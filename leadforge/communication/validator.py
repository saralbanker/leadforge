"""Communication Quality & Compliance Safety Validator."""

import re
from typing import List
from leadforge.utils import get_logger

logger = get_logger()

_SPAM_TRIGGER_PATTERNS = [
    re.compile(r"\b(100%\s+free|guaranteed\s+money|earn\s+\$\$\$|act\bnow|click\s+here\s+now)\b", re.IGNORECASE)
]


class CommunicationQualityValidator:
    """Audits draft emails for compliance footers, spam triggers, and safety."""

    def validate_email_content(
        self, subject: str, body_text: str, recipient_email: str
    ) -> tuple[bool, List[str]]:
        """Audits subject, body, and recipient for compliance and quality safety.

        Returns:
            Tuple of (is_valid: bool, list_of_validation_issues: List[str])
        """
        issues: List[str] = []

        # 1. Non-empty check
        if not subject or not subject.strip():
            issues.append("Subject line cannot be empty.")
        if not body_text or not body_text.strip():
            issues.append("Email body text cannot be empty.")

        # 2. Recipient format check
        if not recipient_email or "@" not in recipient_email:
            issues.append(f"Invalid recipient email format: '{recipient_email}'.")

        # 3. Spam trigger phrase scan
        combined_text = f"{subject} {body_text}"
        for pattern in _SPAM_TRIGGER_PATTERNS:
            if pattern.search(combined_text):
                issues.append("Email text contains prohibited spam trigger phrase.")
                break

        # 4. Length limits
        if len(subject) > 150:
            issues.append("Subject line exceeds maximum length of 150 characters.")

        return (len(issues) == 0), issues
