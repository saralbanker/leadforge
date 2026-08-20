"""Local LLM Copywriting & Reply Generation Engine."""

import json
import re
import requests
from typing import Dict, Any, Optional
from leadforge.config import OLLAMA_API_URL
from leadforge.utils import get_logger

logger = get_logger()


def sanitize_input_text(text: str) -> str:
    """Sanitizes text extracted from websites/emails to prevent prompt injection."""
    if not text:
        return ""
    text = text[:1500]
    text = re.sub(r"(?i)</?system.*?>", "[tag_removed]", text)
    text = re.sub(r"\[/?INST\]", "[tag_removed]", text)
    text = re.sub(r"<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>", "[token_removed]", text)

    injection_patterns = [
        r"(?i)\bignore\s+(?:all\s+|the\s+)?(?:previous|instructions|rules)\b",
        r"(?i)\bsystem\s+prompt\b",
        r"(?i)\bforget\s+(?:all\s+|the\s+)?(?:previous|instructions|rules)\b",
        r"(?i)\byou\s+must\s+output\b",
        r"(?i)\boverride\s+rules\b",
    ]
    for pattern in injection_patterns:
        text = re.sub(pattern, "[removed]", text)

    return text.replace("{", "[").replace("}", "]").replace("<", "&lt;").replace(">", "&gt;").strip()


class LocalLLMEmailWriter:
    """Generates personalized outbound copy using local Ollama (Llama 3.1 8B)."""

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

    @property
    def sender_name(self) -> str:
        settings = self._get_settings()
        if settings:
            return settings.get_str("smtp.from_name", "Orvion")
        return "Orvion"

    def generate_outbound_draft(self, context: Dict[str, Any]) -> tuple[str, str]:
        """Generates subject and email body for an initial outbound outreach.

        Returns:
            Tuple of (subject, body_text)
        """
        biz_name = context.get("name", "there")
        city = context.get("city", "your city")
        rating = context.get("rating", 0.0)
        reviews = context.get("review_count", 0)
        from_name = self.sender_name

        fallback_subject = f"Quick question regarding {biz_name}"
        fallback_body = (
            f"Hi {biz_name} team,\n\n"
            f"I was taking a look at local businesses in {city} and noticed your profile has a {rating}-star rating with {reviews} reviews.\n\n"
            f"We help local companies improve their direct online customer flow. Would you be open to a brief 5-minute chat this week?\n\n"
            f"Best regards,\n{from_name}"
        )

        prompt = (
            f"Write a friendly 3-sentence B2B outreach email for a business named '{biz_name}' in '{city}'.\n"
            f"Details: Rating {rating}, Reviews {reviews}.\n"
            f"Output JSON format: {{\"subject\": \"...\", \"body\": \"...\"}}"
        )

        settings = self._get_settings()
        temp = settings.get_float("llm.temperature", 0.2) if settings else 0.2
        max_toks = settings.get_int("llm.max_tokens", 150) if settings else 150

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": "You are a professional B2B outreach assistant. Output ONLY JSON.",
            "format": "json",
            "stream": False,
            "options": {"temperature": temp, "num_predict": max_toks},
        }

        try:
            resp = requests.post(f"{self.api_url}/api/generate", json=payload, timeout=15)
            if resp.status_code == 200:
                raw = resp.json().get("response", "").strip()
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    subject = parsed.get("subject", "").strip() or fallback_subject
                    body = parsed.get("body", "").strip() or fallback_body
                    return subject, body
        except Exception as e:
            logger.warning(f"[LocalLLMEmailWriter] Ollama execution failed: {e}. Using fallback copy.")

        return fallback_subject, fallback_body

    def generate_reply_draft(self, context: Dict[str, Any], inbound_body: str) -> tuple[str, str]:
        """Generates a reply draft to an incoming email from a prospect.

        Returns:
            Tuple of (subject, body_text)
        """
        biz_name = context.get("name", "there")
        sanitized_inbound = sanitize_input_text(inbound_body)
        from_name = self.sender_name

        fallback_subject = f"Re: Communication with {biz_name}"
        fallback_body = (
            f"Hi {biz_name} team,\n\n"
            f"Thank you for getting back to us. I'd be happy to share more details about how we can support your growth.\n\n"
            f"When would be a convenient time for a short phone call?\n\n"
            f"Best regards,\n{from_name}"
        )

        prompt = (
            f"Prospect email from '{biz_name}': \"{sanitized_inbound}\"\n"
            f"Write a brief, professional reply answering their question.\n"
            f"Output JSON format: {{\"subject\": \"Re: ...\", \"body\": \"...\"}}"
        )

        settings = self._get_settings()
        temp = settings.get_float("llm.temperature", 0.2) if settings else 0.2
        max_toks = settings.get_int("llm.max_tokens", 150) if settings else 150

        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "system": "You are a professional B2B customer support assistant. Output ONLY JSON.",
            "format": "json",
            "stream": False,
            "options": {"temperature": temp, "num_predict": max_toks},
        }

        try:
            resp = requests.post(f"{self.api_url}/api/generate", json=payload, timeout=15)
            if resp.status_code == 200:
                raw = resp.json().get("response", "").strip()
                match = re.search(r"\{.*\}", raw, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    subject = parsed.get("subject", "").strip() or fallback_subject
                    body = parsed.get("body", "").strip() or fallback_body
                    return subject, body
        except Exception as e:
            logger.warning(f"[LocalLLMEmailWriter] Ollama reply generation failed: {e}. Using fallback copy.")

        return fallback_subject, fallback_body
