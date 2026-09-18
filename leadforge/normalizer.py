import re
from urllib.parse import urlparse
from leadforge.config import DEFAULT_PHONE_COUNTRY_CODE

# Digits-only country code derived from config (e.g. "+91" → "91", "+1" → "1")
_CC_DIGITS = re.sub(r"\D", "", DEFAULT_PHONE_COUNTRY_CODE)
# Number of digits in a local (un-prefixed) number for this country code
# India: 10, USA/Canada: 10, UK: 10/9 (we use 10 as the common case)
_LOCAL_DIGITS = 10


DUMMY_PHONE_PATTERNS = {
    "1234567890", "0123456789", "0000000000",
    "1111111111", "2222222222", "3333333333", "4444444444",
    "5555555555", "6666666666", "7777777777", "8888888888", "9999999999",
}


def normalize_phone(phone: str) -> str:
    """Standardize phone numbers into clean string formatting for display.

    Removes spaces, dashes, parentheses. Prepends DEFAULT_PHONE_COUNTRY_CODE
    for bare local-length numbers that have no existing country prefix.
    Strips 'tel:' URI schemes and single leading trunk zeros.
    Use canonical_phone() for deduplication lookups — not this function.
    """
    if not phone:
        return ""
    # Strip URI schemes (tel:, callto:) and parameters (?call_type=)
    cleaned = str(phone).strip()
    cleaned = re.sub(r"^(?:tel|callto):/{0,2}", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.split("?")[0].split("#")[0]

    # If multiple numbers are separated by slash or comma, take the primary one
    if "/" in cleaned:
        cleaned = cleaned.split("/")[0].strip()
    if "," in cleaned:
        cleaned = cleaned.split(",")[0].strip()

    cleaned = re.sub(r"[\s\-\(\)\.]", "", cleaned)

    # Already has an explicit + prefix
    if cleaned.startswith("+"):
        # Fix +9109825... (trunk zero after country code)
        if cleaned.startswith(f"+{_CC_DIGITS}0") and len(cleaned) == len(_CC_DIGITS) + 2 + _LOCAL_DIGITS:
            cleaned = f"+{_CC_DIGITS}" + cleaned[len(_CC_DIGITS) + 2:]
        return cleaned

    # Strip leading 00 international prefix → convert to +
    if cleaned.startswith("00") and len(cleaned) > 4:
        return "+" + cleaned[2:]

    # Strip single leading zero before local number (e.g. 09876543210 → 9876543210)
    if len(cleaned) == _LOCAL_DIGITS + 1 and cleaned.startswith("0"):
        cleaned = cleaned[1:]

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

    All formatting is stripped. Bare local-length numbers get the
    configured country code prepended (controlled by DEFAULT_PHONE_COUNTRY_CODE
    in config.py). Invalid or dummy numbers return empty string.

    Examples (default +91 / India)
    --------
    "+91 98765 43210"  → "919876543210"
    "9876543210"       → "919876543210"   (10-digit → prepend 91)
    "919876543210"     → "919876543210"
    "00919876543210"   → "919876543210"   (00 prefix stripped)
    "09876543210"      → "919876543210"   (0 prefix stripped)
    ""                 → ""
    """
    if not phone:
        return ""
    # Strip URI schemes first
    raw = str(phone).strip()
    raw = re.sub(r"^(?:tel|callto):/{0,2}", "", raw, flags=re.IGNORECASE)
    raw = raw.split("?")[0].split("#")[0]
    if "/" in raw:
        raw = raw.split("/")[0].strip()
    if "," in raw:
        raw = raw.split(",")[0].strip()

    digits = re.sub(r"\D", "", raw)
    if not digits:
        return ""
    # Filter all identical digits (e.g. 0000000000, 9999999999)
    if len(set(digits)) <= 1 or digits.startswith("000000"):
        return ""
    # Strip leading 00 (international dialling prefix)
    if digits.startswith("00") and len(digits) > 4:
        digits = digits[2:]
    # Strip leading zero before local number (e.g. 09876543210 → 9876543210)
    if len(digits) == _LOCAL_DIGITS + 1 and digits.startswith("0"):
        digits = digits[1:]
    # Bare local-length number → prepend digits-only country code
    if len(digits) == _LOCAL_DIGITS:
        if digits in DUMMY_PHONE_PATTERNS:
            return ""
        digits = _CC_DIGITS + digits
    elif len(digits) == _LOCAL_DIGITS + len(_CC_DIGITS) and digits.startswith(_CC_DIGITS):
        local_part = digits[len(_CC_DIGITS):]
        if local_part in DUMMY_PHONE_PATTERNS:
            return ""
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


# Zero-width and bidi characters that Google Maps listings pick up and that
# make a subject line look machine-generated to a spam filter.
_INVISIBLE_CHARS = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")

# Separators after which a Maps listing usually starts keyword-stuffing:
# "Noble Brothers | Tarpaulin Manufacturer in Ahmedabad | Hdpe ..."
_NAME_SPLIT = re.compile(r"\s*[|｜]\s*|\s+[-–—]\s+|\s*\(")

_ENTITY_SUFFIX = re.compile(
    r"\b(pvt\.?\s*ltd\.?|private\s+limited|ltd\.?|llp|inc\.?|co\.?)\s*$",
    re.IGNORECASE,
)


def clean_business_name(name: str, max_length: int = 42) -> str:
    """Reduces an SEO-stuffed Maps listing to the name a human would use.

    Listings routinely carry their whole keyword strategy in the title -
    "ADORN AESTHETICS - Best Hair Transplant Clinic in Ahmedabad | Cosmetic
    Surgery in Ahmedabad | ..." at 124 characters. Dropped into a subject
    line verbatim that reads as bulk mail. Keeps the leading segment, which
    is nearly always the trading name.
    """
    if not name:
        return ""

    cleaned = _INVISIBLE_CHARS.sub("", name)
    cleaned = " ".join(cleaned.split())

    head = _NAME_SPLIT.split(cleaned, maxsplit=1)[0].strip(" ,-–—|(")
    if not head:
        head = cleaned

    # A separator can sit mid-name ("Dr. Arth Shah - Plastic Surgeon"); if the
    # split left almost nothing, keep more of the original instead.
    if len(head) < 3:
        head = cleaned

    if len(head) > max_length:
        truncated = head[:max_length].rsplit(" ", 1)[0]
        head = truncated or head[:max_length]

    # Never end on a dangling conjunction or punctuation ("Elite Surgery Clinic &").
    head = re.sub(r"\s*(?:&|and|\+|,|-|–|—)\s*$", "", head.strip(), flags=re.IGNORECASE)

    return head.strip() or cleaned[:max_length].strip()


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
    import urllib.parse
    cleaned = urllib.parse.unquote(str(email)).strip().lower()
    cleaned = re.sub(r"^mailto:", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned


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
