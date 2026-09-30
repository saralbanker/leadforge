"""Company name cleaning utilities for LeadForge outreach.

NOTE: The cleaning rules and regexes in this file MUST be kept in sync with
leadforge.whatsapp_auto.foundation.templates.clean_company_name.
"""

import re
from typing import Optional


def clean_company_name(name: Optional[str]) -> str:
    """Cleans legal suffixes and Google Maps SEO tags from company name.

    NOTE: Must be kept in sync with whatsapp_auto.foundation.templates.clean_company_name.
    """
    if not name:
        return "your company"
    cleaned = str(name).strip()
    # Strip parenthetical group tags like '( Bhimani Group )' or '(Knife Edge Gate Valve...)'
    cleaned = re.sub(r"\s*\([^)]*\)", "", cleaned).strip()
    # Strip SEO dash tags like ' - Industrial equipment supplier in Ahmedabad'
    if " - " in cleaned:
        cleaned = cleaned.split(" - ")[0].strip()
    # Strip pipe separators (with or without surrounding spaces) like 'S.S. FLEXIBLE PIPE | SS TEFLON PIPE'
    if "|" in cleaned:
        cleaned = re.split(r"\s*\|\s*", cleaned)[0].strip()
    # If multiple slashes/partners exist, take the primary first brand
    if "/" in cleaned:
        cleaned = cleaned.split("/")[0].strip()
    # Remove trailing corporate suffixes (with optional trailing periods/commas)
    cleaned = re.sub(
        r"(?i)\s+(pvt\.?\s*ltd\.?|private\s+limited\.?|llp\.?|limited\.?|ltd\.?|works|corporation|inc\.?)[\s.]*$",
        "",
        cleaned,
    ).strip()
    # Strip trailing punctuation
    cleaned = re.sub(r"[.,\-\s]+$", "", cleaned).strip()
    return cleaned if cleaned else str(name).strip()


def shorten_company_name(name: Optional[str], max_chars: int = 22) -> str:
    """Shortens a business name cleanly for space-constrained contexts like subject lines.

    Distinct from clean_company_name() which removes legal entity suffixes (Pvt Ltd)
    and SEO separators ( - , | , / ).
    shorten_company_name() takes an already-cleaned name and:
    1. Trims unseparated trailing category/SEO noise if present.
    2. Strips generic corporate descriptors ('Industries', 'Technologies', 'Electronics',
       'Products', 'Enterprises', 'Equipment', 'Engineering', 'Wholesalers', 'Cylinders')
       when length exceeds max_chars.
    3. Truncates cleanly at word boundaries so words are never cut in half.
    """
    cleaned = clean_company_name(name)
    if len(cleaned) <= max_chars:
        return cleaned

    # 1. Strip unseparated category/SEO noise
    cleaned = re.sub(
        r"(?i)\s+(sheet metal parts manufacturer|agarbatti and pujapa wholesaler|engineering plastic manufacturer|tea manufacturer|tea wholesale|hdpe manufacture.*|ldpe trader.*)[\s.]*$",
        "",
        cleaned,
    ).strip()
    if len(cleaned) <= max_chars:
        return cleaned

    # 2. Strip common trailing corporate descriptors when name is long
    words = cleaned.split()
    trailing_descriptors = {
        "industries", "technologies", "electronics", "products", "corporation",
        "enterprises", "equipment", "engineering", "wholesaler", "wholesalers",
        "manufacturer", "manufacturers", "supplier", "suppliers", "cylinders",
        "co", "company"
    }
    while len(words) > 2 and words[-1].lower().strip(".,-&") in trailing_descriptors:
        words = words[:-1]
        cand = " ".join(words).strip(".,-& ")
        if len(cand) <= max_chars:
            return cand

    # 3. Truncate at word boundary up to max_chars
    res = []
    curr_len = 0
    for w in words:
        addition = len(w) if not res else len(w) + 1
        if curr_len + addition <= max_chars:
            res.append(w)
            curr_len += addition
        else:
            break
    if res:
        return " ".join(res).strip(".,-& ")
    return cleaned[:max_chars].strip()
