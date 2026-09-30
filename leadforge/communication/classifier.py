"""LLM Inbound Reply Classification Engine."""

import json
import re
import requests
from typing import Optional
from leadforge.config import OLLAMA_API_URL
from leadforge.utils import get_logger

logger = get_logger()

VALID_CLASSIFICATIONS = {"POSITIVE", "NEGATIVE", "UNSUBSCRIBE", "BOUNCE", "OUT_OF_OFFICE", "NEUTRAL"}

# Hard bounce: the address itself is invalid - a 5xx/5.x.x SMTP code, or a DSN
# saying the mailbox does not exist. Never worth retrying.
_HARD_BOUNCE_PATTERNS = [
    r"\b5\d{2}[\s-]5\.\d\.\d\b",
    r"\baddress not found\b",
    r"\buser unknown\b",
    r"\bno such user\b",
    r"\bmailbox not found\b",
    r"\bdoes not exist\b",
    r"\brecipient address rejected\b",
    r"\binvalid recipient\b",
    r"\bunknown user\b",
    r"\bunknown recipient\b",
    r"\bno mailbox by that name\b",
]

# Soft bounce: a temporary delivery problem - a 4xx/4.x.x SMTP code, a full
# mailbox, or a greylisting deferral. The address may still be good, so it
# stays eligible for a later retry.
_SOFT_BOUNCE_PATTERNS = [
    r"\b4\d{2}[\s-]4\.\d\.\d\b",
    r"\bmailbox full\b",
    r"\bquota exceeded\b",
    r"\bover quota\b",
    r"\btry again later\b",
    r"\btemporarily deferred\b",
    r"\bgreylisted\b",
    r"\bmailbox unavailable, try again\b",
    r"\bmessage delayed\b",
]


def classify_bounce_severity(text: str) -> str:
    """Classifies a bounce message body/subject as 'hard' or 'soft'.

    'hard' (permanent - the address is invalid, never retry it) or 'soft'
    (temporary - full mailbox, greylisted, deferred; still retryable).

    Defaults to 'hard' when no soft-bounce indicator is present at all:
    treating an ambiguous bounce as permanent is the safer failure mode for
    a cold-outreach sender protecting its own deliverability.
    """
    if not text:
        return "hard"
    lower = text.lower()
    has_soft = any(re.search(pat, lower) for pat in _SOFT_BOUNCE_PATTERNS)
    has_hard = any(re.search(pat, lower) for pat in _HARD_BOUNCE_PATTERNS)
    if has_soft and not has_hard:
        return "soft"
    return "hard"


class LLMReplyClassifier:
    """Classifies prospect email replies into structured intent categories."""

    def __init__(self, api_url: Optional[str] = None):
        self._explicit_api_url = api_url

    def _get_settings(self):
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
            return settings.get_str("llm.model_name", "qwen2.5:3b")
        return "qwen2.5:3b"

    @staticmethod
    def strip_quoted_reply(text: str) -> str:
        """Strips quoted previous emails, headers, and signature disclaimers to isolate the prospect's actual reply."""
        if not text:
            return ""
        lines = text.splitlines()
        cleaned = []
        quote_header_pattern = re.compile(
            r"^(On\s+.+?\bwrote:|-+\s*Original Message\s*-+|-+\s*Forwarded message\s*-+|From:\s*.+@.+|\*?CONFIDENTIALITY NOTICE)",
            re.IGNORECASE,
        )
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(">"):
                continue
            if quote_header_pattern.search(stripped):
                break
            cleaned.append(line)
        res = "\n".join(cleaned).strip()
        return res if res else text.strip()

    def classify_reply(self, email_body: str) -> str:
        """Classifies inbound email body into intent category.

        Returns:
            One of POSITIVE, NEGATIVE, UNSUBSCRIBE, BOUNCE, OUT_OF_OFFICE, NEUTRAL.
        """
        if not email_body or not email_body.strip():
            return "NEUTRAL"

        effective_body = self.strip_quoted_reply(email_body)
        text_lower = effective_body.lower()

        # Deterministic regex shortcuts for obvious cases
        if any(kw in text_lower for kw in ["unsubscribe", "stop emailing", "remove me", "take me off", "opt out", "opt-out", "please remove", "do not email", "dont email"]):
            return "UNSUBSCRIBE"
        if any(kw in text_lower for kw in ["out of office", "auto-reply", "automatic reply", "on vacation", "away from my email", "away from the office", "annual leave", "maternity leave", "paternity leave"]):
            return "OUT_OF_OFFICE"
        if any(kw in text_lower for kw in [
            "undeliverable", "mail delivery failed", "address not found", "delivery status notification",
            "failed to deliver", "returned to sender", "user unknown", "mailbox unavailable",
            "recipient address rejected", "550 5.1.1", "5.1.1", "failure notice", "delivery failure", "could not be delivered"
        ]):
            return "BOUNCE"

        # LLM Classification
        prompt = (
            f"Classify the following email reply from a prospect into EXACTLY ONE label:\n"
            f"POSITIVE, NEGATIVE, UNSUBSCRIBE, BOUNCE, OUT_OF_OFFICE, NEUTRAL.\n\n"
            f"Email body: \"{effective_body[:1000]}\"\n\n"
            f"Output JSON format: {{\"label\": \"...\"}}"
        )

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": "You are a B2B sales email intent classifier. Output ONLY JSON.",
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0, "num_predict": 50},
        }

        try:
            resp = requests.post(f"{self.api_url}/api/generate", json=payload, timeout=10)
            if resp.status_code == 200:
                raw = resp.json().get("response", "").strip()
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    label = json.loads(match.group(0)).get("label", "").upper().strip()
                    if label in VALID_CLASSIFICATIONS:
                        return label
        except Exception as e:
            logger.warning(f"[LLMReplyClassifier] Ollama classification failed: {e}. Falling back to rule-based classifier.")

        # Fallback rule-based matching: Check NEGATIVE before POSITIVE to handle "not interested"
        negative_keywords = [
            "not interested", "no thanks", "dont contact", "don't contact", "remove", "busy",
            "wrong person", "wrong company", "do not contact", "not looking", "please don't", "please dont"
        ]
        positive_keywords = [
            "interested", "call", "demo", "pricing", "quote", "meeting", "yes", "sure",
            "sounds good", "let's talk", "lets talk", "schedule", "reach out"
        ]

        if any(kw in text_lower for kw in negative_keywords):
            return "NEGATIVE"
        if any(kw in text_lower for kw in positive_keywords):
            return "POSITIVE"

        return "NEUTRAL"
