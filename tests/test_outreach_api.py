import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

# Important: Override database path before importing any db modules to isolate test data
import leadforge.database

temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()
leadforge.database.DB_PATH = temp_db_path

from leadforge.database import initialize_database, get_db_connection  # noqa: E402
from leadforge.server import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown():
    # Bootstrap database
    initialize_database()
    yield
    # Cleanup temp db
    if temp_db_path.exists():
        try:
            os.remove(temp_db_path)
        except Exception:
            pass


def test_list_campaigns():
    """Verify GET /api/outreach/campaigns lists routing configs."""
    response = client.get("/api/outreach/campaigns")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    # Since we have campaign_routing.yaml in the root, it should load some campaigns
    assert len(data) > 0
    assert "name" in data[0]


@patch("leadforge.outreach.discovery.WebsiteAuditor.audit_website")
@patch("leadforge.outreach.generator.OllamaHookGenerator.generate_hook")
def test_drafts_generation_and_approval_workflow(mock_hook: MagicMock, mock_audit: MagicMock):
    """Verify generate draft, approve, reject, list, and deliver loop."""
    # 1. Setup mock responses
    mock_audit.return_value = {
        "has_website": True,
        "ssl_valid": True,
        "load_time_seconds": 1.2,
        "viewport_mobile": True,
        "cms": "WordPress",
        "has_booking": False,
        "discovered_emails": ["contact@testbusiness.com"],
        "cleaned_text": "Sample crawled homepage text.",
    }
    mock_hook.return_value = "I saw your website and liked the WP design."

    # 2. Seed database records
    conn = get_db_connection()
    cursor = conn.cursor()

    business_id = "01907de3-bc42-7c89-8d76-5a507db4f555"
    opp_id = "01907de3-bc42-7c89-8d76-5a507db4f666"
    bt_id = "01907de3-bc42-7c89-8d76-5a507db4f777"
    addr_id = "01907de3-bc42-7c89-8d76-5a507db4f888"

    cursor.execute("INSERT OR IGNORE INTO business_types (id, name) VALUES (?, ?);", (bt_id, "Dentists"))
    cursor.execute(
        """
        INSERT OR IGNORE INTO businesses (id, normalized_name, name, website_domain, business_type_id)
        VALUES (?, ?, ?, ?, ?);
        """,
        (business_id, "test business", "Test Business", "testbusiness.com", bt_id)
    )
    cursor.execute(
        """
        INSERT OR IGNORE INTO addresses (id, business_id, address_line, area, city, state, postal_code)
        VALUES (?, ?, '123 Main St', 'Naroda', 'Ahmedabad', 'Gujarat', '380001');
        """,
        (addr_id, business_id)
    )
    cursor.execute(
        """
        INSERT OR IGNORE INTO opportunities (id, business_id, title, pipeline_stage, score)
        VALUES (?, ?, 'Web Site Opportunity', 'PROSPECTING', 80);
        """,
        (opp_id, business_id)
    )
    conn.commit()
    conn.close()

    # 3. Generate Draft (POST /api/outreach/drafts/generate)
    response = client.post(
        "/api/outreach/drafts/generate",
        json={"opportunity_id": opp_id, "force_regenerate": False}
    )
    assert response.status_code == 200
    draft = response.json()
    assert draft["opportunity_id"] == opp_id
    assert draft["status"] == "PENDING_APPROVAL"
    assert draft["recipient_email"] == "contact@testbusiness.com"
    assert "WP design" in draft["body"]
    draft_id = draft["id"]

    # 4. List Drafts (GET /api/outreach/drafts)
    response = client.get("/api/outreach/drafts")
    assert response.status_code == 200
    drafts = response.json()
    assert len(drafts) > 0
    assert drafts[0]["id"] == draft_id
    assert drafts[0]["business_name"] == "Test Business"
    assert drafts[0]["opportunity_score"] == 80

    # 5. Approve Draft (POST /api/outreach/drafts/{id}/approve)
    response = client.post(f"/api/outreach/drafts/{draft_id}/approve")
    assert response.status_code == 200
    assert response.json()["message"] == "Draft approved successfully."

    # Verify status changed in list
    response = client.get("/api/outreach/drafts?status=APPROVED")
    assert response.status_code == 200
    assert len(response.json()) == 1
    assert response.json()[0]["id"] == draft_id

    # 6. Reject Draft (POST /api/outreach/drafts/{id}/reject)
    response = client.post(f"/api/outreach/drafts/{draft_id}/reject")
    assert response.status_code == 200
    assert response.json()["message"] == "Draft rejected."

    # Verify status changed to REJECTED/rejected in db
    response = client.get("/api/outreach/drafts")
    assert response.status_code == 200
    assert response.json()[0]["status"] == "REJECTED"


@patch("leadforge.outreach.deliverer.SMTPEmailDeliverer.send_approved_drafts")
def test_outreach_deliver(mock_deliver: MagicMock):
    """Verify POST /api/outreach/deliver triggers delivery task in background."""
    mock_deliver.return_value = 1
    response = client.post("/api/outreach/deliver")
    assert response.status_code == 200
    assert "SMTP delivery task started" in response.json()["message"]
