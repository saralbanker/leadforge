import re
from urllib.parse import urlparse

def normalize_phone(phone: str) -> str:
    """
    Standardize phone numbers into clean string formatting.
    Removes spaces, dashes, parentheses.
    Ensures '+91' prefix for 10-digit Indian numbers.
    """
    if not phone:
        return ""
    # Strip any formatting character
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)

    # If 10 digits, prepend +91
    if len(cleaned) == 10 and cleaned.isdigit():
        return f"+91{cleaned}"

    # If starts with 91 and is 12 digits, prepend +
    if len(cleaned) == 12 and cleaned.startswith("91") and cleaned.isdigit():
        return f"+{cleaned}"

    # Standardize lead symbol
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    return cleaned

def normalize_website(url: str) -> str:
    """
    Ensure website URL has a scheme prefix (defaulting to https if missing),
    lowercased netloc, and trimmed query parameters.
    """
    if not url:
        return ""
    cleaned = url.strip()

    # Default scheme
    if not re.match(r'^https?://', cleaned, re.IGNORECASE):
        cleaned = "https://" + cleaned

    try:
        parsed = urlparse(cleaned)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path

        # Remove trailing slash from path if empty otherwise
        if path == "/":
            path = ""

        query = parsed.query
        if query:
            return f"{scheme}://{netloc}{path}?{query}"
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return cleaned

def normalize_domain(url: str) -> str:
    """Extract and normalize standard domain name from a URL."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc or parsed.path
        if ":" in netloc:
            netloc = netloc.split(":")[0]
        # Remove www.
        if netloc.lower().startswith("www."):
            netloc = netloc[4:]
        return netloc.strip().lower()
    except Exception:
        return ""

def normalize_category(category: str) -> str:
    """Standardizes category strings into a clean title-cased format."""
    if not category:
        return ""
    cleaned = " ".join(category.split())
    return cleaned.strip().title()

def normalize_email(email: str) -> str:
    """Cleans and standardizes email strings."""
    if not email:
        return ""
    return email.strip().lower()

def normalize_status(status: str) -> str:
    """
    Maps Google Maps statuses into standard values.
    Standard statuses: 'OPERATIONAL', 'TEMPORARILY_CLOSED', 'PERMANENTLY_CLOSED'
    """
    if not status:
        return "OPERATIONAL"
    cleaned = status.strip().upper()

    if "TEMPORARILY" in cleaned or "TEMP" in cleaned:
        return "TEMPORARILY_CLOSED"
    if "PERMANENTLY" in cleaned or "PERM" in cleaned or "CLOSED" in cleaned:
        return "PERMANENTLY_CLOSED"

    return "OPERATIONAL"
