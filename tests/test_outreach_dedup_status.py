"""Deduplication must key on outreach that actually happened, not on any row.

A CANCELLED or REJECTED draft never reached the recipient. Counting it as a
duplicate permanently locks that business out of the pipeline, which is what
happened to the leads whose drafts were cancelled after the fabricated-address
incident.
"""

import uuid

import pytest

from leadforge.database import get_db_connection, initialize_database
from leadforge.outreach.discovery import is_duplicate_outreach


@pytest.fixture(autouse=True)
def setup_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test_dedup_status.db"
    monkeypatch.setattr("leadforge.database.DB_PATH", db_path)
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db_path))
    initialize_database()


def _seed(status: str) -> tuple[str, str]:
    """Creates a business, opportunity and one draft in the given status."""
    biz_id, opp_id, draft_id = (str(uuid.uuid4()) for _ in range(3))
    email = "owner@example.com"
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO businesses (id, normalized_name, name, website_domain) VALUES (?,?,?,?)",
        (biz_id, "acme", "Acme", "acme.example"),
    )
    conn.execute(
        "INSERT INTO opportunities (id, business_id, title, pipeline_stage) VALUES (?,?,?,?)",
        (opp_id, biz_id, "Website", "PROSPECTING"),
    )
    conn.execute(
        "INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, "
        "subject, body, status) VALUES (?,?,?,?,?,?,?)",
        (draft_id, opp_id, "Test", email, "s", "b", status),
    )
    conn.commit()
    conn.close()
    return biz_id, email


@pytest.mark.parametrize("status", ["PENDING_APPROVAL", "APPROVED", "QUEUED", "SENT", "FAILED"])
def test_live_drafts_block_a_second_draft(status):
    biz_id, email = _seed(status)
    assert is_duplicate_outreach(biz_id, email=email, domain="acme.example") is True


@pytest.mark.parametrize("status", ["CANCELLED", "REJECTED"])
def test_cancelled_and_rejected_drafts_do_not_block(status):
    """These never reached anyone, so the business stays eligible."""
    biz_id, email = _seed(status)
    assert is_duplicate_outreach(biz_id, email=email, domain="acme.example") is False


def test_each_tier_independently_ignores_dead_drafts():
    biz_id, email = _seed("CANCELLED")
    assert is_duplicate_outreach(biz_id) is False                      # tier 1: business
    assert is_duplicate_outreach(str(uuid.uuid4()), email=email) is False   # tier 2: address
    assert is_duplicate_outreach(str(uuid.uuid4()), domain="acme.example") is False  # tier 3: domain
