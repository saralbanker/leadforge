import re
from typing import Dict, Any
from leadforge.utils import clean_text

# Indian PIN code: exactly 6 digits, first digit 1–9, standing alone in the text.
_POSTAL_CODE_RE = re.compile(r"\b([1-9]\d{5})\b")


def extract_postal_code(address: str) -> str:
    """Extract the postal (PIN) code from an address string.

    Uses the last standalone 6-digit group — Indian addresses place the PIN at
    the end. Returns "" when no PIN is present.
    """
    if not address:
        return ""
    matches = _POSTAL_CODE_RE.findall(address)
    return matches[-1] if matches else ""


def parse_business_details(
    name: str,
    phone_data: str,
    website: str,
    address: str,
    category: str,
    source_url: str,
    city: str = "",
) -> Dict[str, Any]:
    """
    Cleans, structures, and returns parsed business details.
    """
    # Clean phone number (remove "phone:tel:" prefix and format whitespace)
    phone_cleaned = ""
    if phone_data:
        phone_cleaned = phone_data.replace("phone:tel:", "").strip()
        # Normalise layout
        phone_cleaned = "".join(phone_cleaned.split())

    # Clean address
    address_cleaned = ""
    if address:
        address_cleaned = address.replace("Address: ", "").strip()
        address_cleaned = clean_text(address_cleaned)

    # Deduce area from address
    area_deduced = ""
    if address_cleaned:
        # Common format: "Street, Locality/Area, City, State PostalCode"
        parts = [p.strip() for p in address_cleaned.split(",") if p.strip()]
        if len(parts) > 1:
            # Look for the target city in any part, then take the part before it as the area.
            city_lower = city.strip().lower() if city else ""
            city_idx = -1
            if city_lower:
                for idx, part in enumerate(parts):
                    if city_lower in part.lower():
                        city_idx = idx
                        break

            if city_idx > 0:
                area_deduced = parts[city_idx - 1]
            else:
                # Fallback: second-to-last component is usually the area/locality
                area_deduced = parts[-2] if len(parts) >= 2 else parts[0]

    # Normalize website url (ensure no Google redirection headers)
    website_cleaned = ""
    if website:
        website_cleaned = website.strip()
        if "google.com/url" in website_cleaned:
            # Try to extract actual website from google redirection parameter
            from urllib.parse import urlparse, parse_qs

            parsed = urlparse(website_cleaned)
            q_params = parse_qs(parsed.query)
            if "q" in q_params:
                website_cleaned = q_params["q"][0]
            elif "url" in q_params:
                website_cleaned = q_params["url"][0]

    return {
        "name": clean_text(name),
        "category": category,
        "phone": phone_cleaned,
        "website": website_cleaned,
        "address": address_cleaned,
        "area": clean_text(area_deduced),
        "postal_code": extract_postal_code(address_cleaned),
        "source_url": source_url,
    }
