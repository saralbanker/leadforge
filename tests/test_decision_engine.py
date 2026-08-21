import os
import sqlite3
import tempfile
import pytest
from leadforge.decision_engine import DecisionEngine, DecisionObject


@pytest.fixture(autouse=True)
def initialize_test_db():
    """Fixture ensuring temporary test DB is initialized with migrations for DecisionEngine tests."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    os.environ["LEADFORGE_DB_PATH"] = path

    from leadforge.database import initialize_database
    initialize_database()

    yield

    if os.path.exists(path):
        os.remove(path)


def test_deterministic_decision_repeatability():
    """Verify identical business data input always produces 100% identical DecisionObject."""
    engine = DecisionEngine()
    data = {
        "category": "Dentist",
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 1.2,
        "rating": 4.5,
        "review_count": 25,
    }

    d1 = engine.evaluate_decision(data)
    d2 = engine.evaluate_decision(data)

    assert d1.service_name == d2.service_name
    assert d1.campaign_name == d2.campaign_name
    assert d1.outreach_strategy == d2.outreach_strategy
    assert d1.primary_cta == d2.primary_cta
    assert d1.reasoning == d2.reasoning


def test_no_website_decision_routing():
    """Verify business with no website routes to Digital Transformation offer and strategy."""
    engine = DecisionEngine()
    data = {
        "category": "Plumbing",
        "has_website": False,
    }

    decision = engine.evaluate_decision(data)
    assert decision.outreach_strategy == "DIGITAL_TRANSFORMATION"
    assert "Website Design" in decision.service_name
    assert "mock design" in decision.primary_cta
    assert any("No website detected" in r for r in decision.reasoning)


def test_ssl_invalid_decision_routing():
    """Verify business with invalid SSL routes to Technical Remediation."""
    engine = DecisionEngine()
    data = {
        "category": "Lawyer",
        "has_website": True,
        "ssl_valid": False,
        "load_time_seconds": 1.5,
    }

    decision = engine.evaluate_decision(data)
    assert decision.outreach_strategy == "TECHNICAL_REMEDIATION"
    assert "SSL" in decision.service_name
    assert "browser warning" in decision.primary_cta


def test_slow_load_time_decision_routing():
    """Verify business with slow load time (>3.0s) routes to Performance Remediation."""
    engine = DecisionEngine()
    data = {
        "category": "Accounting",
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 4.5,
    }

    decision = engine.evaluate_decision(data)
    assert decision.outreach_strategy == "PERFORMANCE_REMEDIATION"
    assert "Speed Optimization" in decision.service_name


def test_booking_category_decision_routing():
    """Verify appointment/booking category (Clinics, Dentists, Salons) routes to Booking Portal offer."""
    engine = DecisionEngine()
    data = {
        "category": "Dental Clinic",
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 1.0,
    }

    decision = engine.evaluate_decision(data)
    assert decision.outreach_strategy == "CONVERSION_OPTIMIZATION"
    assert "Booking" in decision.service_name
    assert "Campaign B (Booking)" in decision.campaign_name


def test_distributor_category_decision_routing():
    """Verify wholesale/distributor category routes to Order Portal offer."""
    engine = DecisionEngine()
    data = {
        "category": "Wholesalers",
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 1.0,
    }

    decision = engine.evaluate_decision(data)
    assert "Order" in decision.service_name
    assert "Order Portal" in decision.campaign_name


def test_unknown_category_fallback():
    """Verify unknown category falls back gracefully to standard campaign routing."""
    engine = DecisionEngine()
    data = {
        "category": "Niche Speciality Industry",
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 1.0,
    }

    decision = engine.evaluate_decision(data)
    assert decision.outreach_strategy == "GENERAL_GROWTH"
    assert "Local SEO" in decision.service_name
    assert len(decision.reasoning) > 0
