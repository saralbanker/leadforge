import re
from urllib.parse import urlparse
from leadforge.config import DEFAULT_PHONE_COUNTRY_CODE

# Digits-only country code derived from config (e.g. "+91" → "91", "+1" → "1")
_CC_DIGITS = re.sub(r"\D", "", DEFAULT_PHONE_COUNTRY_CODE)
# Number of digits in a local (un-prefixed) number for this country code
# India: 10, USA/Canada: 10, UK: 10/9 (we use 10 as the common case)
_LOCAL_DIGITS = 10


def normalize_phone(phone: str) -> str:
    """Standardize phone numbers into clean string formatting for display.

    Removes spaces, dashes, parentheses.  Prepends DEFAULT_PHONE_COUNTRY_CODE
    for bare local-length numbers that have no existing country prefix.
    Use canonical_phone() for deduplication lookups — not this function.
    """
    if not phone:
        return ""
    cleaned = re.sub(r"[\s\-\(\)]", "", phone)

    # Already has an explicit + prefix — trust it
    if cleaned.startswith("+"):
        return cleaned

    # Strip leading 00 international prefix → convert to +
    if cleaned.startswith("00") and len(cleaned) > 4:
        return "+" + cleaned[2:]

    # Bare local-length digits → prepend configured country code
    if len(cleaned) == _LOCAL_DIGITS and cleaned.isdigit():
        return f"{DEFAULT_PHONE_COUNTRY_CODE}{cleaned}"

    # Already has country code prepended without + (e.g. "919876543210")
    cc_len = len(_CC_DIGITS)
    if (
        len(cleaned) == _LOCAL_DIGITS + cc_len
        and cleaned.startswith(_CC_DIGITS)
        and cleaned.isdigit()
    ):
        return f"+{cleaned}"

    return cleaned


def canonical_phone(phone: str) -> str:
    """Return a digits-only canonical phone string for deduplication.

    All formatting is stripped.  Bare local-length numbers get the
    configured country code prepended (controlled by DEFAULT_PHONE_COUNTRY_CODE
    in config.py).

    Examples (default +91 / India)
    --------
    "+91 98765 43210"  → "919876543210"
    "9876543210"       → "919876543210"   (10-digit → prepend 91)
    "919876543210"     → "919876543210"
    "00919876543210"   → "919876543210"   (00 prefix stripped)
    ""                 → ""
    """
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    if not digits:
        return ""
    # Strip leading 00 (international dialling prefix)
    if digits.startswith("00") and len(digits) > 4:
        digits = digits[2:]
    # Strip leading zero before local number (e.g. 09876543210 → 9876543210)
    if len(digits) == _LOCAL_DIGITS + 1 and digits.startswith("0"):
        digits = digits[1:]
    # Bare local-length number → prepend digits-only country code
    if len(digits) == _LOCAL_DIGITS:
        digits = _CC_DIGITS + digits
    return digits


def normalize_website(url: str) -> str:
    """
    Ensure website URL has a scheme prefix (defaulting to https if missing),
    lowercased netloc, and trimmed query parameters.
    """
    if not url:
        return ""
    cleaned = url.strip()

    # Default scheme
    if not re.match(r"^https?://", cleaned, re.IGNORECASE):
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

    if cleaned in ("OPERATIONAL", "OPEN", "OPEN NOW"):
        return "OPERATIONAL"
    if "TEMPORARILY" in cleaned or "TEMP" in cleaned:
        return "TEMPORARILY_CLOSED"
    if "PERMANENTLY" in cleaned or "PERM" in cleaned:
        return "PERMANENTLY_CLOSED"
    # Bare "CLOSED" is ambiguous — treat as temporarily closed rather than permanently
    if cleaned == "CLOSED":
        return "TEMPORARILY_CLOSED"
    # Unrecognised status — do not assume OPERATIONAL
    return "UNKNOWN"
