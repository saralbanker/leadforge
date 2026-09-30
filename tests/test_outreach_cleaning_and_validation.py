"""Tests for outreach company name cleaning, subject rendering length, and email validation."""

import pytest
from leadforge.outreach.cleaning import clean_company_name
from leadforge.normalizer import normalize_email, is_valid_recipient_email
from leadforge.outreach.router import CampaignRouter
from leadforge.outreach.generator import OllamaHookGenerator
from whatsapp_auto.foundation.templates import clean_company_name as whatsapp_clean_company_name


def test_clean_company_name_rajsagar_and_protekg():
    """Verify specific problematic company names are properly cleaned of SEO and legal tags."""
    rajsagar_raw = "Rajsagar Steel Pvt Ltd - MS Seamless Pipes, Line Pipes, ST52 Pipes, CS Seamless"
    assert clean_company_name(rajsagar_raw) == "Rajsagar Steel"
    assert whatsapp_clean_company_name(rajsagar_raw) == "Rajsagar Steel"

    protekg_raw = "ProtekG Power Electronics Pvt Ltd - Online UPS Manufacturers"
    assert clean_company_name(protekg_raw) == "ProtekG Power Electronics"
    assert whatsapp_clean_company_name(protekg_raw) == "ProtekG Power Electronics"


def test_clean_company_name_edge_cases():
    """Verify edge cases: pipe tags, parentheticals, legal suffixes, empty strings."""
    assert clean_company_name("") == "your company"
    assert clean_company_name(None) == "your company"
    assert clean_company_name("Acme Pipes | Best Pipe Manufacturer") == "Acme Pipes"
    assert clean_company_name("Delta Industries (Bhimani Group)") == "Delta Industries"
    assert clean_company_name("Zenith Valves LLP") == "Zenith Valves"
    assert clean_company_name("Apex Pumps & Systems Private Limited.") == "Apex Pumps & Systems"


def test_normalize_email_strips_mailto_and_percent20():
    """Verify mailto:, URL-encoded spaces (%20), and trailing/internal spaces are cleaned."""
    assert normalize_email("mailto:info@rohanchemicals.com") == "info@rohanchemicals.com"
    assert normalize_email("%20info@rohanchemicals.com") == "info@rohanchemicals.com"
    assert normalize_email("mailto:%20info@rohanchemicals.com") == "info@rohanchemicals.com"
    assert normalize_email("  sales@example.com  ") == "sales@example.com"
    assert normalize_email("contact@example.co.in") == "contact@example.co.in"


def test_is_valid_recipient_email():
    """Verify defensive validation catches %20, spaces, empty, and invalid RFC formats."""
    valid, err = is_valid_recipient_email("info@rohanchemicals.com")
    assert valid is True
    assert err is None

    # Rejection of percent sign
    valid, err = is_valid_recipient_email("%20info@rohanchemicals.com")
    assert valid is False
    assert "percent" in err.lower()

    # Rejection of leading / trailing whitespace
    valid, err = is_valid_recipient_email(" info@rohanchemicals.com")
    assert valid is False
    assert "whitespace" in err.lower()

    valid, err = is_valid_recipient_email("info@rohanchemicals.com ")
    assert valid is False
    assert "whitespace" in err.lower()

    # Rejection of invalid structure
    valid, err = is_valid_recipient_email("not-an-email")
    assert valid is False

    valid, err = is_valid_recipient_email("@missinguser.com")
    assert valid is False

    valid, err = is_valid_recipient_email("")
    assert valid is False


def test_subject_rendering_with_cleaned_name_length():
    """Verify subject lines rendered with cleaned business names stay under 50-60 chars."""
    raw_name = "Rajsagar Steel Pvt Ltd - MS Seamless Pipes, Line Pipes, ST52 Pipes, CS Seamless"
    
    templates = [
        "product catalog for {business_name}",
        "quick note on dealer orders: {business_name}",
        "note on repeat orders: {business_name}",
        "direct web page for {business_name}",
        "client bookings for {business_name}",
        "website updates for {business_name}",
        "web speed for {business_name}",
    ]

    for tpl in templates:
        rendered = CampaignRouter.render_subject(tpl, business_name=raw_name)
        # Should contain Rajsagar Steel, not the raw SEO junk
        assert "Rajsagar Steel" in rendered
        assert "Seamless" not in rendered
        # Character count check: direct, punchy subjects (<= 50 chars)
        assert len(rendered) <= 50, f"Subject too long ({len(rendered)} chars): '{rendered}'"


def test_shorten_company_name():
    """Verify that shorten_company_name compresses long names by stripping unseparated SEO tags,
    corporate descriptors, and truncating at word boundaries."""
    from leadforge.outreach.cleaning import shorten_company_name

    # Unseparated SEO tags stripped
    khyati = "Khyati Industries Sheet Metal Parts manufacturer"
    assert shorten_company_name(khyati, max_chars=22) == "Khyati Industries"

    sanju = "Sanju sales Agarbatti and pujapa wholesaler"
    assert shorten_company_name(sanju, max_chars=22) == "Sanju sales"

    # Corporate descriptor stripped when long
    smtpl = "Sahajanand Medical Technologies Pvt. Ltd."
    assert shorten_company_name(smtpl, max_chars=22) == "Sahajanand Medical"

    shivam = "Shivam Hydraulic Pumps & Cylinders"
    assert shorten_company_name(shivam, max_chars=22) == "Shivam Hydraulic Pumps"

    # Short names unaffected
    assert shorten_company_name("Firestop", max_chars=22) == "Firestop"
    assert shorten_company_name("Mazda Limited", max_chars=22) == "Mazda"


def test_hook_generation_uses_cleaned_name():
    """Verify OllamaHookGenerator fallbacks and prompt variables use cleaned company name."""
    gen = OllamaHookGenerator(api_url="http://127.0.0.1:9")  # Unreachable port -> deterministic fallback
    raw_name = "Rajsagar Steel Pvt Ltd - MS Seamless Pipes, Line Pipes, ST52 Pipes, CS Seamless"

    hook = gen.generate_hook(
        business_name=raw_name,
        review_count=0,
        rating=4.5,
        city="Ahmedabad",
        scraped_text="Steel supplier in Naroda",
        category="Steel Supplier",
        area="Naroda",
        has_website=True,
    )
    assert "Rajsagar Steel" in hook
    assert "Seamless" not in hook
