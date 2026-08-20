import pytest
import yaml
from pathlib import Path
from leadforge.outreach.router import CampaignRouter


@pytest.fixture
def temp_campaign_config(tmp_path: Path) -> Path:
    """Fixture to create a temporary campaign_routing.yaml file for testing."""
    config_data = {
        "campaigns": [
            {
                "name": "Campaign A",
                "target_offer": "Web Design Offer",
                "criteria": {
                    "has_website": False,
                    "max_load_time_seconds": 3.0,
                },
                "copy_template": {
                    "subject": "Design Subject",
                    "body_structure": "Design Body",
                },
            },
            {
                "name": "Campaign B (Special)",
                "target_offer": "Software Integration Offer",
                "criteria": {
                    "has_website": True,
                    "ssl_valid": True,
                    "categories": ["Dentist", "Physio"],
                },
                "copy_template": {
                    "subject": "Special Subject",
                    "body_structure": "Special Body",
                },
            },
            {
                "name": "Campaign C (Standard)",
                "target_offer": "General Software Offer",
                "criteria": {
                    "has_website": True,
                },
                "copy_template": {
                    "subject": "Standard Subject",
                    "body_structure": "Standard Body",
                },
            },
        ]
    }
    config_file = tmp_path / "test_campaign_routing.yaml"
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f)
    return config_file


def test_router_loads_config(temp_campaign_config: Path):
    """Verify router successfully parses YAML campaign configurations."""
    router = CampaignRouter(config_path=temp_campaign_config)
    assert len(router.campaigns) == 3
    assert router.campaigns[0]["name"] == "Campaign A"


def test_router_missing_config():
    """Verify router handles non-existent config path gracefully by returning an empty list."""
    router = CampaignRouter(config_path=Path("non_existent_file.yaml"))
    assert router.campaigns == []


def test_route_campaign_a_no_website(temp_campaign_config: Path):
    """Campaign A should match if has_website is False."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="Dentist",
        has_website=False,
        ssl_valid=True,
        load_time_seconds=1.5,
    )
    assert matched is not None
    assert matched["name"] == "Campaign A"
    assert matched["target_offer"] == "Web Design Offer"


def test_route_campaign_a_slow_website_rejected(temp_campaign_config: Path):
    """Campaign A should fail to match if website load time is higher than max limit."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="Dentist",
        has_website=False,
        ssl_valid=True,
        load_time_seconds=4.0,  # exceeds 3.0 max limit
    )
    assert matched is None


def test_route_campaign_b_category_match(temp_campaign_config: Path):
    """Campaign B should match if website exists, SSL is valid, and category matches."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="Dentist",
        has_website=True,
        ssl_valid=True,
        load_time_seconds=1.2,
    )
    assert matched is not None
    assert matched["name"] == "Campaign B (Special)"


def test_route_campaign_b_unmatched_category_falls_to_c(temp_campaign_config: Path):
    """If category does not match Campaign B, it should fall back to Campaign C."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="Wholesaler",  # not in Dentist / Physio
        has_website=True,
        ssl_valid=True,
        load_time_seconds=1.2,
    )
    assert matched is not None
    assert matched["name"] == "Campaign C (Standard)"


def test_route_empty_category_does_not_match_category_restricted_campaign(temp_campaign_config: Path):
    """An empty/unknown category must not satisfy a category-restricted campaign
    (regression: empty string is a substring of every string, so the fuzzy
    category match previously treated unknown category as a universal match)."""
    router = CampaignRouter(config_path=temp_campaign_config)
    matched = router.route_lead(
        category="",
        has_website=True,
        ssl_valid=True,
        load_time_seconds=1.2,
    )
    assert matched is not None
    assert matched["name"] == "Campaign C (Standard)"  # falls through, not Campaign B


def test_route_no_matches(temp_campaign_config: Path):
    """If no campaign rules match, should return None."""
    router = CampaignRouter(config_path=temp_campaign_config)
    # Campaign A requires has_website=False
    # Campaign B & C require has_website=True
    # Let's see: what if category is mismatch, etc.
    # In this fixture, Campaign C matches any has_website=True, so it always catches it.
    # Let's verify Campaign B rejects invalid SSL and falls to Campaign C
    matched = router.route_lead(
        category="Dentist",
        has_website=True,
        ssl_valid=False,  # fails Campaign B criteria
        load_time_seconds=1.0,
    )
    assert matched is not None
    assert matched["name"] == "Campaign C (Standard)"
