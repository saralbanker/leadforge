import os
import tempfile
import pytest
from pathlib import Path

# Important: Override database path before importing any db modules to isolate test data
import leadforge.database

temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()
from leadforge.database import initialize_database, get_db_connection  # noqa: E402
from leadforge.outreach.discovery import (  # noqa: E402
    extract_emails_from_text,
    is_duplicate_outreach,
)


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown():
    mp = pytest.MonkeyPatch()
    mp.setattr(leadforge.database, "DB_PATH", temp_db_path)
    # Bootstrap database
    initialize_database()
    yield
    mp.undo()
    # Cleanup temp db
    if temp_db_path.exists():
        try:
            os.remove(temp_db_path)
        except Exception:
            pass


def test_extract_emails_from_text():
    """Verify that regex extracts unique valid emails and filters generic/image extensions."""
    sample_text = (
        "Contact us at office@starbuilders.in or support@starbuilders.in. "
        "Do not write to sentry@example.com (generic) or logo@company.com.png (image extension)."
    )
    emails = extract_emails_from_text(sample_text)
    assert "support@starbuilders.in" in emails
    assert "office@starbuilders.in" in emails
    assert "sentry@example.com" not in emails  # filtered generic
    assert "logo@company.com.png" not in emails  # filtered extension


def test_is_duplicate_outreach_flow():
    """Verify database-backed deduplication gates (by business ID, email, or domain)."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create dummy records matching 36-character length constraints
    business_id = "01907de3-bc42-7c89-8d76-5a507db4f777"
    opp_id = "01907de3-bc42-7c89-8d76-5a507db4f888"
    bt_id = "01907de3-bc42-7c89-8d76-5a507db4f999"

    # Insert dummy business type (respecting length=36 constraint)
    cursor.execute(
        "INSERT OR IGNORE INTO business_types (id, name) VALUES (?, ?);",
        (bt_id, "Dentist")
    )

    # Insert business
    cursor.execute(
        """
        INSERT OR IGNORE INTO businesses (id, normalized_name, name, website_domain, business_type_id)
        VALUES (?, ?, ?, ?, ?);
        """,
        (business_id, "star builders", "Star Builders", "starbuilders.in", bt_id)
    )

    # Insert opportunity
    cursor.execute(
        """
        INSERT OR IGNORE INTO opportunities (id, business_id, title, pipeline_stage)
        VALUES (?, ?, ?, 'PROSPECTING');
        """,
        (opp_id, business_id, "Web Design Opportunity")
    )

    # Confirm there is no duplicate outreach initially
    assert not is_duplicate_outreach(business_id, email="info@starbuilders.in", domain="starbuilders.in")

    # Insert draft to simulate outreach
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status)
        VALUES (?, ?, ?, ?, ?, ?, 'PENDING_APPROVAL');
        """,
        (
            "01907de3-bc42-7c89-8d76-5a507db4faaa",
            opp_id,
            "test_campaign.xlsx",
            "info@starbuilders.in",
            "test subject",
            "test body",
        )
    )
    conn.commit()
    conn.close()

    # Now verify duplication checks catch it
    assert is_duplicate_outreach(business_id)  # Tier 1 match (business_id)
    assert is_duplicate_outreach("01907de3-bc42-7c89-8d76-5a507db4fbbb", email="info@starbuilders.in")  # Tier 2 match
    assert is_duplicate_outreach("01907de3-bc42-7c89-8d76-5a507db4fbbb", domain="starbuilders.in")  # Tier 3 match
    assert not is_duplicate_outreach("01907de3-bc42-7c89-8d76-5a507db4fbbb", email="clean@starbuilders.in", domain="clean.com")
