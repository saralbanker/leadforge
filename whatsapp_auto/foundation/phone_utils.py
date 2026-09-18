"""Indian Phone Number Normalization and Validation Utility."""

import re
from typing import Optional


def normalize_indian_phone(raw_phone: Optional[str]) -> Optional[str]:
    """Normalizes raw input into a verified 10-digit Indian mobile number.

    Rules:
    - Strips spaces, dashes, dots, parentheses, and leading '+'.
    - Handles leading country code '91' (12 digits total -> extracts last 10).
    - Handles leading trunk prefix '0' (11 digits total -> extracts last 10).
    - Rejects landlines and invalid numbers: Indian mobiles MUST start with 6, 7, 8, or 9.
      (e.g., Ahmedabad landline 079-25831234 is rejected).

    Returns:
        10-digit string if valid mobile (e.g. '9825012345'), otherwise None.
    """
    if not raw_phone:
        return None

    # Strip non-digits
    digits = re.sub(r"\D", "", str(raw_phone))

    # Reject explicit Ahmedabad STD 079 landlines (079 + 8-digit subscriber starting with 2, 3, 4, 5, 6)
    if digits.startswith(("0792", "0793", "0794", "0795", "0796")):
        return None
    if digits.startswith(("91792", "91793", "91794", "91795", "91796")):
        return None

    # Strip country code +91
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    # Strip trunk prefix 0
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    # Check length
    if len(digits) != 10:
        return None

    # Reject 10-digit strings that match Ahmedabad fixed landlines (792, 793, 794, 795, 796)
    if digits.startswith(("792", "793", "794", "795", "796")):
        return None

    # Check first digit for Indian mobile series (6, 7, 8, 9)
    if digits[0] not in ("6", "7", "8", "9"):
        return None

    return digits


def format_display_phone(phone_10: str) -> str:
    """Formats 10-digit number for clean operator reading: '+91 98250 12345'."""
    if not phone_10 or len(phone_10) != 10:
        return str(phone_10)
    return f"+91 {phone_10[:5]} {phone_10[5:]}"
