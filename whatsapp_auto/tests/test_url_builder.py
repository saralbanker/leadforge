"""Tests for foundation/url_builder.py."""

import urllib.parse
import pytest
from foundation.url_builder import build_whatsapp_link


class TestUrlBuilder:
    """Test suite for WhatsApp deep link generation."""

    def test_web_mode(self):
        link = build_whatsapp_link("9825012345", "Hello Sir,\nHow are you?", mode="web")
        assert link.startswith("https://web.whatsapp.com/send?phone=919825012345&text=")
        assert "Hello%20Sir%2C%0AHow%20are%20you%3F" in link

    def test_universal_mode(self):
        link = build_whatsapp_link("9825012345", "Hello Sir", mode="universal")
        assert link.startswith("https://wa.me/919825012345?text=")
        assert "Hello%20Sir" in link

    def test_api_mode(self):
        link = build_whatsapp_link("9825012345", "Hello Sir", mode="api")
        assert link.startswith("https://api.whatsapp.com/send?phone=919825012345&text=")

    def test_special_characters_encoded(self):
        text = "Hello & Welcome! Price: ₹15,000 / unit?"
        link = build_whatsapp_link("9825012345", text, mode="web")
        # Ensure & and ? in message body do not break query parameters
        parsed = urllib.parse.urlparse(link)
        params = urllib.parse.parse_qs(parsed.query)
        assert params["phone"] == ["919825012345"]
        assert params["text"] == [text]
