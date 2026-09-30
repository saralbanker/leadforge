"""Pre-generation classification of scraped website content.

Determines whether scraped website text contains concrete, extractable product
or operational specifics versus thin, boilerplate, parked, error, or empty text.
Enables routing thin scrapes to honest fallbacks rather than forcing small models
to hallucinate specificity.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScrapedContentClassification:
    is_usable: bool
    classification: str  # USABLE, EMPTY, TOO_SHORT, BOILERPLATE_OR_ERROR, NO_WEBSITE
    sanitized_text: str
    char_count: int
    word_count: int
    rejection_reason: Optional[str] = None


# Heuristic patterns that indicate non-content / error / placeholder pages
BOILERPLATE_ERROR_PATTERNS = [
    (r"\b(home\s+loading|loading\.\.\.|please\s+wait)\b", "loading_placeholder"),
    (r"\b(under\s+construction|site\s+under\s+construction|maintenance\s+mode)\b", "under_construction"),
    (r"\b(domain\s+(?:is\s+)?(?:for\s+sale|available|parked)|buy\s+this\s+domain|parked\s+free|hugedomains)\b", "domain_parked"),
    (r"\b(404\s+not\s+found|403\s+forbidden|access\s+denied|page\s+not\s+found|error\s+404)\b", "http_error"),
    (r"\b(website\s+coming\s+soon|coming\s+soon)\b", "coming_soon"),
    (r"\b(enable\s+javascript\s+to\s+run\s+this\s+app|you\s+need\s+to\s+enable\s+javascript|javascript\s+is\s+disabled)\b", "js_required"),
    (r"\b(apache2?\s+(?:ubuntu\s+)?default\s+page|welcome\s+to\s+nginx|iis\s+windows\s+server)\b", "server_default"),
    (r"\b(no\s+website\s+content\s+available)\b", "fallback_placeholder"),
]

# Minimum content thresholds for reliable LLM extraction
MIN_USABLE_CHARS = 20
MIN_USABLE_WORDS = 3


def sanitize_scraped_text(text: str) -> str:
    """Sanitizes text extracted from websites to prevent prompt injection and formatting breaks."""
    if not text:
        return ""

    # 1. Truncate to a sensible limit
    text = text[:2500]

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

    # 4. Remove braces to prevent template injection escaping
    text = text.replace("{", "[").replace("}", "]").replace("<", "&lt;").replace(">", "&gt;")

    # 5. Normalize whitespace
    text = " ".join(text.split())

    return text.strip()


def classify_scraped_content(text: Optional[str]) -> ScrapedContentClassification:
    """Evaluates scraped website text for usability before LLM inference.

    Args:
        text: Raw or pre-sanitized text extracted from the business website.

    Returns:
        ScrapedContentClassification indicating whether the text is usable for
        grounded extraction, along with sanitized text and diagnostic metrics.
    """
    if text is None or not text.strip():
        return ScrapedContentClassification(
            is_usable=False,
            classification="EMPTY",
            sanitized_text="",
            char_count=0,
            word_count=0,
            rejection_reason="Text is empty or None",
        )

    sanitized = sanitize_scraped_text(text)
    if not sanitized:
        return ScrapedContentClassification(
            is_usable=False,
            classification="EMPTY",
            sanitized_text="",
            char_count=0,
            word_count=0,
            rejection_reason="Text is empty after sanitization",
        )

    char_count = len(sanitized)
    words = sanitized.split()
    word_count = len(words)
    lower_text = sanitized.lower()

    # Check for boilerplate, parked, error, or loading text
    for pattern, reason in BOILERPLATE_ERROR_PATTERNS:
        if re.search(pattern, lower_text):
            return ScrapedContentClassification(
                is_usable=False,
                classification="BOILERPLATE_OR_ERROR",
                sanitized_text=sanitized,
                char_count=char_count,
                word_count=word_count,
                rejection_reason=f"Matched non-content pattern: {reason}",
            )

    # Check length thresholds
    if char_count < MIN_USABLE_CHARS or word_count < MIN_USABLE_WORDS:
        return ScrapedContentClassification(
            is_usable=False,
            classification="TOO_SHORT",
            sanitized_text=sanitized,
            char_count=char_count,
            word_count=word_count,
            rejection_reason=f"Content too short ({char_count} chars, {word_count} words; min: {MIN_USABLE_CHARS} chars, {MIN_USABLE_WORDS} words)",
        )

    return ScrapedContentClassification(
        is_usable=True,
        classification="USABLE",
        sanitized_text=sanitized,
        char_count=char_count,
        word_count=word_count,
        rejection_reason=None,
    )
