"""WhatsApp Message Templates for Ahmedabad B2B Industrial Outreach.

Designed for solo operators:
- Zero "Hi team"
- Professional, respectful salutation ("Hello Sir,")
- Short, basic vocabulary, straight to the point
- Localized strictly to Ahmedabad industrial hubs (Vatva, Odhav, Kathwada, Changodar, Sanand)
"""

import re
from typing import Optional


def clean_company_name(name: str) -> str:
    """Cleans legal suffixes and Google Maps SEO tags from company name.

    NOTE: Must be kept in sync with leadforge.outreach.cleaning.clean_company_name.
    """
    if not name:
        return "your company"
    cleaned = name.strip()
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
        cleaned
    ).strip()
    # Strip trailing punctuation
    cleaned = re.sub(r"[.,\-\s]+$", "", cleaned).strip()
    return cleaned if cleaned else name.strip()


def shorten_company_name(name: Optional[str], max_chars: int = 22) -> str:
    """Shortens a business name cleanly for space-constrained contexts.

    NOTE: Must be kept in sync with leadforge.outreach.cleaning.shorten_company_name.
    """
    cleaned = clean_company_name(name)
    if len(cleaned) <= max_chars:
        return cleaned

    cleaned = re.sub(
        r"(?i)\s+(sheet metal parts manufacturer|agarbatti and pujapa wholesaler|engineering plastic manufacturer|tea manufacturer|tea wholesale|hdpe manufacture.*|ldpe trader.*)[\s.]*$",
        "",
        cleaned,
    ).strip()
    if len(cleaned) <= max_chars:
        return cleaned

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


def clean_product_name(product: Optional[str]) -> str:
    """Cleans product category strings (removes JSON brackets, quotes, trailing 'supplier/manufacturer')."""
    if not product:
        return "industrial equipment"
    p = str(product).strip()
    # Strip JSON brackets and quotes
    p = re.sub(r"[\[\]\"']", "", p)
    # If comma separated, take first
    if "," in p:
        p = p.split(",")[0].strip()
    p = p.lower().strip()
    # Remove redundant trailing words iteratively (e.g. 'supplier in ahmedabad')
    pattern = r"\s+(in\s+ahmedabad|supplier|manufacturer|dealer|wholesaler|exports?|solutions?)$"
    for _ in range(3):
        p_new = re.sub(pattern, "", p).strip()
        if p_new == p:
            break
        p = p_new
    # If standalone manufacturer/supplier without category context, fallback to descriptive category
    if p in ("manufacturer", "manufacturing", "supplier", "dealer", "wholesaler", "industrial equipment supplier", ""):
        return "industrial equipment"
    return p if p else "industrial equipment"


def render_template_a(
    company_name: str,
    products: Optional[str] = None,
    area: Optional[str] = None,
    hook: Optional[str] = None,
) -> str:
    """Template A (Primary): WhatsApp-to-Tally Order Entry Hook.

    Focuses on eliminating manual re-typing of repeat customer orders into Tally.
    Word count: ~55 words.
    """
    clean_name = clean_company_name(company_name)
    prod_str = clean_product_name(products)
    area_str = area.strip() if area else "Ahmedabad"

    opening = hook.strip() if hook and hook.strip() else (
        f"Hello Sir, noticed {clean_name} operates with {prod_str} in {area_str}."
    )
    return (
        f"{opening}\n\n"
        "When repeat orders come in on WhatsApp or phone, does your staff have to re-type those items into Tally by hand?\n\n"
        "We built a simple tool for Ahmedabad manufacturers that pushes WhatsApp orders directly into Tally without re-typing.\n\n"
        "Can I share a 30-second demo video here?\n\n"
        "Saral Banker\n"
        "Orvion, Ahmedabad"
    )


def render_template_b(
    company_name: str,
    products: Optional[str] = None,
    area: Optional[str] = None,
    hook: Optional[str] = None,
) -> str:
    """Template B: Dispatch Challan & Gate Pass Automation Hook.

    Focuses on shop-floor dispatch challans syncing with Tally.
    """
    clean_name = clean_company_name(company_name)
    prod_str = clean_product_name(products)
    area_str = area.strip() if area else "Ahmedabad"

    opening = hook.strip() if hook and hook.strip() else (
        f"Hello Sir, saw {clean_name}'s {prod_str} plant in {area_str}."
    )
    return (
        f"{opening}\n\n"
        "Quick question: do your factory supervisors still prepare dispatch challans and gate passes on paper before billing in Tally?\n\n"
        "We made a lightweight tool for Ahmedabad engineering plants that creates dispatch challans on mobile and syncs with Tally instantly.\n\n"
        "Worth sending a 30-second preview here?\n\n"
        "Saral Banker | Orvion, Ellisbridge"
    )


def render_template_c(
    company_name: str,
    products: Optional[str] = None,
    area: Optional[str] = None,
    hook: Optional[str] = None,
) -> str:
    """Template C: IndiaMART Buyer Inquiry Alert Hook.

    Focuses on preventing lost sales inquiries during shop-floor hours.
    """
    clean_name = clean_company_name(company_name)
    prod_str = clean_product_name(products)
    area_str = area.strip() if area else "Ahmedabad"

    opening = hook.strip() if hook and hook.strip() else (
        f"Hello Sir, saw {clean_name} listed for {prod_str} in {area_str}."
    )
    return (
        f"{opening}\n\n"
        "Do new buyer inquiries from IndiaMART or WhatsApp get delayed when your team is busy on the shop floor?\n\n"
        "We built a simple alert tool for local manufacturers that routes every buyer inquiry directly to your sales staff's WhatsApp within 10 seconds.\n\n"
        "Can I send a short 30-second clip showing how it works?\n\n"
        "Saral Banker | Orvion, Ahmedabad"
    )
