import json
import re
import time
import requests
from typing import Dict, Any, Optional, List
from leadforge.config import OLLAMA_API_URL, DEFAULT_LLM_MODEL, DEFAULT_LLM_MAX_TOKENS, DEFAULT_LLM_TEMPERATURE
from leadforge.utils import get_logger

logger = get_logger()

DEFAULT_SYSTEM_PROMPT = """You are an expert B2B outreach copywriter specialized in industrial, manufacturing, and local business growth. Write a concise, highly tailored observation hook for the target business based on their gathered operational details.

Writing Rules:
1. Write like a real business development professional sending a quick, relevant inquiry.
2. Ground the observation specifically in their real industry, city/industrial zone, and digital infrastructure (e.g. absence of digital spec catalog or online procurement).
3. Do NOT use generic pleasantries, greetings, or "hope you are well". Keep it under 25 words.
4. Output strictly raw JSON: {"observation_hook": "Your single observation sentence here."}
5. NEVER use any of these words or phrases — they read as marketing filler and will get the email rejected:
{banned_vocabulary}"""

DEFAULT_USER_PROMPT_TEMPLATE = """Business Name: {business_name}
Category: {category}
City: {city}
Area / Industrial Zone: {area}
Has Website: {has_website}
Website Domain / Scraped Snippet: {scraped_text}
Google Rating: {rating}
Google Review Count: {review_count}

Output the single observation hook in raw JSON."""


def banned_vocabulary() -> str:
    """The words EmailQualityEngine rejects, formatted for the system prompt.

    Derived from the quality engine's own constants so the prompt and the gate
    can never disagree — previously the prompt named 2 of the 23 banned terms,
    and the model reached for the other 21 unprompted.
    """
    from leadforge.outreach.quality import EmailQualityEngine

    terms = sorted(EmailQualityEngine.AI_JARGON_PHRASES | EmailQualityEngine.SPAM_KEYWORDS)
    return ", ".join(f'"{t}"' for t in terms)


def resolve_system_prompt(template: str) -> str:
    """Ensures the quality gate's banned vocabulary reaches the model.

    Substitutes {banned_vocabulary} where the prompt provides the placeholder.
    A custom prompt configured in settings normally will not, so the list is
    appended instead — otherwise operators who tune their own prompt silently
    lose the guard and the gate rejects copy the model was never warned about.
    """
    if not template:
        return template
    if "{banned_vocabulary}" in template:
        return template.replace("{banned_vocabulary}", banned_vocabulary())
    return (
        template.rstrip()
        + "\n\nNever use these words or phrases — they will get the email rejected:\n"
        + banned_vocabulary()
    )


def sanitize_scraped_text(text: str) -> str:
    """Sanitizes text extracted from websites to prevent prompt injection."""
    if not text:
        return ""

    # 1. Truncate to a sensible limit to save context and limit attack vector
    text = text[:1500]

    # 2. Neutralize chat template tokens and special markers
    text = re.sub(r"(?i)</?system.*?>", "[tag_removed]", text)
    text = re.sub(r"\[/?INST\]", "[tag_removed]", text)
    text = re.sub(r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>", "[token_removed]", text)

    # 3. Block/remove common instruction-override keywords (case-insensitive)
    injection_patterns = [
        r"(?i)\bignore\s+(?:all\s+|the\s+)?(?:previous|instructions|rules)\b",
        r"(?i)\bsystem\s+prompt\b",
        r"(?i)\bforget\s+(?:all\s+|the\s+)?(?:previous|instructions|rules)\b",
        r"(?i)\byou\s+must\s+output\b",
        r"(?i)\boverride\s+rules\b",
        r"(?i)\bnew\s+instructions\b",
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, "[removed]", text)

    # 4. Remove characters that look like JSON markup or raw angle brackets to avoid prompt context escaping
    text = text.replace("{", "[").replace("}", "]").replace("<", "&lt;").replace(">", "&gt;")

    return text.strip()


class OllamaHookGenerator:
    """Manages local LLM inference via Ollama to write personalized hooks.

    Fully configurable via LeadForge settings (system prompt, user prompt template,
    model name, temperature, endpoint URL, max tokens, and enable/disable flag).
    """

    def __init__(self, api_url: Optional[str] = None, settings_getter=None) -> None:
        self._explicit_api_url = api_url
        self._settings_getter = settings_getter

    def _get_settings(self):
        if self._settings_getter:
            return self._settings_getter
        try:
            from leadforge.repositories.settings import SettingsCache
            return SettingsCache()
        except Exception:
            return None

    @property
    def api_url(self) -> str:
        if self._explicit_api_url:
            return self._explicit_api_url
        settings = self._get_settings()
        if settings:
            return settings.get_str("llm.api_url", OLLAMA_API_URL)
        return OLLAMA_API_URL

    @property
    def model_name(self) -> str:
        settings = self._get_settings()
        if settings:
            return settings.get_str("llm.model_name", DEFAULT_LLM_MODEL)
        return DEFAULT_LLM_MODEL

    @property
    def system_prompt(self) -> str:
        settings = self._get_settings()
        if settings:
            return settings.get_str("llm.system_prompt", DEFAULT_SYSTEM_PROMPT)
        return DEFAULT_SYSTEM_PROMPT

    @property
    def user_prompt_template(self) -> str:
        settings = self._get_settings()
        if settings:
            return settings.get_str("llm.user_prompt_template", DEFAULT_USER_PROMPT_TEMPLATE)
        return DEFAULT_USER_PROMPT_TEMPLATE

    @property
    def temperature(self) -> float:
        settings = self._get_settings()
        if settings:
            return settings.get_float("llm.temperature", DEFAULT_LLM_TEMPERATURE)
        return DEFAULT_LLM_TEMPERATURE

    @property
    def max_tokens(self) -> int:
        settings = self._get_settings()
        if settings:
            return settings.get_int("llm.max_tokens", DEFAULT_LLM_MAX_TOKENS)
        return DEFAULT_LLM_MAX_TOKENS

    @property
    def keep_alive(self) -> str:
        """How long Ollama keeps the model resident after a request.

        "0s" evicts it immediately, so the next email pays a full reload and
        loses the cached prompt prefix — measured at 24s per hook versus 7s
        with the model resident.
        """
        import os
        default = os.getenv("OLLAMA_KEEP_ALIVE", "10m").strip() or "10m"
        settings = self._get_settings()
        if settings:
            return settings.get_str("llm.keep_alive", default)
        return default

    @property
    def is_enabled(self) -> bool:
        settings = self._get_settings()
        if settings:
            return settings.get_str("llm.enabled", "true").lower() in ("true", "1", "yes")
        return True

    @staticmethod
    def get_approved_exemplars(category: str = "", limit: int = 2) -> List[Dict[str, str]]:
        """Returns past drafts that earned a reply, for in-context learning.

        Previously this selected on status IN ('APPROVED', 'SENT') — i.e. that
        someone clicked approve. That is not evidence the copy worked. The only
        two qualifying drafts had been sent to fabricated addresses and hard
        bounced, and the model dutifully cloned their sentence structure into
        every subsequent hook.

        A reply is the one signal that a human read the email and responded, so
        that is what qualifies now. With no replies recorded, this returns
        nothing and the model writes from the prompt alone.
        """
        try:
            from leadforge.database import get_db_connection
            conn = get_db_connection()
            cursor = conn.cursor()
            query = """
                SELECT ed.subject, ed.body, b.name as business_name,
                       bt.name as category, a.city, a.area
                FROM email_drafts ed
                JOIN opportunities o ON ed.opportunity_id = o.id
                JOIN businesses b ON o.business_id = b.id
                LEFT JOIN business_types bt ON b.business_type_id = bt.id
                LEFT JOIN addresses a ON b.id = a.business_id
                WHERE ed.status = 'SENT'
                  AND ed.error_message IS NULL
                  AND EXISTS (
                      SELECT 1 FROM communication_threads ct
                      JOIN communication_messages cm ON cm.thread_id = ct.id
                      WHERE ct.business_id = b.id AND cm.direction = 'INBOUND'
                  )
            """
            params = []
            if category:
                query += " AND (bt.name LIKE ? OR b.name LIKE ?)"
                params.extend([f"%{category}%", f"%{category}%"])
            query += " ORDER BY ed.updated_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.debug(f"[Generator] Exemplar lookup failed: {exc}")
            return []

    def generate_hook_with_source(self, **kwargs) -> tuple[str, str]:
        """Generates a hook and reports where it came from.

        Returns:
            (hook, source) where source is 'llm' when the model produced the
            text and 'fallback' when the deterministic stand-in was used.
            Callers must persist this: every failure path returns the same
            generic sentence, so without it an Ollama outage silently mails
            identical boilerplate to every lead in a batch.
        """
        self._last_hook_source = "fallback"
        hook = self.generate_hook(**kwargs)
        return hook, self._last_hook_source

    def generate_hook(
        self,
        business_name: str,
        review_count: int,
        rating: float,
        city: str,
        scraped_text: str,
        category: str = "",
        area: str = "",
        has_website: Optional[bool] = None,
    ) -> str:
        """Invokes the configured local LM via Ollama to generate the observation hook.

        Returns:
            Personalized observation hook string, or a deterministic fallback
            on connection, timeout, or format validation failures.
        """
        fallback_hook = f"I noticed your business, {business_name}, has a solid local presence in {city}."
        if review_count and review_count > 0:
            fallback_hook = f"I was looking at your {rating}-star rating on Google Maps with {review_count} reviews."

        self._last_hook_source = "fallback"

        if not self.is_enabled:
            logger.info("Local LM is disabled in settings; returning deterministic fallback hook.")
            return fallback_hook

        sanitized_scraped = sanitize_scraped_text(scraped_text)
        eff_has_website = has_website if has_website is not None else bool(scraped_text)

        # Build prompt using configured template with graceful fallback keys
        template = self.user_prompt_template
        prompt_vars = {
            "business_name": business_name,
            "review_count": review_count,
            "rating": rating,
            "city": city,
            "scraped_text": sanitized_scraped or "No website content available.",
            "category": category or "Local Business",
            "area": area or city,
            "has_website": "Yes" if eff_has_website else "No",
        }

        try:
            prompt_content = template.format(**prompt_vars)
        except KeyError:
            # If user customized template with partial keys, safely interpolate known variables
            prompt_content = template
            for k, v in prompt_vars.items():
                prompt_content = prompt_content.replace(f"{{{k}}}", str(v))

        # Retrieve user-approved exemplars to guide the model with accepted reference patterns
        exemplars = self.get_approved_exemplars(category=category, limit=2)
        if not exemplars and category:
            exemplars = self.get_approved_exemplars(category="", limit=2)

        sys_prompt = resolve_system_prompt(self.system_prompt)
        if exemplars:
            sys_prompt += "\n\nUser-Approved Reference Examples (Follow this preferred tone and structure):\n"
            for i, ex in enumerate(exemplars, 1):
                clean_ref = ex.get("body", "").split("\n\n---")[0].strip().replace("\n", " ")
                if len(clean_ref) > 200:
                    clean_ref = clean_ref[:197] + "..."
                sys_prompt += f"Example {i} ({ex.get('business_name', 'Business')} - {ex.get('category', 'Manufacturing')}): \"{clean_ref}\"\n"

        payload = {
            "model": self.model_name,
            "prompt": prompt_content,
            "system": sys_prompt,
            "format": "json",
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        try:
            logger.info(f"Requesting Ollama hook generation for business: '{business_name}' using model '{self.model_name}' (keep_alive: {self.keep_alive})")
            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=300,  # 5 minutes: a long custom system prompt can push CPU-only prompt-eval alone past 2-3 minutes
            )

            if response.status_code != 200:
                logger.warning(f"Ollama server returned status code {response.status_code}. Using fallback.")
                return fallback_hook

            response_json = response.json()
            raw_response = response_json.get("response", "").strip()

            # Clean potential markdown JSON wrapping
            json_str = raw_response
            match = re.search(r"\{.*\}", raw_response, re.DOTALL)
            if match:
                json_str = match.group(0)

            hook = ""
            try:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict):
                    hook = (
                        parsed.get("observation_hook")
                        or parsed.get("hook")
                        or parsed.get("observation")
                        or parsed.get("pitch")
                        or parsed.get("text")
                        or parsed.get("sentence")
                        or parsed.get("message")
                        or parsed.get("result")
                        or ""
                    ).strip()
                    if not hook and parsed.get("body"):
                        # Some system prompts (e.g. full-email schemas) return subject/body
                        # instead of a standalone hook fragment. Use the opening of the body
                        # as the observation hook rather than discarding the generation.
                        body_text = str(parsed["body"]).strip()
                        first_sentence = re.split(r"(?<=[.!?])\s+", body_text, maxsplit=1)[0]
                        hook = first_sentence.strip()
                    if not hook:
                        # Last resort: personalization_basis is a short internal label, not
                        # reader-facing prose, but it beats discarding the generation entirely.
                        hook = str(parsed.get("personalization_basis") or "").strip()
                    if not hook and len(parsed) == 1:
                        # Grab whatever single value is in the dict
                        hook = str(list(parsed.values())[0]).strip()
                elif isinstance(parsed, str):
                    hook = parsed.strip()
            except Exception:
                hook = ""

            if not hook:
                logger.warning("Parsed Ollama response has empty hook. Using fallback.")
                return fallback_hook

            logger.info("Successfully generated personalized observation hook via local Ollama.")
            self._last_hook_source = "llm"
            return hook

        except requests.exceptions.RequestException as req_err:
            logger.warning(f"Ollama connection error: {req_err}. Using fallback.")
            return fallback_hook
        except Exception as e:
            logger.error(f"Unexpected error in hook generation: {str(e)}")
            return fallback_hook

    @classmethod
    def test_connection(cls, api_url: Optional[str] = None) -> Dict[str, Any]:
        """Tests connectivity to Ollama server and lists installed local models."""
        url = (api_url or OLLAMA_API_URL).rstrip("/")
        start = time.time()
        try:
            resp = requests.get(f"{url}/api/tags", timeout=5.0)
            latency_ms = round((time.time() - start) * 1000, 1)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name") for m in data.get("models", []) if m.get("name")]
                return {
                    "connected": True,
                    "endpoint": url,
                    "models": models,
                    "latency_ms": latency_ms,
                    "model_count": len(models),
                    "error": None,
                }
            return {
                "connected": False,
                "endpoint": url,
                "models": [],
                "latency_ms": latency_ms,
                "error": f"Ollama HTTP {resp.status_code}: {resp.text[:100]}",
            }
        except Exception as e:
            return {
                "connected": False,
                "endpoint": url,
                "models": [],
                "latency_ms": round((time.time() - start) * 1000, 1),
                "error": str(e),
            }

    @classmethod
    def test_inference(
        cls,
        api_url: Optional[str] = None,
        model_name: Optional[str] = None,
        system_prompt: Optional[str] = None,
        prompt: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 150,
    ) -> Dict[str, Any]:
        """Runs a test generation against the local LM and returns timing and generated output."""
        url = (api_url or OLLAMA_API_URL).rstrip("/")
        model = model_name or "llama3.1:8b"
        sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        user_prompt = prompt or "Business Name: Shree Ram Engineering Works\nCategory: CNC Machining\nCity: Ahmedabad\nOutput raw JSON."

        payload = {
            "model": model,
            "prompt": user_prompt,
            "system": sys_prompt,
            "format": "json",
            "stream": False,
            "keep_alive": "0s",
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        start = time.time()
        try:
            resp = requests.post(f"{url}/api/generate", json=payload, timeout=300.0)
            latency_ms = round((time.time() - start) * 1000, 1)
            if resp.status_code == 200:
                data = resp.json()
                raw_text = data.get("response", "").strip()
                return {
                    "success": True,
                    "raw_response": raw_text,
                    "latency_ms": latency_ms,
                    "model": model,
                    "error": None,
                }
            return {
                "success": False,
                "raw_response": None,
                "latency_ms": latency_ms,
                "model": model,
                "error": f"Ollama returned HTTP {resp.status_code}: {resp.text[:200]}",
            }
        except Exception as e:
            return {
                "success": False,
                "raw_response": None,
                "latency_ms": round((time.time() - start) * 1000, 1),
                "model": model,
                "error": str(e),
            }


def compile_compliance_footer(settings_getter) -> str:
    """Builds an opt-out & company identity compliance footer using configured settings."""
    from leadforge.config import SMTP_FROM_NAME
    company = settings_getter.get_str("outreach.footer_company_name", SMTP_FROM_NAME or "LeadForge")
    website = settings_getter.get_str("outreach.footer_website", "")
    opt_out = settings_getter.get_str(
        "outreach.footer_opt_out_text",
        "If you'd prefer not to receive future emails from us, reply with 'unsubscribe' and we will remove you immediately.",
    )

    parts = []
    if company:
        parts.append(company)
    if website:
        parts.append(website)

    header_line = " | ".join(parts)
    footer_lines = ["---"]
    if header_line:
        footer_lines.append(header_line)
    if opt_out:
        footer_lines.append(opt_out)

    return "\n\n" + "\n".join(footer_lines)
