import re
from typing import Dict, Any, List


class EmailQualityEngine:
    """Deterministic Quality Scoring Engine.

    Evaluates cold email copy against criteria to maximize reply rates,
    minimize spam-filter flags, and prevent AI-style copy patterns.
    """

    SPAM_KEYWORDS = {
        "free",
        "guarantee",
        "risk-free",
        "risk free",
        "buy",
        "investment",
        "pricing",
        "revenue",
        "leads",
        "grow",
        "sales",
    }

    AI_JARGON_PHRASES = {
        "hope this email finds you well",
        "hope you are doing well",
        "hope you are well",
        "in today's digital landscape",
        "digital age",
        "streamline",
        "leverage",
        "empower",
        "elevate",
        "seamless",
        "orchestrate",
        "look no further",
    }

    @classmethod
    def score_draft(cls, body: str) -> Dict[str, Any]:
        """Calculates a numerical quality score and generates suggestions for improvement.

        Returns:
            Dictionary containing quality_score (int), passed (bool), and issues (List[str]).
        """
        issues: List[str] = []
        # Separate core email copy from compliance footer
        core_body = (body or "").split("\n\n---")[0].strip()
        core_lower = core_body.lower()
        words = core_lower.split()
        word_count = len(words)

        # 1. Length Check
        if word_count > 90:
            issues.append(f"Email body is too long ({word_count} words). Keep under 80 words.")

        # 2. Spam Word Check (word-boundary match so e.g. "buy" doesn't flag "buyers")
        detected_spam = [w for w in cls.SPAM_KEYWORDS if re.search(rf"\b{re.escape(w)}\b", core_lower)]
        if detected_spam:
            issues.append(f"Spam indicators detected: {detected_spam}. Avoid commercial sales language.")

        # 3. AI Cliché Check
        detected_jargon = [phrase for phrase in cls.AI_JARGON_PHRASES if phrase in core_lower]
        if detected_jargon:
            issues.append(f"AI boilerplate phrases detected: {detected_jargon}. Use a natural human voice.")

        # 4. Link & Image Check (Banned in initial outreach for deliverability safety)
        if "http://" in core_lower or "https://" in core_lower or "www." in core_lower:
            issues.append("Contains link or URL in body text. Banned in initial emails to maximize inbox delivery.")

        if "<img>" in core_lower or "src=" in core_lower:
            issues.append("Contains tracking pixel or image references, which trigger spam filters.")

        score = max(0, 100 - (len(issues) * 20))
        return {
            "quality_score": score,
            "passed": score >= 80,
            "issues": issues,
        }
