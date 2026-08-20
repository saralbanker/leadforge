"""LLM Inbound Reply Classification Engine."""

import json
import re
import requests
from typing import Optional
from leadforge.config import OLLAMA_API_URL
from leadforge.utils import get_logger

logger = get_logger()

VALID_CLASSIFICATIONS = {"POSITIVE", "NEGATIVE", "UNSUBSCRIBE", "BOUNCE", "OUT_OF_OFFICE", "NEUTRAL"}


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
            return settings.get_str("llm.model_name", "llama3.1:8b")
        return "llama3.1:8b"

    def classify_reply(self, email_body: str) -> str:
        """Classifies inbound email body into intent category.

        Returns:
            One of POSITIVE, NEGATIVE, UNSUBSCRIBE, BOUNCE, OUT_OF_OFFICE, NEUTRAL.
        """
        if not email_body or not email_body.strip():
            return "NEUTRAL"

        text_lower = email_body.lower()

        # Deterministic regex shortcuts for obvious cases
        if any(kw in text_lower for kw in ["unsubscribe", "stop emailing", "remove me", "take me off"]):
            return "UNSUBSCRIBE"
        if any(kw in text_lower for kw in ["out of office", "auto-reply", "automatic reply", "on vacation"]):
            return "OUT_OF_OFFICE"
        if any(kw in text_lower for kw in ["undeliverable", "mail delivery failed", "address not found"]):
            return "BOUNCE"

        # LLM Classification
        prompt = (
            f"Classify the following email reply from a prospect into EXACTLY ONE label:\n"
            f"POSITIVE, NEGATIVE, UNSUBSCRIBE, BOUNCE, OUT_OF_OFFICE, NEUTRAL.\n\n"
            f"Email body: \"{email_body[:1000]}\"\n\n"
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
        negative_keywords = ["not interested", "no thanks", "dont contact", "don't contact", "remove", "busy"]
        positive_keywords = ["interested", "call", "demo", "pricing", "quote", "meeting", "yes", "sure", "sounds good"]

        if any(kw in text_lower for kw in negative_keywords):
            return "NEGATIVE"
        if any(kw in text_lower for kw in positive_keywords):
            return "POSITIVE"

        return "NEUTRAL"
