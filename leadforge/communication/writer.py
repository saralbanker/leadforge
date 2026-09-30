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
            return settings.get_str("llm.model_name", "qwen2.5:3b")
        return "qwen2.5:3b"

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

    def generate_followup_draft(
        self,
        context: Dict[str, Any],
        step: int = 2,
        campaign_name: Optional[str] = None,
        first_subject: Optional[str] = None,
        first_body: Optional[str] = None,
        premise_verified: bool = True,
    ) -> tuple[str, str]:
        """Generates subject and email body for an automated follow-up step.

        Selects templates deterministically per business and per step from campaign_routing.yaml.
        Enforces lowercase plain-spoken tone, banned terms, shorter length, and closing question.

        Returns:
            Tuple of (subject, body_text)
        """
        from leadforge.outreach.cleaning import clean_company_name
        from leadforge.outreach.router import CampaignRouter
        router = CampaignRouter()

        biz_id = context.get("business_id") or context.get("id", "")
        biz_name = clean_company_name(context.get("name", "there"))
        city = context.get("city", "your city")
        area = context.get("area", "")

        matched_campaign = None
        if campaign_name:
            for camp in router.campaigns:
                if camp.get("name") == campaign_name:
                    matched_campaign = camp
                    break

        if not matched_campaign:
            # Fallback: route based on available context
            has_website = bool(context.get("website_domain"))
            category = context.get("category", "")
            matched_campaign = router.route_lead(
                category=category,
                has_website=has_website,
                ssl_valid=context.get("ssl_valid", True),
                audit_data=context,
            )

        if matched_campaign and "copy_template" in matched_campaign:
            copy_tmpl = matched_campaign["copy_template"]
            pv = premise_verified if premise_verified is not None else matched_campaign.get("premise_verified", True)
            subject_tmpl = router.select_followup_subject(copy_tmpl, step=step, business_id=biz_id, first_subject=first_subject)
            body_tmpl = router.select_followup_body(copy_tmpl, step=step, business_id=biz_id, premise_verified=pv)
        else:
            # Fallback when no campaign matched
            if first_subject:
                subject_tmpl = f"Re: {first_subject}"
            else:
                subject_tmpl = f"Follow-up: regarding {biz_name}"
            if step >= 3:
                body_tmpl = "if this is not a priority for {business_name} right now, no problem at all.\n\nshould i check back with you in a few months?"
            else:
                body_tmpl = "wanted to see if you had a moment to consider our note regarding {business_name}.\n\nwould you be open to a short 5-minute chat this week?"

        if first_subject:
            subject = subject_tmpl.replace("{business_name}", biz_name).replace("{city}", city).replace("{area}", area).replace("{first_subject}", first_subject).replace("{subject}", first_subject).strip()
        else:
            # When no previous subject is recorded on thread, format with clean Follow-up subject
            clean_tmpl = subject_tmpl.replace("{first_subject}", f"regarding {biz_name}").replace("{subject}", f"regarding {biz_name}")
            subject = clean_tmpl.replace("{business_name}", biz_name).replace("{city}", city).replace("{area}", area).strip()
            if not subject.lower().startswith("follow-up"):
                subject = f"Follow-up: {subject}"

        if subject.lower().startswith("follow-up") and not subject.startswith("Follow-up"):
            subject = "Follow-up" + subject[9:]

        core_body = body_tmpl.replace("{business_name}", biz_name).replace("{city}", city).replace("{area}", area).strip()

        settings = self._get_settings()
        if settings:
            from leadforge.outreach.generator import compose_full_body
            body = compose_full_body(core_body, biz_name, settings)
        else:
            body = f"Hi {biz_name} team,\n\n{core_body}\n\nBest,\nSaral Banker, Orvion"

        return subject, body

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
