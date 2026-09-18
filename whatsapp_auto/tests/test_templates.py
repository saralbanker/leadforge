"""Tests for foundation/templates.py."""

import pytest
from foundation.templates import (
    clean_company_name,
    clean_product_name,
    render_template_a,
    render_template_b,
    render_template_c,
)


class TestCleanCompanyName:
    """Test suite for cleaning company names."""

    def test_strip_seo_dash_suffix(self):
        raw = "Mahalaxmi Sales - Industrial equipment supplier in Ahmedabad"
        assert clean_company_name(raw) == "Mahalaxmi Sales"

    def test_strip_pvt_ltd(self):
        assert clean_company_name("Beena Engineering Pvt Ltd") == "Beena Engineering"
        assert clean_company_name("Beena Engineering Pvt. Ltd.") == "Beena Engineering"
        assert clean_company_name("Beena Engineering Private Limited") == "Beena Engineering"

    def test_strip_trailing_punctuation(self):
        """Should strip trailing dot after Private Limited or Ltd."""
        # e.g. "JAY Chemical Industries Private Limited."
        assert clean_company_name("JAY Chemical Industries Private Limited.") == "JAY Chemical Industries"

    def test_strip_parenthetical_groups(self):
        """Should clean parenthetical group tags like '( Bhimani Group )'."""
        assert "Bhimani Group" not in clean_company_name("Bhimani Chemicals Pvt. Ltd. ( Bhimani Group )")

    def test_clean_fallback(self):
        assert clean_company_name("") == "your company"
        assert clean_company_name(None) == "your company"


class TestCleanProductName:
    """Test suite for cleaning product categories."""

    def test_clean_json_brackets_and_quotes(self):
        raw = '["industrial equipment supplier"]'
        assert clean_product_name(raw) == "industrial equipment"

    def test_clean_single_word_manufacturer(self):
        """Should handle standalone '["manufacturer"]' without returning raw 'manufacturer'."""
        cleaned = clean_product_name('["manufacturer"]')
        assert cleaned != "manufacturer", f"Expected descriptive category fallback, got: '{cleaned}'"

    def test_clean_chemical_manufacturer(self):
        assert clean_product_name('["chemical manufacturer"]') == "chemical"

    def test_fallback(self):
        assert clean_product_name(None) == "industrial equipment"
        assert clean_product_name("") == "industrial equipment"


class TestTemplateRendering:
    """Test suite for template generation."""

    def test_template_a_structure(self):
        msg = render_template_a(
            company_name="Beena Engineering Pvt Ltd",
            products='["industrial valves supplier"]',
            area="Vatva GIDC",
        )
        assert "Hello Sir," in msg
        assert "Beena Engineering" in msg
        assert "Pvt Ltd" not in msg
        assert "Vatva GIDC" in msg
        assert "industrial valves" in msg
        assert '["' not in msg, "JSON brackets leaked into Template A"

    def test_template_b_no_json_leak(self):
        """Verify Template B cleans product category and does not leak JSON syntax."""
        msg = render_template_b(
            company_name="Metro Chem Industries",
            products='["chemical manufacturer"]',
            area="Vatva",
        )
        assert '["' not in msg, f"JSON brackets leaked into Template B: {msg}"
        assert "chemical" in msg

    def test_template_c_no_json_leak(self):
        """Verify Template C cleans product category and does not leak JSON syntax."""
        msg = render_template_c(
            company_name="Satguru Valve Corporation",
            products='["manufacturer"]',
            area="Kazipur Dariyapur",
        )
        assert '["' not in msg, f"JSON brackets leaked into Template C: {msg}"

    def test_word_count_limits(self):
        """Templates must be concise (< 70 words) for high WhatsApp readability."""
        msg = render_template_a("Acme Engineering", "valves", "Odhav")
        words = len(msg.split())
        assert words <= 70, f"Template A is too long: {words} words"
