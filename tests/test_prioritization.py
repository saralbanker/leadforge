from leadforge.prioritization import LeadPrioritizationEngine
from leadforge.scorer import process_and_score_leads


def test_deterministic_repeatability():
    """Verify identical input always produces identical score and breakdown."""
    lead = {
        "name": "Apex Dental Clinic",
        "category": "Dentist",
        "has_website": False,
        "rating": 3.8,
        "review_count": 65,
        "phone": "+1 555-0199",
        "contact_email": "info@apexdental.com",
        "maturity_score": 35.0,
        "maturity_grade": "F",
    }

    res1 = LeadPrioritizationEngine.calculate_priority(lead)
    res2 = LeadPrioritizationEngine.calculate_priority(lead)

    assert res1.overall_score == res2.overall_score
    assert res1.priority_tier == res2.priority_tier
    assert res1.score_breakdown == res2.score_breakdown
    assert res1.explanation == res2.explanation


def test_maximum_critical_score():
    """Verify a top-tier candidate achieves CRITICAL priority (>85 pts)."""
    lead = {
        "name": "Premier Plumbing",
        "category": "Plumbing",
        "has_website": False,  # 25 pts
        "maturity_grade": "F",  # 20 pts
        "rating": 3.5,
        "review_count": 80,  # 20 pts
        "phone": "555-123-4567",
        "contact_email": "contact@premierplumbing.com",  # 15 pts
        # Category Plumbing: 15 pts
        # Total = 95.0 pts (CRITICAL)
    }

    res = LeadPrioritizationEngine.calculate_priority(lead)
    assert res.overall_score >= 85.0
    assert res.priority_tier == "CRITICAL"
    assert len(res.explanation) > 0


def test_minimum_low_score():
    """Verify a low priority candidate receives LOW tier (<50 pts)."""
    lead = {
        "name": "Generic Shop",
        "category": "Retail",
        "website": "https://genericshop.com",
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 1.0,  # 5 pts
        "maturity_grade": "A",
        "maturity_score": 90.0,  # 5 pts
        "rating": 4.8,
        "review_count": 2,  # 5 pts
        "phone": "",
        "contact_email": "",  # 0 pts
        # Category Retail: 5 pts
        # Total = 20.0 pts (LOW)
    }

    res = LeadPrioritizationEngine.calculate_priority(lead)
    assert res.overall_score < 50.0
    assert res.priority_tier == "LOW"


def test_boundary_values():
    """Verify tier assignment exact boundary rules."""
    # Score 85.0 -> CRITICAL
    lead_crit = {
        "has_website": False,  # 25
        "maturity_grade": "F",  # 20
        "rating": 3.8,
        "review_count": 100,  # 20
        "phone": "555-000-1111",  # 10 (phone only)
        "category": "Dentist",  # 15
        # Total = 90 -> CRITICAL
    }
    assert LeadPrioritizationEngine.calculate_priority(lead_crit).priority_tier == "CRITICAL"

    # Medium boundary
    lead_med = {
        "website": "https://example.com",
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 1.5,  # 5
        "maturity_grade": "C",  # 12
        "review_count": 25,  # 15
        "phone": "555-000-1111",  # 10
        "category": "Restaurant",  # 10
        # Total = 52 -> MEDIUM
    }
    res_med = LeadPrioritizationEngine.calculate_priority(lead_med)
    assert res_med.overall_score >= 50.0 and res_med.overall_score < 70.0
    assert res_med.priority_tier == "MEDIUM"


def test_missing_optional_fields():
    """Verify calculation gracefully handles empty or missing fields."""
    empty_lead = {}
    res = LeadPrioritizationEngine.calculate_priority(empty_lead)
    assert isinstance(res.overall_score, float)
    assert res.priority_tier in ("CRITICAL", "HIGH", "MEDIUM", "LOW")
    assert isinstance(res.score_breakdown, dict)


def test_invalid_field_types():
    """Verify non-numeric rating/reviews or malformed inputs do not crash scoring."""
    malformed_lead = {
        "rating": "INVALID_RATING",
        "review_count": "NOT_A_NUMBER",
        "load_time_seconds": None,
        "phone": 123456789,  # Non-string phone
    }
    res = LeadPrioritizationEngine.calculate_priority(malformed_lead)
    assert isinstance(res.overall_score, float)


def test_scorer_wrapper_integration():
    """Verify legacy score_lead and process_and_score_leads delegate cleanly."""
    leads = [
        {"name": "Low Priority", "website": "https://a.com", "has_website": True, "ssl_valid": True, "load_time_seconds": 0.5},
        {"name": "High Priority", "has_website": False, "category": "Roofing", "phone": "555-999-8888", "contact_email": "r@roof.com"},
    ]

    processed = process_and_score_leads(leads)
    assert len(processed) == 2
    assert processed[0]["name"] == "High Priority"
    assert processed[0]["score"] > processed[1]["score"]
