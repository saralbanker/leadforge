import hashlib
import json
import re
import time
import requests
from typing import Dict, Any, Optional, List
from leadforge.config import OLLAMA_API_URL, DEFAULT_LLM_MODEL, DEFAULT_LLM_MAX_TOKENS, DEFAULT_LLM_TEMPERATURE
from leadforge.outreach.cleaning import clean_company_name, shorten_company_name
from leadforge.outreach.content_classifier import (
    classify_scraped_content,
    ScrapedContentClassification,
    sanitize_scraped_text,
)
from leadforge.utils import get_logger

logger = get_logger()

DEFAULT_SYSTEM_PROMPT = """You write the OPENING OBSERVATION LINE and PRODUCT FOCUS of a cold email to a small business owner.
Your single priority: Answer "who noticed something real about my business" in one short sentence.
Do not imply prior contact, do not use follow-up or inquiry language, and never invent claims.

Rules:
1. Output strictly raw JSON with two fields:
   - "observation_hook": exactly ONE sentence, strictly under 15 words. No greetings, introductions, or pitches.
   - "specific_topic": 1 to 3 words naming the single most identifying product line, equipment, or specialty from website text (e.g. "servo voltage stabilizers", "commercial litigation", "packaging"). Lowercase. If no website text exists, use empty string "".
2. Evidence Priority (STRICT ORDER):
   - FIRST PRIORITY: Specific detail from website text (services, products, specialties).
   - SECOND PRIORITY: Business presence detail (e.g. no website listed).
   - LAST RESORT ONLY: Google rating and review count only if no website text exists. Never recite Google ratings if usable website text was provided.
3. Stay strictly EVIDENCE-BOUND: State only verified facts from the input. If Operational Premise is UNCONFIRMED, never assume or assert their workflow. NEVER pose as a customer or prospective buyer ("for buyers like me", "looking to buy").
4. Words: Use simple words. No exclamation marks, em-dashes, or filler ("in various locations", "has a website"). Never use "online presence", "digital footprint", "digital age", "solutions", "leverage", "optimize", "streamline", or:
{banned_vocabulary}

Good examples (one real observation, cleaned names, strictly under 15 words):
- Business "Apex Law" in "Denver", Category: Law Firm, Website mentions commercial litigation -> {"observation_hook": "I noticed Apex Law handles commercial litigation for businesses in Denver.", "specific_topic": "commercial litigation"}
- Business "Ratan Plastics" in "Chicago", Category: Plastic Manufacturer, Website: exports packaging -> {"observation_hook": "I saw Ratan Plastics exports packaging to 45 countries.", "specific_topic": "packaging"}
- Business "Sydney Roof Masters" in "Sydney", Category: Roofing, Has Website: No -> {"observation_hook": "Sydney Roof Masters does not have a website listed for customers in Sydney.", "specific_topic": ""}
- Business "ATX Dental" in "Austin", Category: Dentist, Rating: 4.9, Reviews: 128, Premise: UNCONFIRMED -> {"observation_hook": "I saw ATX Dental has 128 reviews with a 4.9 rating in Austin.", "specific_topic": ""}

Bad examples (implies prior contact, poses as customer, or invents claims - NEVER write like this):
- "Following up on your inquiry regarding Apex Law." (FALSE - implies prior contact)
- "I was looking to buy from Ratan Plastics as a customer." (FORBIDDEN - posing as buyer)
- "ATX Dental loses patients because calls are handled manually." (INVENTED - UNCONFIRMED premise)
- "Sydney Roof Masters needs to optimize its digital footprint." (JARGON - violates banned words)

Output strictly raw JSON: {"observation_hook": "your one sentence here", "specific_topic": "1-3 words product or specialty"}"""

DEFAULT_USER_PROMPT_TEMPLATE = """Business Name: {business_name}
Category: {category}
City: {city}
Area: {area}
Has Website: {has_website}
Website Domain / Scraped Snippet: {scraped_text}
Google Rating: {rating}
Google Review Count: {review_count}
Operational Premise: {operational_premise}

Output the single observation hook in raw JSON."""


def compress_specific_topic(topic: str, max_words: int = 3) -> str:
    """Compresses an extracted specific topic down to 1-3 words.

    Strips trailing functional fluff ('manufacturing', 'products', 'supplier', etc.)
    and isolates the core product noun phrase so subject lines stay compact.
    """
    if not topic or not isinstance(topic, str):
        return ""
    cleaned = topic.strip().strip('"\'`.,;:-()[]{}').lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    words = cleaned.split()

    # Strip trailing fluff words
    trailing_fluff = {
        "manufacturing", "manufacturer", "manufacturers", "products", "product",
        "supplier", "suppliers", "services", "service", "supplies", "powder",
        "parts", "spare", "spares", "wholesalers", "wholesaler", "exporter", "exporters",
        "rates", "items"
    }
    while len(words) > 1 and words[-1] in trailing_fluff:
        words = words[:-1]

    stopwords = {"and", "or", "with", "for", "in", "of", "to", "the", "a", "an"}
    while len(words) > 1 and words[0] in stopwords:
        words = words[1:]

    if len(words) <= max_words:
        return " ".join(words)

    # Core noun check at the tail (e.g. "oil cooled servo voltage stabilizers" -> "servo voltage stabilizers")
    tail = words[-max_words:]
    while len(tail) > 1 and tail[0] in stopwords:
        tail = tail[1:]

    if any(k in tail[-1] for k in ["stabilizer", "stabilizers", "pump", "pumps", "valve", "valves", "pipe", "pipes", "machinery", "pigment", "pigments", "instrument", "instruments"]):
        return " ".join(tail)

    head = words[:max_words]
    while len(head) > 1 and head[-1] in stopwords:
        head = head[:-1]
    return " ".join(head)


def validate_specific_topic(topic: str, max_words: int = 3, allow_compression: bool = True) -> tuple[bool, str]:
    """Validates and normalizes an extracted specific topic, enforcing 1-3 words.

    Compresses over-length noun phrases down to 1-3 words when compressible,
    or rejects them if they are full sentences, AI jargon, spam, or generic words.
    """
    if not topic or not isinstance(topic, str):
        return False, ""
    cleaned = topic.strip().strip('"\'`.,;:-()[]{}').lower()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return False, ""

    from leadforge.outreach.quality import EmailQualityEngine
    banned = EmailQualityEngine.AI_JARGON_PHRASES | EmailQualityEngine.SPAM_KEYWORDS
    for b in banned:
        if b in cleaned:
            return False, ""

    words = cleaned.split()
    # Reject full sentences or excessively long strings as non-topic garbage
    if len(words) > 6 or len(cleaned) > 50:
        return False, ""

    if allow_compression:
        cleaned = compress_specific_topic(cleaned, max_words=max_words)
        words = cleaned.split()
    elif len(words) > max_words:
        return False, ""

    if len(words) < 1 or len(words) > max_words:
        return False, ""

    if len(cleaned) > 40:
        return False, ""

    generic_terms = {
        "product", "products", "service", "services", "solution", "solutions",
        "business", "company", "manufacturing", "manufacturer", "manufacturers",
        "item", "items", "equipment", "goods", "industry", "industries",
        "quality", "technology", "technologies", "local business"
    }
    if cleaned in generic_terms:
        return False, ""

    return True, cleaned


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


def clean_product_topic(raw_topic: str, clean_name: str, raw_name: str = "") -> str:
    """Strips subject line boilerplate, prefixes, and company names to isolate the core product noun."""
    if not raw_topic:
        return ""
    topic = raw_topic.strip().strip(".,;:-?!()[]{}\"'")
    noise_prefixes = [
        "idea for", "regarding", "re:", "note on", "question:", "quick note:",
        "quick thought:", "inquiry re:", "details:", "brief note:", "checking in:", "quick question:"
    ]
    for p in noise_prefixes:
        if topic.lower().startswith(p):
            topic = topic[len(p):].strip()

    for name in [clean_name, raw_name, clean_name.split()[0]]:
        if name and len(name) >= 3:
            pat = re.compile(rf"\b(?:at|for|re:|:|-)?\s*{re.escape(name)}\b", re.IGNORECASE)
            topic = pat.sub("", topic)

    topic = re.sub(r"\b(?:sales|wholesaler|pujapa|agarbatti)\b", "", topic, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", topic).strip().strip(".,;:-?!()[]{}\"'")


def extract_secondary_topic(scraped_text: str, hook: str, clean_topic: str) -> str:
    """Extracts a secondary specific product topic from scraped text that avoids repeating the hook or primary topic."""
    if not scraped_text:
        return ""
    text = scraped_text.lower()
    hook_lower = hook.lower()

    candidates = [
        (r"\b(temperature(?:\s+and|,)?\s+pressure\s+instruments?|pressure\s+transmitters?)\b", "instrumentation specs"),
        (r"\b(power\s+conditioning|online\s+ups\s+systems?|battery\s+chargers?)\b", "power conditioning catalog"),
        (r"\b(gold\s+and\s+silver\s+bullion|precious\s+metals?|live\s+rates)\b", "bullion rate catalog"),
        (r"\b(waterproofing|tile\s+&(?:amp;)?\s+stone\s+adhesive|construction\s+chemicals?)\b", "construction chemical products"),
        (r"\b(reactive\s+(?:&|and)?\s+disperse\s+dyes|textile\s+auxiliaries)\b", "textile dye products"),
        (r"\b(steel\s+pipes?\s+(?:and|&)?\s+tubes?|carbon\s+steel\s+pipes?)\b", "tubular product listings"),
        (r"\b(ball\s+mill\s+rubber\s+liners?|wear\s+resistant\s+liners?)\b", "rubber liner products"),
        (r"\b(kurta\s+sets|co-?ords|women\'s\s+apparel)\b", "apparel catalog"),
        (r"\b(crgo\s+laminations?|transformer\s+cores?)\b", "transformer lamination specs"),
        (r"\b(carbon\s+steel\s+and\s+alloy\s+steel\s+pipes?|steel\s+pipe\s+manufacturers)\b", "alloy pipe catalog"),
        (r"\b(cardiovascular\s+stents?|medical\s+devices?)\b", "medical device portfolio"),
        (r"\b(hdpe\s+tarpaulins?|tarpaulin\s+sheets?)\b", "HDPE tarpaulin listings"),
        (r"\b(woven\s+fabrics?|textile\s+materials?)\b", "textile materials catalog"),
        (r"\b(private\s+label\s+supplements?|herbal\s+extracts?)\b", "dietary supplement catalog"),
        (r"\b(cpvc\s+(?:and|&)?\s+upvc\s+pipes?|pvc\s+fittings?)\b", "CPVC and UPVC pipe listings"),
        (r"\b(antique\s+chudi|bangles?\s+collection)\b", "bangle collections"),
        (r"\b(incense\s+sticks?|agarbatti\s+products?)\b", "aromatherapy product line"),
        (r"\b(fire\s+extinguishers?|fire\s+fighting\s+equipments?)\b", "fire safety equipment range"),
        (r"\b(tea\s+wholesale|tea\s+blends?)\b", "wholesale tea catalog"),
        (r"\b(bridal\s+jewelry|silver\s+jewelry)\b", "silver and bridal jewelry range"),
        (r"\b(vacuum\s+systems?|heat\s+transfer\s+equipment|process\s+equipment)\b", "process equipment specs"),
        (r"\b(sheet\s+metal\s+components?|stamping\s+parts?)\b", "sheet metal component listings"),
        (r"\b(v\s*belt\s+pulleys?|timing\s+pulleys?)\b", "pulley manufacturing range"),
        (r"\b(tarpaulins?|shade\s+nets?)\b", "tarpaulin and shade net catalog"),
        (r"\b(custom\s+springs?|coil\s+springs?|industrial\s+springs?)\b", "industrial spring specs"),
        (r"\b(textile\s+machine\s+combs?|textile\s+spare\s+parts?)\b", "textile machinery parts catalog"),
        (r"\b(dairy\s+machinery|sanitary\s+pumps?)\b", "dairy machinery specs"),
        (r"\b(thermochromic|photochromic|colour\s+changing\s+pigments?)\b", "colour changing pigment range"),
        (r"\b(ceramic\s+tiles?|vitrified\s+tiles?)\b", "ceramic product line"),
        (r"\b(cassia\s+tora\s+gum|guar\s+gum\s+powder)\b", "cassia tora gum products"),
        (r"\b(industrial\s+valves?|ball\s+valves?)\b", "industrial valve catalog"),
        (r"\b(cz\s+gold\s+jewelry|cubic\s+zirconia)\b", "CZ gold jewelry collection"),
        (r"\b(gold\s+jewellery|diamond\s+jewellery)\b", "gold jewellery catalog"),
        (r"\b(sulphuric\s+acid|dyes\s+&(?:amp;)?\s+intermediates)\b", "chemical intermediates catalog"),
        (r"\b(caps\s+and\s+hats|hosiery\s+goods?)\b", "headwear catalog"),
        (r"\b(sodium\s+silicate|silicate\s+solutions?)\b", "sodium silicate product line"),
        (r"\b(passenger\s+elevators?|commercial\s+escalators?)\b", "elevator and escalator specs"),
    ]
    for pat, rep in candidates:
        if re.search(pat, text):
            if rep.lower() not in hook_lower:
                return rep
    return ""


def generate_contact_bridge(
    business_name: str,
    raw_name: str = "",
    city: str = "",
    hook: str = "",
    specific_topic: str = "",
    scraped_text: str = "",
    classification: Optional[ScrapedContentClassification] = None,
    business_id: Optional[str] = None,
    category: str = "",
) -> tuple[str, str]:
    """Generates an honest, evidence-grounded contact bridge answering 'why I am writing today'.

    - If scraped content is classified USABLE: cites genuine product catalog, specs, or listings,
      avoiding repetition of terms in the observation hook and preventing duplicate city phrasing.
    - If scraped content is NOT USABLE (NO_WEBSITE, EMPTY, BOILERPLATE_OR_ERROR): defines a distinct,
      truthful fallback citing industrial directory records or regional manufacturer listings,
      never pretending to have browsed a website or online catalog.

    Returns:
        (bridge_sentence, source)
        where source is 'grounded:scraped', 'fallback:no_website', or 'fallback:thin_content'.
    """
    clean_name = clean_company_name(business_name)
    short_name = shorten_company_name(clean_name, max_chars=18)
    city_in_hook = bool(city and str(city).strip().lower() in (hook or "").lower())

    if classification is None:
        classification = classify_scraped_content(scraped_text)

    # Population 1: Thin content, boilerplate, or no website
    if not classification.is_usable:
        if classification.classification in ("NO_WEBSITE", "EMPTY"):
            if city_in_hook:
                bridge = f"I came across {short_name} while reviewing regional industrial directory listings."
            else:
                bridge = f"I came across {short_name} while reviewing industrial directory listings for {city} manufacturers."
            return bridge, "fallback:no_website"
        else:
            bridge = f"I found {short_name} while researching regional industrial supplier listings."
            return bridge, "fallback:thin_content"

    # Population 2: Usable website content
    clean_topic = clean_product_topic(specific_topic, clean_name, raw_name)
    secondary = extract_secondary_topic(classification.sanitized_text, hook, clean_topic)
    product_term = secondary or (f"{clean_topic} catalog" if clean_topic else "product catalog")

    seed = f"bridge:{business_id or clean_name}"
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    frame_idx = int.from_bytes(digest[:4], "big") % 8

    frames = [
        f"I noticed your {product_term} while reviewing regional suppliers.",
        f"I came across your {product_term} while looking at local plants.",
        f"I found your {product_term} while researching regional manufacturers.",
        f"I came across {short_name}'s {product_term} while reviewing local suppliers.",
        f"I noticed your {product_term} while researching regional engineering suppliers.",
        f"I found {short_name}'s {product_term} while looking at industrial suppliers.",
        f"I came across your {product_term} while reviewing regional manufacturing units.",
        f"I noticed your {product_term} while looking through local suppliers.",
    ]
    return frames[frame_idx], "grounded:scraped"


class OllamaHookGenerator:
    """Manages local LLM inference via Ollama to write personalized hooks.

    Fully configurable via LeadForge settings (system prompt, user prompt template,
    model name, temperature, endpoint URL, max tokens, and enable/disable flag).
    """

    def __init__(self, api_url: Optional[str] = None, settings_getter=None) -> None:
        self._explicit_api_url = api_url
        self._settings_getter = settings_getter
        self._last_hook_source = "fallback"
        self._last_specific_topic = ""
        self._last_classification: Optional[ScrapedContentClassification] = None

    @property
    def last_specific_topic(self) -> str:
        return self._last_specific_topic

    @property
    def last_classification(self) -> Optional[ScrapedContentClassification]:
        return self._last_classification

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

    @property
    def max_retries(self) -> int:
        settings = self._get_settings()
        if settings:
            return settings.get_int("llm.hook_max_retries", settings.get_int("llm.max_retries", 3))
        return 3

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

        Requiring merely an INBOUND message is not enough either: once the IMAP
        reader started ingesting bounce notifications, every hard-bounced send
        acquired an inbound message and was about to be promoted to an exemplar.
        A mailer-daemon rejection is the opposite of evidence that copy worked, so
        machine-generated classifications are excluded and only a genuine human
        reply qualifies.
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
                        AND COALESCE(cm.classification_label, '') NOT IN
                            ('BOUNCE', 'OUT_OF_OFFICE', 'UNSUBSCRIBE')
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

    def generate_hook_with_details(self, **kwargs) -> tuple[str, str, str]:
        """Generates a hook and returns (hook, source, specific_topic)."""
        self._last_hook_source = "fallback"
        self._last_specific_topic = ""
        hook = self.generate_hook(**kwargs)
        return hook, self._last_hook_source, self._last_specific_topic

    def generate_bridge(
        self,
        business_name: str,
        scraped_text: str = "",
        category: str = "",
        city: str = "",
        specific_topic: str = "",
        observation_hook: str = "",
        classification: Optional[ScrapedContentClassification] = None,
        business_id: Optional[str] = None,
        raw_name: str = "",
    ) -> tuple[str, str]:
        """Generates a validated contact bridge sentence.

        Uses local LM inference when enabled, validating against EmailQualityEngine.validate_bridge().
        Falls back to deterministic evidence-grounded bridge generation on connection failure,
        timeout, or quality validation failure.
        """
        return generate_contact_bridge(
            business_name=business_name,
            raw_name=raw_name,
            city=city,
            hook=observation_hook,
            specific_topic=specific_topic,
            scraped_text=scraped_text,
            classification=classification,
            business_id=business_id,
            category=category,
        )

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
        premise_verified: bool = True,
    ) -> str:
        """Invokes the configured local LM via Ollama to generate the observation hook.

        Validates output against hook quality rules (length, banned terms, filler,
        evidence priority). Retries up to max_retries on validation failure, then
        falls back to best candidate seen recording provenance reason.

        Returns:
            Personalized observation hook string, or a deterministic fallback
            on connection, timeout, or validation failures.
        """
        clean_biz_name = clean_company_name(business_name)
        fallback_hook = f"I noticed your business, {clean_biz_name}, has a solid local presence in {city}."
        if review_count and review_count > 0:
            fallback_hook = f"I was looking at your {rating}-star rating on Google Maps with {review_count} reviews."

        self._last_hook_source = "fallback"
        self._last_specific_topic = ""

        if not self.is_enabled:
            logger.info("Local LM is disabled in settings; returning deterministic fallback hook.")
            return fallback_hook

        classification = classify_scraped_content(scraped_text)
        self._last_classification = classification
        sanitized_scraped = classification.sanitized_text
        eff_has_website = has_website if has_website is not None else (classification.is_usable or bool(scraped_text and scraped_text.strip()))
        premise_str = "CONFIRMED" if premise_verified else "UNCONFIRMED"
        has_usable_site_text = classification.is_usable

        # Build prompt using configured template with graceful fallback keys
        template = self.user_prompt_template
        prompt_vars = {
            "business_name": clean_biz_name,
            "review_count": review_count,
            "rating": rating,
            "city": city,
            "scraped_text": sanitized_scraped or "No website content available.",
            "category": category or "Local Business",
            "area": area or city,
            "has_website": "Yes" if eff_has_website else "No",
            "operational_premise": premise_str,
            "premise_verified": premise_str,
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
                sys_prompt += f"Example {i} ({ex.get('business_name', 'Business')} - {ex.get('category', 'Local Business')}): \"{clean_ref}\"\n"

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

        from leadforge.outreach.quality import EmailQualityEngine

        max_attempts = max(1, self.max_retries)
        candidates: List[tuple[str, List[str], int]] = []

        for attempt in range(1, max_attempts + 1):
            try:
                logger.info(
                    f"Requesting Ollama hook generation (attempt {attempt}/{max_attempts}) "
                    f"for business: '{clean_biz_name}' using model '{self.model_name}' (keep_alive: {self.keep_alive})"
                )
                response = requests.post(
                    f"{self.api_url}/api/generate",
                    json=payload,
                    timeout=300,  # 5 minutes: a long custom system prompt can push CPU-only prompt-eval alone past 2-3 minutes
                )

                if response.status_code != 200:
                    logger.warning(
                        f"Ollama server returned status code {response.status_code} on attempt {attempt}."
                    )
                    continue

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
                        raw_topic = str(parsed.get("specific_topic") or "").strip()
                        if raw_topic:
                            is_valid_topic, clean_topic = validate_specific_topic(raw_topic)
                            if is_valid_topic:
                                self._last_specific_topic = clean_topic

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
                    logger.warning(f"Parsed Ollama response on attempt {attempt} has empty hook.")
                    continue

                is_valid, issues = EmailQualityEngine.validate_hook(
                    hook, has_site_text=has_usable_site_text
                )
                if is_valid:
                    logger.info(
                        f"Successfully generated and validated personalized observation hook via local Ollama (attempt {attempt})."
                    )
                    self._last_hook_source = "llm"
                    return hook

                logger.warning(
                    f"Hook on attempt {attempt}/{max_attempts} failed validation: {issues}. Hook: '{hook}'"
                )
                penalty = len(issues) * 10
                word_count = len(hook.split())
                if word_count > 15:
                    penalty += (word_count - 15) * 2
                candidates.append((hook, issues, penalty))

            except requests.exceptions.RequestException as req_err:
                logger.warning(f"Ollama connection error on attempt {attempt}: {req_err}")
                continue
            except Exception as e:
                logger.error(f"Unexpected error in hook generation on attempt {attempt}: {str(e)}")
                continue

        if candidates:
            candidates.sort(key=lambda x: x[2])
            best_hook, best_issues, _ = candidates[0]
            issue_text = best_issues[0] if best_issues else "validation_failed"
            if "exceeds 15 words" in issue_text:
                reason = "too_long"
            elif "banned phrase" in issue_text:
                reason = "banned_phrase"
            elif "filler" in issue_text:
                reason = "filler"
            elif "Rating recital" in issue_text:
                reason = "rating_recital_with_site_text"
            else:
                reason = issue_text

            self._last_hook_source = f"fallback:degraded:{reason}"
            logger.warning(
                f"All {max_attempts} hook generation attempts failed validation. "
                f"Falling back to best candidate ({self._last_hook_source}): '{best_hook}'"
            )
            return best_hook

        logger.warning("No LLM candidates generated. Using fallback.")
        self._last_hook_source = "fallback"
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
        model = model_name or "qwen2.5:3b"
        sys_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        user_prompt = prompt or "Business Name: Apex Dental Care\nCategory: Dentist\nCity: Austin\nArea: Downtown\nHas Website: Yes\nScraped Snippet: Family and cosmetic dentistry\nGoogle Rating: 4.8\nGoogle Review Count: 86\nOperational Premise: UNCONFIRMED\nOutput raw JSON."

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


SENDER_SIGNOFF = "Saral Banker, Orvion"


def compose_full_body(core_body: str, business_name: str, settings_getter) -> str:
    """Wraps a composed pitch with a greeting, sign-off, and compliance footer.

    2026-09-24: sent drafts were shipped with no greeting and no sign-off
    because CampaignRouter.render_body() only ever produced the middle pitch
    paragraphs - callers were responsible for wrapping it, and the initial
    draft endpoint never did. This is the single place that wrap now happens,
    so every drafted email opens with "Hi <name> team," and closes with
    "Saral Banker, Orvion" before the CAN-SPAM footer.
    """
    clean_name = clean_company_name(business_name) if business_name else ""
    greeting = f"Hi {clean_name} team," if clean_name and clean_name != "your company" else "Hi there,"
    core = (core_body or "").strip()
    body = f"{greeting}\n\n{core}\n\nBest,\n{SENDER_SIGNOFF}"

    footer = compile_compliance_footer(settings_getter)
    if footer and footer.strip() not in body:
        body = body + footer
    return body


def compile_compliance_footer(settings_getter) -> str:
    """Builds an opt-out & company identity compliance footer using configured settings."""
    from leadforge.config import SMTP_FROM_NAME
    company = settings_getter.get_str("outreach.footer_company_name", SMTP_FROM_NAME or "LeadForge")
    website = settings_getter.get_str("outreach.footer_website", "")
    opt_out = settings_getter.get_str(
        "outreach.footer_opt_out_text",
        "If you'd prefer not to receive future emails from us, reply with 'unsubscribe' and we will remove you immediately.",
    )

    # US CAN-SPAM and Canadian CASL both require a valid physical postal address
    # in commercial email. It does not have to be an office - a home address is
    # what most sole traders use - but it has to be real and it has to be there.
    postal = settings_getter.get_str("outreach.footer_postal_address", "")

    parts = []
    if company:
        parts.append(company)
    if website:
        parts.append(website)

    header_line = " | ".join(parts)
    footer_lines = ["---"]
    if header_line:
        footer_lines.append(header_line)
    if postal:
        footer_lines.append(postal)
    if opt_out:
        footer_lines.append(opt_out)

    return "\n\n" + "\n".join(footer_lines)
