"""CAN-SPAM and CASL compliance validation utilities."""

from __future__ import annotations

import re
from typing import Tuple


def validate_postal_address(address: str) -> Tuple[bool, str]:
    """Validates that a string is a genuine physical postal address under CAN-SPAM / CASL.

    A valid address requires:
      - Minimum length (>= 15 characters).
      - Absence of placeholder or dummy strings (e.g. 'test', 'example', 'fake').
      - Presence of numeric digits (street number, box/suite number, or postal code).
      - At least 3 distinct component words (e.g. street, city, state/postal code).
      - Standard address separators (commas, newlines, or semicolons).
    """
    if not address or not isinstance(address, str):
        return False, "Address is missing or empty."

    raw = address.strip()
    if len(raw) < 15:
        return False, f"Address '{raw}' is too short ({len(raw)} chars; minimum 15 characters required)."

    lower = raw.lower()
    placeholders = [
        "test",
        "example",
        "fake",
        "placeholder",
        "asdf",
        "sample",
        "tbd",
        "xxx",
        "123 main street",
        "nowhere",
        "dummy",
    ]
    for ph in placeholders:
        if ph in lower:
            return False, f"Address contains placeholder pattern '{ph}'."

    # Must contain numeric digits (street number, PO Box, or PIN/ZIP code)
    has_digit = any(c.isdigit() for c in raw)
    has_po_box = "p.o. box" in lower or "po box" in lower or "post box" in lower
    if not has_digit and not has_po_box:
        return False, "Address must contain a street number, box number, or postal code."

    # Word count
    words = [w for w in re.split(r"[\s,;]+", raw) if w.strip()]
    if len(words) < 3:
        return False, "Address must contain at least 3 distinct components (street, city/locality, postal code)."

    # Must contain a standard separator
    if not any(c in raw for c in [",", "\n", ";"]):
        return False, "Address must be structured with commas or newlines separating street, city, and postal code."

    return True, "Valid postal address."
