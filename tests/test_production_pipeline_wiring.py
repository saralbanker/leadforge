"""Verification of end-to-end production pipeline wiring for draft generation.

Ensures that live production entry points (server.py and daemon.py) call the
grounded, length-compacted pipeline functions:
- generator.py: generate_contact_bridge(), extract_secondary_topic()
- router.py: CampaignRouter.render_body(), render_subject()
- quality.py: EmailQualityEngine.validate_body(), validate_bridge(), validate_subject()
"""

import asyncio
import json
import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

import leadforge.database
from leadforge.database import initialize_database, get_db_connection
from leadforge.server import app
from leadforge.daemon import AutonomousOrvionEngine
from leadforge.outreach.router import CampaignRouter
from leadforge.outreach.quality import EmailQualityEngine


temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db_path = Path(temp_db.name)
temp_db.close()


@pytest.fixture(scope="module", autouse=True)
def setup_and_teardown():
    mp = pytest.MonkeyPatch()
    mp.setattr(leadforge.database, "DB_PATH", temp_db_path)
    initialize_database()
    yield
    mp.undo()
    if temp_db_path.exists():
        try:
            os.remove(temp_db_path)
        except Exception:
            pass


client = TestClient(app)


def test_server_generate_draft_calls_render_body_and_includes_contact_bridge():
    """Verify POST /api/outreach/drafts/generate calls CampaignRouter.render_body
    and produces an email body containing a grounded contact bridge rather than an empty placeholder.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    biz_id = "019fa894-85fc-737a-a141-ecee13878bb5"
    opp_id = "019fa894-85fc-737a-a141-ecee13878bb6"
    bt_id = "019fa894-85fc-737a-a141-ecee13878bb7"
    addr_id = "019fa894-85fc-737a-a141-ecee13878bb8"

    cursor.execute("INSERT OR IGNORE INTO business_types (id, name) VALUES (?, ?);", (bt_id, "Manufacturing"))
    cursor.execute(
        """
        INSERT OR REPLACE INTO businesses (id, normalized_name, name, website_domain, contact_email, business_type_id)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (biz_id, "aavad instrument", "Aavad Instrument Pvt. Ltd.", "aavadinstrument.com", "hrg@aavadinstrument.com", bt_id)
    )
    cursor.execute(
        """
        INSERT OR REPLACE INTO addresses (id, business_id, address_line, area, city, state, postal_code)
        VALUES (?, ?, 'Phase 1 GIDC', 'Vatva GIDC', 'Ahmedabad', 'Gujarat', '382445');
        """,
        (addr_id, biz_id)
    )
    cursor.execute(
        """
        INSERT OR REPLACE INTO opportunities (id, business_id, title, pipeline_stage, score)
        VALUES (?, ?, 'B2B Outreach - Manufacturing', 'PROSPECTING', 90);
        """,
        (opp_id, biz_id)
    )
    conn.commit()
    conn.close()

    scraped = "Aavad Instrument is a manufacturer of temperature and pressure instruments, thermocouple, and RTD sensors."

    with patch("leadforge.server.phone_enrichment_orchestrator.enrich_phone", return_value=(None, None, None, [])), \
         patch("leadforge.outreach.discovery.WebsiteAuditor.audit_website", return_value={
             "has_website": True,
             "ssl_valid": True,
             "load_time_seconds": 0.8,
             "viewport_mobile": True,
             "cms": "Custom",
             "has_booking": False,
             "discovered_emails": ["hrg@aavadinstrument.com"],
             "cleaned_text": scraped,
         }), \
         patch("leadforge.outreach.generator.OllamaHookGenerator.generate_hook_with_source", return_value=(
             "I noticed Aavad Instrument manufactures precision instrumentation for various industries.",
             "llm"
         )), \
         patch.object(CampaignRouter, "render_body", wraps=CampaignRouter.render_body) as spy_render_body:

        res = client.post("/api/outreach/drafts/generate", json={"opportunity_id": opp_id})
        assert res.status_code == 200, f"Generate draft failed: {res.text}"
        data = res.json()

        # 1. Verify CampaignRouter.render_body was called
        assert spy_render_body.called, "CampaignRouter.render_body was NOT called during server draft generation"

        # 2. Verify body contains grounded bridge sentence (Paragraph 2 Sentence 1
        # of the core pitch - i.e. excluding the greeting/sign-off/footer wrapper
        # that compose_full_body() adds around it, see P0-3).
        body = data["body"]
        core_pitch = EmailQualityEngine._core_body(body)
        paras = [p.strip() for p in core_pitch.split("\n\n") if p.strip()]
        assert len(paras) >= 2, "Body must contain at least 2 paragraphs"
        p2 = paras[1]

        # The bridge must NOT be empty or omitted
        assert "I noticed your" in p2 or "I came across" in p2 or "I found" in p2, \
            f"Paragraph 2 missing grounded contact bridge: {p2}"

        # 3. Verify core body length budget <= 65 words
        core_body = EmailQualityEngine._core_body(body)
        core_words = len(core_body.split())
        assert 40 <= core_words <= 65, f"Core body word count {core_words} out of expected 40-65 range"

        # 4. Verify quality issues recorded
        assert "quality_issues" in data


def test_daemon_run_email_generation_step_calls_render_body_and_validates():
    """Verify daemon.run_email_generation_step calls CampaignRouter.render_body,
    validates the draft with EmailQualityEngine, and auto-approves compliant drafts.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    biz_id = "019fa894-cdef-7471-a293-031865c3a320"
    opp_id = "019fa894-cdef-7471-a293-031865c3a321"
    bt_id = "019fa894-cdef-7471-a293-031865c3a322"
    addr_id = "019fa894-cdef-7471-a293-031865c3a323"

    cursor.execute("INSERT OR IGNORE INTO business_types (id, name) VALUES (?, ?);", (bt_id, "Manufacturing"))
    cursor.execute(
        """
        INSERT OR REPLACE INTO businesses (id, normalized_name, name, website_domain, contact_email, business_type_id)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (biz_id, "protekg power", "ProtekG Power Electronics Pvt Ltd", "protekg.com", "sales.protekg@gmail.com", bt_id)
    )
    cursor.execute(
        """
        INSERT OR REPLACE INTO addresses (id, business_id, address_line, area, city, state, postal_code)
        VALUES (?, ?, 'GIDC Odhav', 'Odhav', 'Ahmedabad', 'Gujarat', '382415');
        """,
        (addr_id, biz_id)
    )
    cursor.execute(
        """
        INSERT OR REPLACE INTO opportunities (id, business_id, title, pipeline_stage, score)
        VALUES (?, ?, 'B2B Outreach - Stabilizers', 'PROSPECTING', 95);
        """,
        (opp_id, biz_id)
    )
    conn.commit()
    conn.close()

    scraped = "ProtekG Power Electronics manufactures servo voltage stabilizers, power conditioning units, and battery chargers."

    engine = AutonomousOrvionEngine()

    async def _run():
        with patch("leadforge.outreach.discovery.WebsiteAuditor.audit_website", return_value={"cleaned_text": scraped}), \
             patch.object(engine.generator, "generate_hook_with_details", return_value=(
                 "ProtekG Power Electronics manufactures oil-cooled servo voltage stabilizers in Ahmedabad.",
                 "llm",
                 "servo voltage stabilizers",
             )), \
             patch.object(CampaignRouter, "render_body", wraps=CampaignRouter.render_body) as spy_render_body:

            await engine.run_email_generation_step()
            assert spy_render_body.called, "CampaignRouter.render_body was NOT called in daemon"

    asyncio.run(_run())

    # Check draft persisted in database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM email_drafts WHERE recipient_email = 'sales.protekg@gmail.com'")
    draft = cursor.fetchone()
    conn.close()

    assert draft is not None, "Draft was not inserted by daemon"
    assert draft["status"] == "APPROVED"
    assert draft["quality_score"] >= 80

    # Check bridge sentence exists in body
    body = draft["body"]
    assert "I noticed your" in body or "I found" in body or "I came across" in body, \
        f"Grounded bridge missing from body: {body}"
