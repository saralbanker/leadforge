"""Unit tests for Hierarchical Industry Taxonomy and Multi-Platform Control Plane integration."""

from leadforge.taxonomy import (
    get_taxonomy_tree,
    build_specialized_search_query,
    get_service_offerings_for_niche,
)
from leadforge.merge import BusinessMerger


def test_taxonomy_tree_structure():
    """Verify taxonomy tree contains all major sectors and deep manufacturing niches."""
    tree = get_taxonomy_tree()
    assert "Manufacturing" in tree
    assert "Construction & Infrastructure" in tree
    assert "Healthcare & Medical" in tree
    assert "Automotive & Logistics" in tree

    mfg_subcats = tree["Manufacturing"]["subcategories"]
    assert "Plastics & Polymers" in mfg_subcats
    assert "Boilers, Tanks & Pressure Vessels" in mfg_subcats
    assert "CNC Machining & Precision Tooling" in mfg_subcats
    assert "Chemicals, Dyes & Pigments" in mfg_subcats
    assert "Electrical, Transformers & Switchgears" in mfg_subcats
    assert "Metals, Forging & Foundry" in mfg_subcats


def test_specialized_query_builder():
    """Verify search queries combine niche keywords with partition city."""
    q1 = build_specialized_search_query("Manufacturing", "Boilers, Tanks & Pressure Vessels", "Ahmedabad")
    assert "Boilers" in q1 or "Pressure Vessels" in q1
    assert "Ahmedabad" in q1

    q2 = build_specialized_search_query("Manufacturing", "Plastics & Polymers", "Pune")
    assert "Plastics" in q2 or "Polymers" in q2
    assert "Pune" in q2


def test_service_offerings_lookup():
    """Verify relevant outbound agency pitch hooks are resolved from the taxonomy."""
    services = get_service_offerings_for_niche("Manufacturing", "Plastics & Polymers")
    assert "B2B Catalog Portal" in services
    assert "Website Design & Development" in services


def test_merge_with_phone_candidates():
    """Verify BusinessMerger correctly merges phone_candidates and updates primary phone when upgraded."""
    merger = BusinessMerger()
    existing_biz = {
        "id": "01912345-6789-7abc-def0-123456789abc",
        "name": "Mahalaxmi Boilers Pvt Ltd",
        "display_phone": "+917922801234",
        "phone_source": "google_maps",
        "primary_platform": "google_maps",
        "phone_candidates": '[{"phone": "+917922801234", "canonical": "7922801234", "phone_type": "LANDLINE", "source": "google_maps"}]',
        "website_domain": "oldwebsite.com",
        "address": "GIDC Vatva",
    }

    incoming_lead = {
        "name": "Mahalaxmi Boilers Pvt Ltd",
        "phone": "+919825014820",
        "phone_source": "indiamart",
        "primary_platform": "indiamart",
        "phone_candidates": [
            {"phone": "+919825014820", "canonical": "9825014820", "phone_type": "MOBILE", "source": "indiamart"},
            {"phone": "+917922801234", "canonical": "7922801234", "phone_type": "LANDLINE", "source": "google_maps"},
        ],
        "website_domain": "mahalaxmiboilers.com",
        "address": "Plot 42, Phase 1, GIDC Vatva, Ahmedabad",
    }

    updates, conflicts = merger.merge(existing_biz, incoming_lead)

    # Phone was upgraded from landline to mobile
    assert "display_phone" in updates
    assert updates["display_phone"] == "+919825014820"
    assert updates["phone_source"] == "indiamart"
    assert "phone_candidates" in updates
    assert "primary_platform" in updates
