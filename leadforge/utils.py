import logging
import re
import sys
import time
from typing import List, Dict, Any, Optional
from leadforge.config import LOGS_DIR

# Configure Logging
log_file_path = LOGS_DIR / "run.log"

logger = logging.getLogger("leadforge")
logger.setLevel(logging.INFO)

# File Handler
file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
file_formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
file_handler.setFormatter(file_formatter)
logger.addHandler(file_handler)

# Console Handler
console_handler = logging.StreamHandler(sys.stdout)
console_formatter = logging.Formatter("%(message)s")
console_handler.setFormatter(console_formatter)
logger.addHandler(console_handler)


def get_logger() -> logging.Logger:
    """Returns the configured logger instance."""
    return logger


def measure_time(func):
    """Decorator to measure execution duration of a function."""

    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        duration = time.time() - start_time
        logger.info(f"Execution of '{func.__name__}' took {duration:.2f} seconds.")
        return result, duration

    return wrapper


def deduplicate_leads(leads: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Remove duplicate businesses from the list.
    Matching is done by lowercased, whitespace-stripped Business Name
    combined with Phone Number or Address (if phone is unavailable).
    """
    seen = set()
    unique_leads = []

    for lead in leads:
        name = str(lead.get("name", "")).strip().lower()
        phone = str(lead.get("phone", "")).strip().replace(" ", "").replace("-", "")
        address = str(lead.get("address", "")).strip().lower()

        # If phone is available, key on name + phone, else key on name + address
        if phone:
            key = f"{name}::{phone}"
        else:
            key = f"{name}::{address[:50]}"

        if key not in seen and name:
            seen.add(key)
            unique_leads.append(lead)

    return unique_leads


# Google Place ID URL patterns, checked in priority order.
# 1. Hex feature ID embedded in the data blob (…!1s0x…:0x…)
# 2. Hex feature ID as an explicit ftid query parameter
# 3. Textual place ID in the data blob (…!19sChIJ…)
# 4. Textual place ID as query parameter (place_id=ChIJ… / q=place_id:ChIJ…)
_PLACE_ID_PATTERNS = [
    re.compile(r"1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)"),
    re.compile(r"[?&]ftid=(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)"),
    re.compile(r"!19s(ChIJ[A-Za-z0-9_-]+)"),
    re.compile(r"place_id[=:](ChIJ[A-Za-z0-9_-]+)"),
]


def extract_place_id(url: str) -> Optional[str]:
    """Extract a deterministic Google Place ID from any known Maps URL variant.

    Returns None when the URL carries no recognizable place identifier.
    """
    if not url:
        return None
    for pattern in _PLACE_ID_PATTERNS:
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


def clean_text(text: Any) -> str:
    """Helper to clean extra whitespaces and newline characters."""
    if text is None:
        return ""
    text_str = str(text)
    if not text_str.strip() or text_str.lower() == "nan":
        return ""
    return " ".join(text_str.split())
