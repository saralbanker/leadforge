import json
import re
import time
import requests
from typing import Dict, Any, Optional, List
from leadforge.config import OLLAMA_API_URL
from leadforge.utils import get_logger

logger = get_logger()

DEFAULT_SYSTEM_PROMPT = """You are an outreach copywriter. Write a single, personalized observation sentence about a local business based on their details. This sentence will be the first line of an email.

Writing Rules:
1. Write like a real person sending a quick email from their phone. Keep it under 18 words.
2. Start immediately with a specific detail (e.g. "I noticed your profile has 48 reviews but no link to a website").
3. Do NOT use introductory greeting fluff or say "hope you are well".
4. Return ONLY a JSON payload conforming to the format below. Do not output any other conversational text or surrounding explanations.

JSON Format:
{
  "observation_hook": "Your single observation sentence goes here."
}
"""

DEFAULT_USER_PROMPT_TEMPLATE = """Business Name: {business_name}
Google Review Count: {review_count}
Google Rating: {rating}
City: {city}
Scraped Website Snippet: {scraped_text}

Output the single observation hook in raw JSON.
"""


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
            return settings.get_str("llm.model_name", "llama3.2:3b")
        return "llama3.2:3b"

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
            return settings.get_float("llm.temperature", 0.2)
        return 0.2

    @property
    def max_tokens(self) -> int:
        settings = self._get_settings()
        if settings:
            return settings.get_int("llm.max_tokens", 35)
        return 35

    @property
    def is_enabled(self) -> bool:
        settings = self._get_settings()
        if settings:
            return settings.get_str("llm.enabled", "true").lower() in ("true", "1", "yes")
        return True

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

        payload = {
            "model": self.model_name,
            "prompt": prompt_content,
            "system": self.system_prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.max_tokens,
            },
        }

        try:
            logger.info(f"Requesting Ollama hook generation for business: '{business_name}' using model '{self.model_name}'")
            response = requests.post(
                f"{self.api_url}/api/generate",
                json=payload,
                timeout=15,  # Limit timeout for local CPU execution
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
                    if not hook and len(parsed) == 1:
                        # Grab whatever single value is in the dict
                        hook = str(list(parsed.values())[0]).strip()
                elif isinstance(parsed, str):
                    hook = parsed.strip()
            except Exception:
                # If model returned plain text instead of JSON
                clean_raw = raw_response.strip().strip('"').strip("'")
                if clean_raw and not clean_raw.startswith("{") and len(clean_raw) < 300:
                    hook = clean_raw

            if not hook:
                logger.warning("Parsed Ollama response has empty hook. Using fallback.")
                return fallback_hook

            logger.info("Successfully generated personalized observation hook via local Ollama.")
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
        model = model_name or "llama3.2:3b"
        sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        user_prompt = prompt or "Business Name: Shree Ram Engineering Works\nCategory: CNC Machining\nCity: Ahmedabad\nOutput raw JSON."

        payload = {
            "model": model,
            "prompt": user_prompt,
            "system": sys_prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        start = time.time()
        try:
            resp = requests.post(f"{url}/api/generate", json=payload, timeout=25.0)
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
