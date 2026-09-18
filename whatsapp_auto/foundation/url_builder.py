"""WhatsApp URL and Deep-Link Builder."""

import urllib.parse
from typing import Literal


def build_whatsapp_link(
    phone_10_digits: str,
    text: str,
    mode: Literal["web", "universal", "api"] = "web",
) -> str:
    """Constructs a pre-filled, URL-encoded WhatsApp deep-link.

    Args:
        phone_10_digits: Exactly 10 digits representing Indian mobile (e.g. '9825012345').
        text: Plain-text message body including line breaks.
        mode:
            - 'web': Opens directly in WhatsApp Web browser tab (`https://web.whatsapp.com/send`).
            - 'universal': Cross-platform (`https://wa.me/91...`) which triggers Desktop app or Mobile app.
            - 'api': Direct API scheme (`https://api.whatsapp.com/send`).

    Returns:
        Full clickable URL string.
    """
    clean_phone = phone_10_digits.strip()
    encoded_text = urllib.parse.quote(text, safe="")

    if mode == "web":
        return f"https://web.whatsapp.com/send?phone=91{clean_phone}&text={encoded_text}"
    elif mode == "api":
        return f"https://api.whatsapp.com/send?phone=91{clean_phone}&text={encoded_text}"
    else:  # universal
        return f"https://wa.me/91{clean_phone}?text={encoded_text}"
