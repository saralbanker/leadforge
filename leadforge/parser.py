from typing import Dict, Any
from leadforge.utils import clean_text

def parse_business_details(
    name: str,
    phone_data: str,
    website: str,
    address: str,
    category: str,
    source_url: str
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
        # Expected format in India/Ahmedabad: "House No, Street Name, Area Name, Ahmedabad, Gujarat PinCode"
        parts = [p.strip() for p in address_cleaned.split(",") if p.strip()]
        if len(parts) > 1:
            # Look for Ahmedabad in parts
            ahmedabad_idx = -1
            for idx, part in enumerate(parts):
                if "Ahmedabad" in part:
                    ahmedabad_idx = idx
                    break

            if ahmedabad_idx > 0:
                # Area is usually the part right before "Ahmedabad"
                area_deduced = parts[ahmedabad_idx - 1]
            else:
                # Fallback to the third-to-last or middle part
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
        "source_url": source_url
    }
