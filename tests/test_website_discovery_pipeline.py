import pytest
from leadforge.validator import BusinessValidator
from leadforge.opportunity_engine import OpportunityIntelligenceEngine
from leadforge.server import ScrapeRequest


def test_validator_website_filter_all():
    validator = BusinessValidator()
    biz_with_site = {
        "name": "Acme Corp",
        "phone": "+919876543210",
        "website": "https://acme.com",
        "address": "123 Main St, Ahmedabad, Gujarat 380001",
        "postal_code": "380001",
        "rating": 4.5,
        "review_count": 50,
        "business_status": "OPERATIONAL",
    }
    biz_no_site = {
        "name": "Beta Tools",
        "phone": "+919876543211",
        "website": "",
        "address": "456 Side St, Ahmedabad, Gujarat 380001",
        "postal_code": "380001",
        "rating": 4.0,
        "review_count": 20,
        "business_status": "OPERATIONAL",
    }

    # Under website_filter="ALL", both should pass basic criteria
    assert validator.validate(biz_with_site, website_filter="ALL") == "PASS"
    assert validator.validate(biz_no_site, website_filter="ALL") == "PASS"


def test_validator_website_filter_has_website():
    validator = BusinessValidator()
    biz_with_site = {
        "name": "Acme Corp",
        "phone": "+919876543210",
        "website": "https://acme.com",
        "address": "123 Main St, Ahmedabad, Gujarat 380001",
        "business_status": "OPERATIONAL",
    }
    biz_no_site = {
        "name": "Beta Tools",
        "phone": "+919876543211",
        "website": "",
        "address": "456 Side St, Ahmedabad, Gujarat 380001",
        "business_status": "OPERATIONAL",
    }

    assert validator.validate(biz_with_site, website_filter="HAS_WEBSITE") == "PASS"
    assert validator.validate(biz_no_site, website_filter="HAS_WEBSITE") == "NO_WEBSITE"


def test_validator_website_filter_no_website():
    validator = BusinessValidator()
    biz_with_site = {
        "name": "Acme Corp",
        "phone": "+919876543210",
        "website": "https://acme.com",
        "address": "123 Main St, Ahmedabad, Gujarat 380001",
        "business_status": "OPERATIONAL",
    }
    biz_no_site = {
        "name": "Beta Tools",
        "phone": "+919876543211",
        "website": "",
        "address": "456 Side St, Ahmedabad, Gujarat 380001",
        "business_status": "OPERATIONAL",
    }

    assert validator.validate(biz_with_site, website_filter="NO_WEBSITE") == "HAS_WEBSITE"
    assert validator.validate(biz_no_site, website_filter="NO_WEBSITE") == "PASS"


def test_opportunity_engine_website_scoring_recalibration():
    engine = OpportunityIntelligenceEngine()
    weights = engine._load_weights()
    biz_payload = {
        "name": "Tech Corp",
        "website": "https://techcorp.in",
        "phone": "+919876543210",
        "business_status": "OPERATIONAL",
        "rating": 4.5,
        "review_count": 25,
    }
    signals, score = engine._compute_signals(biz_payload, weights)
    # Score should be >= 30.0 (has_website=25.0, phone=3.0, operational=12.0, rating=12.0, review=8.0)
    assert score >= 30.0


def test_scrape_request_pydantic_schema():
    req1 = ScrapeRequest(city="Ahmedabad", category="Textiles", limit=20, website_filter="HAS_WEBSITE")
    assert req1.website_filter == "HAS_WEBSITE"

    req2 = ScrapeRequest(city="Surat", category="Diamonds", limit=10, no_website_only=True)
    assert req2.no_website_only is True
