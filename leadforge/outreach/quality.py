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
        "digital footprint",
        "online presence",
        "streamline",
        "leverage",
        "optimize",
        "solutions",
        "empower",
        "elevate",
        "seamless",
        "orchestrate",
        "look no further",
    }

    FILLER_PHRASES = {
        "in various locations",
        "in multiple locations",
        "in different locations",
        "in various areas",
        "in various places",
    }

    # Opening hook similarity limit: Two opening hooks sharing this much of
    # their wording are the same sentence with the nouns swapped. Measured against
    # real output: distinct hooks land around 0.35-0.55, clones of one template
    # land above 0.75.
    HOOK_SIMILARITY_LIMIT = 0.62
    SIMILARITY_LIMIT = 0.62  # Backward compatibility alias

    # Whole-body similarity limit: When comparing core email bodies (excluding compliance
    # footers), two drafts sharing both the middle value proposition and the closing question
    # reach ~0.75-0.90 similarity (even with distinct observation hooks and city/name interpolation).
    # Composed drafts sharing only one slot (e.g. middle OR closing) land at ~0.40-0.60, and
    # fully distinct combinations land below 0.35.
    # Setting threshold at 0.70 cleanly flags structural collisions while allowing valid slot combinations.
    BODY_SIMILARITY_LIMIT = 0.70

    @classmethod
    def detect_filler(cls, text: str) -> Optional[str]:
        """Detects meaningless filler phrases in observation hooks."""
        lower = text.lower()
        for filler in cls.FILLER_PHRASES:
            if filler in lower:
                return filler
        # Check for "has a website" / "have a website" as substantive claim (not negated)
        if re.search(r"(?<!\bno\s)(?<!\bwithout\s)\bhas a web\s*site\b", lower):
            return "has a website"
        if re.search(r"(?<!\bnot\s)(?<!\bno\s)(?<!\bwithout\s)(?<!\bn't\s)\bhave a web\s*site\b", lower):
            return "have a website"
        return None

    @classmethod
    def is_rating_recital(cls, text: str) -> bool:
        """Detects whether text is a bare recital of Google ratings or review counts."""
        return bool(re.search(
            r"\b("
            r"google rating|"
            r"google reviews?|"
            r"customer reviews?|"
            r"\d+(\.\d+)?\s*[- ]\s*stars?\b|"
            r"\d+(\.\d+)?\s*ratings?\b|"
            r"ratings? of \d|"
            r"\d+\s*reviews?\b|"
            r"star ratings?"
            r")\b",
            text,
            re.IGNORECASE,
        ))

    @classmethod
    def validate_hook(cls, hook: str, has_site_text: bool = False) -> tuple[bool, List[str]]:
        """Validates an observation hook against strict quality rules.

        A hook is INVALID if it:
        1. Is empty or blank.
        2. Exceeds 15 words.
        3. Contains any banned phrase (AI jargon or spam keywords).
        4. Contains filler like 'in various locations' or 'has a website'.
        5. Is a bare rating/review recital WHEN usable site text was supplied.
        6. Poses the sender as a customer or prospective buyer.

        Rule 6 exists because the model produced "K. Rudra Textiles has no clear
        product details on its website for potential buyers like me." The sender is
        selling web development, not shopping. Implying otherwise to win attention
        is deceptive, and deceptive content in commercial email is precisely what
        CAN-SPAM prohibits.

        Returns:
            (is_valid, issues)
        """
        issues: List[str] = []
        if not hook or not hook.strip():
            return False, ["Hook is empty"]

        cleaned_hook = hook.strip()
        words = cleaned_hook.split()
        word_count = len(words)
        hook_lower = cleaned_hook.lower()

        # 1. Length check: maximum 15 words
        if word_count > 15:
            issues.append(f"Hook exceeds 15 words ({word_count} words)")

        # 2. Banned vocabulary check
        banned_terms = cls.AI_JARGON_PHRASES | cls.SPAM_KEYWORDS
        detected_banned = [
            term for term in sorted(banned_terms)
            if re.search(rf"\b{re.escape(term)}\b", hook_lower)
        ]
        if detected_banned:
            issues.append(f"Contains banned phrase: {detected_banned}")

        # 3. Never pose as a customer. The sender is a vendor, not a buyer.
        posing = re.search(
            r"\b(?:buyers?|customers?|clients?|shoppers?)\s+like\s+(?:me|us)\b"
            r"|\blike\s+(?:me|us)\b"
            r"|\bas\s+a\s+(?:potential\s+)?(?:buyer|customer|client)\b"
            r"|\bi\s+(?:was\s+)?(?:looking|wanted|tried)\s+to\s+(?:buy|order|purchase)\b"
            r"|\bi\s+(?:am|'m)\s+(?:a\s+)?(?:potential\s+)?(?:buyer|customer|client)\b",
            hook_lower,  # already lowercased, so the patterns must be too
        )
        if posing:
            issues.append(f"Poses the sender as a customer: '{posing.group(0)}'")

        # 4. Filler check
        filler = cls.detect_filler(cleaned_hook)
        if filler:
            issues.append(f"Contains filler: '{filler}'")

        # 5. Rating recital check when usable site text was provided
        if has_site_text and cls.is_rating_recital(cleaned_hook):
            issues.append("Rating recital used when usable site text was supplied")

        return len(issues) == 0, issues

    @staticmethod
    def _core_body(body: str) -> str:
        """Extracts the core body copy excluding compliance footer."""
        return (body or "").split("\n\n---")[0].strip()

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

    @staticmethod
    def _tail(skeleton: str, keep: int = 8) -> str:
        """The closing words of the sentence, where reused phrasing concentrates."""
        words = skeleton.split()
        return " ".join(words[-keep:]) if len(words) > keep else skeleton

    @classmethod
    def find_similar_hook(
        cls, body: str, previous_bodies: Sequence[str], limit: Optional[float] = None
    ) -> Optional[tuple]:
        """Returns (ratio, offending_line) when this hook echoes an earlier one."""
        threshold = cls.HOOK_SIMILARITY_LIMIT if limit is None else limit
        line = cls._skeleton(cls._opening_line(body))
        if not line:
            return None

        worst = None
        for prev in previous_bodies:
            prev_line = cls._skeleton(cls._opening_line(prev))
            if not prev_line:
                continue
            ratio = max(
                difflib.SequenceMatcher(None, line, prev_line, autojunk=False).ratio(),
                # The business name legitimately differs and can dominate the
                # comparison when lengths diverge. The tail is where a reused
                # template shows up, so score that separately.
                difflib.SequenceMatcher(None, cls._tail(line), cls._tail(prev_line), autojunk=False).ratio(),
            )
            if ratio >= threshold and (worst is None or ratio > worst[0]):
                worst = (ratio, cls._opening_line(prev))
        return worst

    @classmethod
    def find_similar_body(
        cls, body: str, previous_bodies: Sequence[str], limit: Optional[float] = None
    ) -> Optional[tuple]:
        """Returns (ratio, offending_body) when this whole core body echoes an earlier one."""
        threshold = cls.BODY_SIMILARITY_LIMIT if limit is None else limit
        core = cls._skeleton(cls._core_body(body))
        if not core:
            return None

        words = core.split()
        worst = None
        for prev in previous_bodies:
            prev_core = cls._skeleton(cls._core_body(prev))
            if not prev_core:
                continue
            prev_words = prev_core.split()
            word_ratio = difflib.SequenceMatcher(None, words, prev_words, autojunk=False).ratio()
            char_ratio = difflib.SequenceMatcher(None, core, prev_core, autojunk=False).ratio()
            ratio = max(word_ratio, char_ratio)
            if ratio >= threshold and (worst is None or ratio > worst[0]):
                worst = (ratio, cls._core_body(prev))
        return worst

    @classmethod
    def find_similar(
        cls, body: str, previous_bodies: Sequence[str], limit: Optional[float] = None
    ) -> Optional[tuple]:
        """Returns (ratio, offending_text) when hook or whole body echoes an earlier draft."""
        hook_match = cls.find_similar_hook(body, previous_bodies, limit=limit)
        if hook_match:
            return hook_match
        body_match = cls.find_similar_body(body, previous_bodies, limit=limit)
        if body_match:
            return body_match
        return None

    @classmethod
    def score_draft(cls, body: str, previous_bodies: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """Calculates a numerical quality score and generates suggestions for improvement.

        Returns:
            Dictionary containing quality_score (int), passed (bool), and issues (List[str]).
        """
        issues: List[str] = []
        # Separate core email copy from compliance footer
        core_body = cls._core_body(body)
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

        # 5. Repetition check — a batch of near-identical openings or whole bodies
        #    reads as bulk mail no matter how clean each one is in isolation.
        penalty_units = len(issues)
        if previous_bodies:
            hook_match = cls.find_similar_hook(body, previous_bodies)
            body_match = cls.find_similar_body(body, previous_bodies)
            if hook_match:
                ratio, prev_line = hook_match
                issues.append(
                    f"Opening line is {int(ratio * 100)}% identical to a recent draft "
                    f'("{prev_line[:70]}"). Each lead needs its own observation.'
                )
                # Repetition is the failure that scales, so it costs more.
                penalty_units += 2
            if body_match and not hook_match:
                ratio, prev_body = body_match
                clean_prev = prev_body.replace("\n", " ").strip()[:70]
                issues.append(
                    f"Email body is {int(ratio * 100)}% identical to a recent draft "
                    f'("{clean_prev}..."). Body structure must be varied across the batch.'
                )
                penalty_units += 2

        score = max(0, 100 - (penalty_units * 20))
        return {
            "quality_score": score,
            "passed": score >= 80,
            "issues": issues,
        }
