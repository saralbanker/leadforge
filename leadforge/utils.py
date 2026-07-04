import logging
import sys
import time
from typing import List, Dict, Any
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


def clean_text(text: Any) -> str:
    """Helper to clean extra whitespaces and newline characters."""
    if text is None:
        return ""
    text_str = str(text)
    if not text_str.strip() or text_str.lower() == "nan":
        return ""
    return " ".join(text_str.split())
