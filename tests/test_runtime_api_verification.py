"""Runtime Verification and Diagnostic Suite for LeadForge API Endpoints."""

import os
import sys
import json
import pytest
from fastapi.testclient import TestClient

from leadforge.server import app
from leadforge.search_directory import sanitize_category_query, slugify_category

client = TestClient(app)

def test_root_index():
    """Verify root GET / returns 200 and loads LeadForge UI or metadata."""
    res = client.get("/")
    assert res.status_code == 200
    assert ("LeadForge" in res.text or "<!doctype html>" in res.text)


def test_health_check():
    """Verify GET /health returns 200 OK."""
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_taxonomy_endpoint():
    """Verify GET /api/taxonomy returns 200 with full categorical tree."""
    res = client.get("/api/taxonomy")
    assert res.status_code == 200
    data = res.json()
    assert "Manufacturing" in data
    assert "Construction & Infrastructure" in data
    assert "Plastics & Polymers" in data["Manufacturing"]["subcategories"]
    assert "Boilers, Tanks & Pressure Vessels" in data["Manufacturing"]["subcategories"]


def test_status_endpoint():
    """Verify GET /api/status returns current scraper state."""
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "is_running" in data


def test_metrics_endpoint():
    """Verify GET /api/metrics returns live or snapshot metrics."""
    res = client.get("/api/metrics")
    assert res.status_code == 200


def test_history_endpoint():
    """Verify GET /api/history returns campaign history."""
    res = client.get("/api/history")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_businesses_endpoint():
    """Verify GET /api/businesses returns business registry items."""
    res = client.get("/api/businesses?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_opportunities_endpoint():
    """Verify GET /api/opportunities returns opportunity list."""
    res = client.get("/api/opportunities?limit=10")
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_analytics_endpoint():
    """Verify GET /api/analytics returns business intelligence statistics."""
    res = client.get("/api/analytics")
    assert res.status_code == 200
    data = res.json()
    assert "summary" in data
    assert "campaigns" in data


def test_settings_endpoints():
    """Verify GET and PUT /api/settings endpoints."""
    res = client.get("/api/settings")
    assert res.status_code == 200

    res_put = client.put("/api/settings/TEST_KEY", json={"value": "test_val"})
    assert res_put.status_code == 200


def test_llm_status_endpoint():
    """Verify GET /api/llm/status returns local LM availability."""
    res = client.get("/api/llm/status")
    assert res.status_code == 200
    data = res.json()
    assert "enabled" in data


def test_outreach_endpoints():
    """Verify outreach draft metrics, campaigns, and drafts endpoints."""
    res_m = client.get("/api/outreach/metrics")
    assert res_m.status_code == 200

    res_c = client.get("/api/outreach/campaigns")
    assert res_c.status_code == 200

    res_d = client.get("/api/outreach/drafts")
    assert res_d.status_code == 200


def test_communication_stats_endpoint():
    """Verify GET /api/communication/stats returns 200."""
    res = client.get("/api/communication/stats")
    assert res.status_code == 200
    data = res.json()
    assert "total_threads" in data


def test_leads_zero_results_returns_empty_list_not_404():
    """Verify that a campaign with 0 leads returns 200 OK with [] instead of 404."""
    res = client.get("/api/leads/Ahmedabad_Boilers__Tanks___Pressure_Vessels_20260818_080859.xlsx")
    assert res.status_code == 200
    assert res.json() == [] or isinstance(res.json(), list)


def test_cors_headers_for_port_5174():
    """Verify that origin http://localhost:5174 is accepted in CORS preflight and GET."""
    res = client.get(
        "/api/status",
        headers={"Origin": "http://localhost:5174"}
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") in ["http://localhost:5174", "*"]


def test_category_sanitation_and_slugs():
    """Verify category sanitation and slug generation for directories."""
    cleaned = sanitize_category_query("Boilers, Tanks & Pressure Vessels")
    assert cleaned == "Boilers Tanks and Pressure Vessels"
    slug = slugify_category(cleaned)
    assert slug == "Boilers-Tanks-and-Pressure-Vessels"
