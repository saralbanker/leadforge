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
    MAX_SUBJECT_LENGTH = 50
    MAX_BODY_WORDS = 65
    MIN_BODY_WORDS = 25

    UNIVERSAL_DIAGNOSIS_PHRASES = {
        "lose orders",
        "losing orders",
        "loses orders",
        "lost orders",
        "lose institutional clients",
        "buried on whatsapp",
        "buried in whatsapp",
        "buried in email",
        "buried on email",
        "buried before staff",
        "delayed before staff",
        "forgotten before staff",
        "orders slip through",
        "order slips through",
        "deals slip away",
        "deal slips away",
        "clients slip through",
        "client slips through",
        "struggle to stay on top",
        "struggles to stay on top",
        "you lose",
        "you're losing",
        "you are losing",
        "you miss",
        "you're missing",
        "you are missing",
        "slow to respond",
        "delayed response",
        "missed inquiries",
        "lose track of",
        "losing track of",
        "struggle to keep track",
        "inquiries slip through",
        "inquiries fall through",
    }

    # No implied clients or social proof: the sender has no case studies for
    # this pitch, so any claim of prior results or comparable customers is
    # fabricated. Checked separately from AI_JARGON/SPAM so the reported
    # issue names the actual problem (see P0-3 truthfulness rules).
    SOCIAL_PROOF_PHRASES = {
        "other manufacturers",
        "other manufacturing",
        "companies like yours",
        "clients like you",
        "businesses like yours",
        "manufacturers like you",
        "manufacturers we work with",
        "manufacturers we've worked with",
        "many manufacturers",
        "many companies",
        "many businesses",
        "we helped",
        "we've helped",
        "helped other",
        "our clients",
        "our customers",
        "case study",
        "case studies",
        "success stories",
        "proven results",
    }

    # A greeting and a signed sign-off are required on every outbound body -
    # sent drafts on 2026-09-24 shipped with neither (see P0-3).
    GREETING_PATTERN = re.compile(r"^\s*hi\s+.+,\s*$", re.IGNORECASE)
    SENDER_SIGNOFF = "saral banker, orvion"

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

    @classmethod
    def validate_subject(
        cls,
        subject: str,
        max_chars: int = MAX_SUBJECT_LENGTH,
        business_name: Optional[str] = None,
    ) -> tuple[bool, List[str]]:
        """Validates an email subject line against length, banned terms, and formatting rules.

        A subject is INVALID if it:
        1. Is empty or blank.
        2. Exceeds max_chars (default 50 chars).
        3. Contains any banned phrase (AI jargon or spam keywords).

        Returns:
            (is_valid, issues)
        """
        issues: List[str] = []
        if not subject or not subject.strip():
            return False, ["Subject is empty"]

        cleaned = subject.strip()
        if len(cleaned) > max_chars:
            issues.append(f"Subject exceeds {max_chars} characters ({len(cleaned)} chars)")

        banned_terms = cls.AI_JARGON_PHRASES | cls.SPAM_KEYWORDS
        subject_lower = cleaned.lower()

        # If business name contains a term like "sales" (e.g. "Sanju Sales"),
        # mask out the company name so legitimate company names are not flagged as spam.
        check_text = subject_lower
        if business_name:
            check_text = re.sub(rf"\b{re.escape(business_name.lower())}\b", "", check_text)
            from leadforge.outreach.cleaning import clean_company_name, shorten_company_name
            c_name = clean_company_name(business_name).lower()
            s_name = shorten_company_name(business_name).lower()
            check_text = re.sub(rf"\b{re.escape(c_name)}\b", "", check_text)
            check_text = re.sub(rf"\b{re.escape(s_name)}\b", "", check_text)

        detected_banned = [
            term for term in sorted(banned_terms)
            if re.search(rf"\b{re.escape(term)}\b", check_text)
        ]
        if detected_banned:
            issues.append(f"Contains banned phrase: {detected_banned}")

        return len(issues) == 0, issues

    @classmethod
    def validate_bridge(
        cls,
        bridge: str,
        is_usable: bool = True,
        has_website: bool = True,
        observation_hook: Optional[str] = None,
        city: Optional[str] = None,
    ) -> tuple[bool, List[str]]:
        """Validates a contact bridge sentence answering 'why I am writing to you today'.

        A bridge is INVALID if it:
        1. Is empty or blank.
        2. Is outside word bounds (under 5 words or over 18 words).
        3. Fabricates prior contact (e.g. 'following up', 'we spoke', 'as discussed').
        4. Fabricates offline interactions (e.g. 'called your office', 'visited your plant').
        5. Poses the sender as a customer/buyer.
        6. Claims website/catalog browsing when no usable website exists.
        7. Contains banned vocabulary (AI jargon or spam keywords).
        8. Contains universal diagnosis language (e.g. 'lose orders').
        9. Duplicates city mentions if already stated in observation_hook.
        10. Contains exclamation marks or em-dashes.

        Returns:
            (is_valid, issues)
        """
        issues: List[str] = []
        if not bridge or not bridge.strip():
            return False, ["Bridge is empty"]

        cleaned = bridge.strip()
        words = cleaned.split()
        word_count = len(words)
        lower = cleaned.lower()

        # 1. Length bounds: 5 to 18 words
        if word_count < 5:
            issues.append(f"Bridge is too short ({word_count} words)")
        elif word_count > 18:
            issues.append(f"Bridge exceeds 18 words ({word_count} words)")

        # 2. Fabricated prior contact
        prior_contact = re.search(
            r"\b(?:following\s+up|follow-?up|we\s+spoke|as\s+discussed|our\s+conversation|you\s+requested|your\s+inquiry|per\s+our\s+call|per\s+our\s+chat)\b",
            lower,
        )
        if prior_contact:
            issues.append(f"Fabricates prior contact: '{prior_contact.group(0)}'")

        # 3. Fabricated offline interactions
        offline_contact = re.search(
            r"\b(?:called\s+your\s+office|visited\s+your\s+(?:plant|shop|office|factory)|spoke\s+with\s+your\s+team|stopped\s+by\s+your\s+shop)\b",
            lower,
        )
        if offline_contact:
            issues.append(f"Fabricates offline interaction: '{offline_contact.group(0)}'")

        # 4. Posing as customer
        posing = re.search(
            r"\b(?:buyers?|customers?|clients?|shoppers?)\s+like\s+(?:me|us)\b"
            r"|\blike\s+(?:me|us)\b"
            r"|\bas\s+a\s+(?:potential\s+)?(?:buyer|customer|client)\b"
            r"|\bi\s+(?:was\s+)?(?:looking|wanted|tried)\s+to\s+(?:buy|order|purchase)\b"
            r"|\bi\s+(?:am|'m)\s+(?:a\s+)?(?:potential\s+)?(?:buyer|customer|client)\b",
            lower,
        )
        if posing:
            issues.append(f"Poses the sender as a customer: '{posing.group(0)}'")

        # 5. Honest website claim
        if not is_usable or not has_website:
            fake_web = re.search(
                r"\b(?:on\s+your\s+website|your\s+website|browsing\s+your\s+site|saw\s+your\s+website|online\s+catalog|site\s+catalog)\b",
                lower,
            )
            if fake_web:
                issues.append(f"Fabricates website browsing when no usable website exists: '{fake_web.group(0)}'")

        # 6. Banned vocabulary
        banned_terms = cls.AI_JARGON_PHRASES | cls.SPAM_KEYWORDS
        detected_banned = [
            term for term in sorted(banned_terms)
            if re.search(rf"\b{re.escape(term)}\b", lower)
        ]
        if detected_banned:
            issues.append(f"Contains banned phrase in bridge: {detected_banned}")

        # 7. Universal diagnosis claims
        for diag in cls.UNIVERSAL_DIAGNOSIS_PHRASES:
            if diag in lower:
                issues.append(f"Contains unverified diagnosis claim in bridge: '{diag}'")

        # 8. City duplication with observation hook
        if city and str(city).strip() and observation_hook and str(observation_hook).strip():
            c_clean = str(city).strip().lower()
            if re.search(rf"\b{re.escape(c_clean)}\b", observation_hook.lower()) and re.search(rf"\b{re.escape(c_clean)}\b", lower):
                issues.append(f"Location duplication: '{city}' repeated in bridge")

        # 9. Punctuation and em-dash restrictions
        if "!" in cleaned:
            issues.append("Exclamation marks banned in bridge")
        if "—" in cleaned or "–" in cleaned:
            issues.append("Em-dashes banned in bridge")

        return len(issues) == 0, issues

    @classmethod
    def validate_body(
        cls,
        body: str,
        max_words: int = MAX_BODY_WORDS,
        city: Optional[str] = None,
        is_usable: bool = True,
        has_website: bool = True,
    ) -> tuple[bool, List[str]]:
        """Validates an email body against length ceiling, diagnosis claims, and spam/AI rules.

        A body is INVALID if it:
        1. Is empty or blank.
        2. Exceeds max_words (default 65 words for core body).
        3. Contains universal-claim diagnosis language (e.g. 'lose orders', 'buried on whatsapp').
        4. Contains banned vocabulary (AI jargon or spam keywords).
        5. Contains links, URLs, or image references in initial outreach.
        6. Poses the sender as a customer.
        7. Contains duplicate city mentions across opening paragraphs.

        Returns:
            (is_valid, issues)
        """
        issues: List[str] = []
        if not body or not body.strip():
            return False, ["Body is empty"]

        core = cls._core_body(body)
        core_lower = core.lower()
        words = core.split()
        word_count = len(words)
        paras = [p.strip() for p in core.split("\n\n") if p.strip()]

        # 1. Length check: maximum max_words
        if word_count > max_words:
            issues.append(f"Body exceeds {max_words} words ({word_count} words)")

        # 2. Universal-claim diagnosis language check
        detected_diagnosis = [
            phrase for phrase in sorted(cls.UNIVERSAL_DIAGNOSIS_PHRASES)
            if phrase in core_lower
        ]
        if detected_diagnosis:
            issues.append(f"Contains unverified diagnosis claim: {detected_diagnosis}")

        # 2b. Implied clients / social proof check - no case studies exist.
        detected_social_proof = [
            phrase for phrase in sorted(cls.SOCIAL_PROOF_PHRASES)
            if phrase in core_lower
        ]
        if detected_social_proof:
            issues.append(f"Contains implied social proof / client claim: {detected_social_proof}")

        # 2c. Repeated paragraph opener (e.g. "I noticed ... / I noticed ...") reads as templated.
        openers = [" ".join(p.lower().split()[:2]) for p in paras if len(p.split()) >= 2]
        repeated_openers = sorted({o for o in openers if openers.count(o) > 1})
        if repeated_openers:
            issues.append(f"Paragraphs repeat the same opener: {repeated_openers}")

        # 3. Banned vocabulary check in body copy (middle and closing)
        body_copy = " ".join(paras[1:]) if len(paras) >= 2 else core
        body_copy_lower = body_copy.lower()
        banned_terms = cls.AI_JARGON_PHRASES | cls.SPAM_KEYWORDS
        detected_banned = [
            term for term in sorted(banned_terms)
            if re.search(rf"\b{re.escape(term)}\b", body_copy_lower)
        ]
        if detected_banned:
            issues.append(f"Contains banned phrase: {detected_banned}")

        # 4. Links and images check
        if "http://" in core_lower or "https://" in core_lower or "www." in core_lower:
            issues.append("Contains link or URL in body text")
        if "<img>" in core_lower or "src=" in core_lower:
            issues.append("Contains tracking pixel or image references")

        # 5. Posing as a customer
        posing = re.search(
            r"\b(?:buyers?|customers?|clients?|shoppers?)\s+like\s+(?:me|us)\b"
            r"|\blike\s+(?:me|us)\b"
            r"|\bas\s+a\s+(?:potential\s+)?(?:buyer|customer|client)\b"
            r"|\bi\s+(?:was\s+)?(?:looking|wanted|tried)\s+to\s+(?:buy|order|purchase)\b"
            r"|\bi\s+(?:am|'m)\s+(?:a\s+)?(?:potential\s+)?(?:buyer|customer|client)\b",
            core_lower,
        )
        if posing:
            issues.append(f"Poses the sender as a customer: '{posing.group(0)}'")

        # 6. Location duplication check in opening paragraphs/sentences
        if city and str(city).strip():
            city_clean = str(city).strip().lower()
            paras = [p.strip() for p in core.split("\n\n") if p.strip()]
            if len(paras) >= 2:
                p1_lower = paras[0].lower()
                p2_lower = paras[1].lower()
                city_pat = rf"\b{re.escape(city_clean)}\b"
                if re.search(city_pat, p1_lower) and re.search(city_pat, p2_lower):
                    issues.append(f"Location duplication: '{city}' repeated in opening paragraphs")

        # 7. Bridge sentence validation in Paragraph 2
        if len(paras) >= 2:
            p2 = paras[1]
            first_sent = p2.split(". ")[0].strip()
            if not first_sent.endswith(".") and "." in p2:
                first_sent += "."
            b_valid, b_issues = cls.validate_bridge(
                bridge=first_sent,
                is_usable=is_usable,
                has_website=has_website,
                observation_hook=paras[0],
                city=city,
            )
            for bi in b_issues:
                if bi not in issues:
                    issues.append(bi)

        return len(issues) == 0, issues

    @staticmethod
    def _core_body(body: str) -> str:
        """Extracts the core pitch copy, excluding the greeting, sign-off, and
        compliance footer wrapper added by compose_full_body().

        Length budgets and hook/bridge paragraph checks apply to the
        personalized pitch only - the fixed greeting and sign-off lines are
        boilerplate the sender controls, not content being scored per lead.
        """
        text = (body or "").split("\n\n---")[0].strip()
        # Strip a leading greeting line, e.g. "Hi Acme team,\n\n..."
        text = re.sub(r"^\s*hi\s+[^\n]{0,80},\s*\n+", "", text, count=1, flags=re.IGNORECASE)
        # Strip a trailing sign-off block, e.g. "...\n\nBest,\nSaral Banker, Orvion"
        text = re.sub(
            r"\n+\s*(?:best|regards|thanks|thank you|sincerely)[,.]?\s*\n+\s*saral banker,?\s*orvion\.?\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip()

    @classmethod
    def validate_envelope(cls, body: str) -> tuple[bool, List[str]]:
        """Validates the fixed wrapper every sent email must carry.

        A body is INVALID if it is missing:
        1. A greeting line ('Hi <name/team>,') as the first line.
        2. A sign-off naming the sender ('Saral Banker, Orvion').
        3. The compliance footer (a '---' separator line).

        This is separate from validate_body() so the reason a draft is held
        back names the missing structural element, not a generic body issue.
        """
        issues: List[str] = []
        raw = body or ""
        if not raw.strip():
            return False, ["Body is empty"]

        first_line = raw.strip().split("\n", 1)[0].strip()
        if not cls.GREETING_PATTERN.match(first_line):
            issues.append("Missing greeting line (e.g. 'Hi <name/team>,') at the start of the email")

        if cls.SENDER_SIGNOFF not in raw.lower():
            issues.append(f"Missing sign-off with sender name '{cls.SENDER_SIGNOFF.title()}'")

        if "\n\n---" not in raw and not raw.rstrip().endswith("---"):
            issues.append("Missing compliance footer (postal address / opt-out)")

        return len(issues) == 0, issues

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
        if word_count > cls.MAX_BODY_WORDS:
            issues.append(f"Email body is too long ({word_count} words). Keep under {cls.MAX_BODY_WORDS} words.")

        # 2. Universal Diagnosis Check
        detected_diagnosis = [phrase for phrase in sorted(cls.UNIVERSAL_DIAGNOSIS_PHRASES) if phrase in core_lower]
        if detected_diagnosis:
            issues.append(f"Unverified diagnosis claims detected: {detected_diagnosis}. Avoid asserting operational failure as fact.")

        # 2b. Social proof / implied clients check
        detected_social_proof = [phrase for phrase in sorted(cls.SOCIAL_PROOF_PHRASES) if phrase in core_lower]
        if detected_social_proof:
            issues.append(f"Implied social proof detected: {detected_social_proof}. No case studies exist - never imply other clients or results.")

        # 3. Spam Word Check (word-boundary match so e.g. "buy" doesn't flag "buyers")
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
