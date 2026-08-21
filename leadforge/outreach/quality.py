import difflib
import re
from typing import Dict, Any, List, Optional, Sequence


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

    # Two hooks sharing this much of their wording are the same sentence with
    # the nouns swapped. Measured against real output: distinct hooks land
    # around 0.35-0.55, clones of one template land above 0.75.
    SIMILARITY_LIMIT = 0.62

    @staticmethod
    def _opening_line(body: str) -> str:
        """The observation hook — the only part that is meant to differ per lead."""
        core = (body or "").split("\n\n---")[0].strip()
        first = core.split("\n", 1)[0].strip()
        return first or core

    @classmethod
    def _skeleton(cls, line: str) -> str:
        """Strips the swappable specifics so the sentence shape is what is compared."""
        text = (line or "").lower()
        text = re.sub(r"[^a-z\s]", " ", text)
        return " ".join(text.split())

    @classmethod
    def find_similar(
        cls, body: str, previous_bodies: Sequence[str], limit: Optional[float] = None
    ) -> Optional[tuple]:
        """Returns (ratio, offending_line) when this hook echoes an earlier one."""
        threshold = cls.SIMILARITY_LIMIT if limit is None else limit
        line = cls._skeleton(cls._opening_line(body))
        if not line:
            return None

        worst = None
        for prev in previous_bodies:
            prev_line = cls._skeleton(cls._opening_line(prev))
            if not prev_line:
                continue
            ratio = max(
                difflib.SequenceMatcher(None, line, prev_line).ratio(),
                # The business name legitimately differs and can dominate the
                # comparison when lengths diverge. The tail is where a reused
                # template shows up, so score that separately.
                difflib.SequenceMatcher(None, cls._tail(line), cls._tail(prev_line)).ratio(),
            )
            if ratio >= threshold and (worst is None or ratio > worst[0]):
                worst = (ratio, cls._opening_line(prev))
        return worst

    @staticmethod
    def _tail(skeleton: str, keep: int = 8) -> str:
        """The closing words of the sentence, where reused phrasing concentrates."""
        words = skeleton.split()
        return " ".join(words[-keep:]) if len(words) > keep else skeleton

    @classmethod
    def score_draft(cls, body: str, previous_bodies: Optional[Sequence[str]] = None) -> Dict[str, Any]:
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

        # 5. Repetition check — a batch of near-identical openings reads as bulk
        #    mail no matter how clean each one is in isolation.
        penalty_units = len(issues)
        if previous_bodies:
            match = cls.find_similar(body, previous_bodies)
            if match:
                ratio, prev_line = match
                issues.append(
                    f"Opening line is {int(ratio * 100)}% identical to a recent draft "
                    f'("{prev_line[:70]}"). Each lead needs its own observation.'
                )
                # Repetition is the failure that scales, so it costs more.
                penalty_units += 2

        score = max(0, 100 - (penalty_units * 20))
        return {
            "quality_score": score,
            "passed": score >= 80,
            "issues": issues,
        }
