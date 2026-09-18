"""The quality verdict and hook provenance must be persisted and enforced.

Both were previously computed and discarded: the quality score went into the
HTTP response only, and a fallback hook (used whenever Ollama was unreachable)
was indistinguishable from real model output. Bulk approval — the automation
path — therefore approved anything.
"""

import json
import sqlite3

import pytest

from leadforge.outreach.generator import (
    DEFAULT_SYSTEM_PROMPT,
    OllamaHookGenerator,
    banned_vocabulary,
    resolve_system_prompt,
)
from leadforge.outreach.quality import EmailQualityEngine


# --------------------------------------------------------------------------
# Prompt and quality gate agree
# --------------------------------------------------------------------------

def test_every_banned_term_reaches_the_prompt():
    """The prompt named 2 of 23 banned terms; the model used the other 21."""
    resolved = resolve_system_prompt(DEFAULT_SYSTEM_PROMPT).lower()
    banned = EmailQualityEngine.AI_JARGON_PHRASES | EmailQualityEngine.SPAM_KEYWORDS
    missing = [t for t in banned if t.lower() not in resolved]
    assert missing == [], f"banned terms absent from the system prompt: {missing}"


def test_banned_vocabulary_tracks_the_quality_engine(monkeypatch):
    """Adding a term to the gate must add it to the prompt, with no second edit."""
    monkeypatch.setattr(
        EmailQualityEngine, "AI_JARGON_PHRASES",
        EmailQualityEngine.AI_JARGON_PHRASES | {"synergize"},
    )
    assert "synergize" in banned_vocabulary()


def test_a_custom_prompt_keeps_its_own_wording():
    """The operator's prompt must survive intact — the guard is appended, not merged."""
    custom = "Write one sentence. Output JSON."
    out = resolve_system_prompt(custom)
    assert out.startswith(custom)
    assert "streamline" in out


# --------------------------------------------------------------------------
# Hook provenance
# --------------------------------------------------------------------------

def test_unreachable_model_reports_fallback(monkeypatch):
    gen = OllamaHookGenerator(api_url="http://127.0.0.1:9")  # nothing listening

    def unreachable(*a, **k):
        raise __import__("requests").exceptions.ConnectionError("refused")

    monkeypatch.setattr("leadforge.outreach.generator.requests.post", unreachable)
    hook, source = gen.generate_hook_with_source(
        business_name="Acme Steel", review_count=0, rating=0.0,
        city="Ahmedabad", scraped_text="", category="Steel", area="Vatva",
    )
    assert source == "fallback"
    assert "Acme Steel" in hook


def test_disabled_model_reports_fallback():
    class _Off:
        def get_str(self, k, d=""):
            return "false" if k == "llm.enabled" else d

        def get_int(self, k, d=0):
            return d

        def get_float(self, k, d=0.0):
            return d

    hook, source = OllamaHookGenerator(settings_getter=_Off()).generate_hook_with_source(
        business_name="Acme Steel", review_count=0, rating=0.0,
        city="Ahmedabad", scraped_text="", category="Steel", area="Vatva",
    )
    assert source == "fallback"


def test_successful_generation_reports_llm(monkeypatch):
    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"response": '{"observation_hook": "A real generated line."}'}

    monkeypatch.setattr("leadforge.outreach.generator.requests.post", lambda *a, **k: _Resp())
    hook, source = OllamaHookGenerator(api_url="http://x").generate_hook_with_source(
        business_name="Acme Steel", review_count=0, rating=0.0,
        city="Ahmedabad", scraped_text="", category="Steel", area="Vatva",
    )
    assert source == "llm"
    assert hook == "A real generated line."


# --------------------------------------------------------------------------
# Bulk approval enforcement
# --------------------------------------------------------------------------

MIN_SCORE = 80


def _gate(score, hook_source, issues=None, require_llm=True, min_score=MIN_SCORE):
    """Mirrors the decision made by bulk_approve_drafts for one draft."""
    if score is None:
        return "no quality score recorded — regenerate this draft before approving"
    if score < min_score:
        reason = f"quality score {score} is below the minimum of {min_score}"
        if issues:
            reason += f" ({'; '.join(issues)})"
        return reason
    if require_llm and hook_source == "fallback":
        return "the opening line is the deterministic fallback, not model output"
    return None


@pytest.mark.parametrize("score,source,blocked", [
    (100, "llm", False),
    (80, "llm", False),
    (79, "llm", True),
    (0, "llm", True),
    (100, "fallback", True),
    (None, "llm", True),
])
def test_bulk_approval_decision(score, source, blocked):
    assert (_gate(score, source, issues=["x"]) is not None) is blocked


def test_fallback_is_admissible_when_the_operator_opts_in():
    assert _gate(100, "fallback", require_llm=False) is None


def test_blocked_reason_names_the_quality_issues():
    reason = _gate(60, "llm", issues=["Spam indicators detected: ['free']"])
    assert "60" in reason and "free" in reason


# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

def test_migration_adds_the_columns_and_settings(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    monkeypatch.setenv("LEADFORGE_SKIP_BOOTSTRAP", "1")

    # get_db_connection() prefers LEADFORGE_DB_PATH over the DB_PATH global, and
    # other tests leave it set — patching DB_PATH alone would target their DB.
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db))

    import leadforge.database as database
    monkeypatch.setattr(database, "DB_PATH", db)
    database.initialize_database()

    conn = sqlite3.connect(db)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(email_drafts)")}
    assert {"quality_score", "quality_passed", "quality_issues", "hook_source"} <= cols

    keys = {r[0] for r in conn.execute("SELECT key FROM settings")}
    assert "outreach.min_quality_score" in keys
    assert "outreach.require_llm_hook" in keys
    conn.close()


def test_quality_issues_round_trip_as_json():
    issues = ["Spam indicators detected: ['free']", "Contains link or URL in body text."]
    assert json.loads(json.dumps(issues)) == issues


# --------------------------------------------------------------------------
# Business-name cleaning
# --------------------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("Noble Brothers | Tarpaulin Manufacturer in Ahmedabad", "Noble Brothers"),
    ("Allied Valves (Knife Edge Gate Valve|Ball Valve)", "Allied Valves"),
    ("DWARKESH INDUSTRIES |Cassia Tora Seeds | Splits", "DWARKESH INDUSTRIES"),
    ("Krish Plastic Industries - Engineering Plastic Manufacturer", "Krish Plastic Industries"),
    # Already clean — must pass through untouched.
    ("Anar Rub Tech Private Limited", "Anar Rub Tech Private Limited"),
    ("Mazda Limited", "Mazda Limited"),
])
def test_clean_business_name(raw, expected):
    from leadforge.normalizer import clean_business_name
    assert clean_business_name(raw) == expected


def test_clean_business_name_strips_invisible_characters():
    from leadforge.normalizer import clean_business_name
    assert "​" not in clean_business_name("ADORN AESTHETICS​ - Best Hair Transplant")


def test_clean_business_name_never_ends_on_a_conjunction():
    from leadforge.normalizer import clean_business_name
    out = clean_business_name(
        "Elite Plastic Surgery Clinic & Multispeciality - Plastic Surgeon in Ahmedabad"
    )
    assert not out.rstrip().endswith(("&", "and", "-", ","))


def test_clean_business_name_caps_length():
    from leadforge.normalizer import clean_business_name
    assert len(clean_business_name("A" * 200)) <= 42


@pytest.mark.parametrize("blank", ["", None])
def test_clean_business_name_handles_blank(blank):
    from leadforge.normalizer import clean_business_name
    assert clean_business_name(blank) == ""


# --------------------------------------------------------------------------
# Repetition detection
# --------------------------------------------------------------------------

CLONES = [
    "Aavad Instrument still takes orders over phone, so mistakes must slip through.",
    "Allied Valves still takes orders over phone, so mistakes must slip through.",
    "Anar Rub Tech still takes orders over a contact form, so mistakes must slip through.",
]

VARIED = [
    "Aavad Instrument has no dealer login, so repeat buyers must call in.",
    "Your Odhav unit shows 27 reviews but no product spec sheets online.",
    "Rajsagar lists 40 pipe grades on paper but none are searchable.",
]


def test_a_cloned_opening_is_blocked():
    result = EmailQualityEngine.score_draft(CLONES[1], previous_bodies=[CLONES[0]])
    assert result["passed"] is False
    assert any("identical to a recent draft" in i for i in result["issues"])


def test_the_first_draft_has_nothing_to_repeat():
    assert EmailQualityEngine.score_draft(CLONES[0], previous_bodies=[])["passed"] is True


def test_distinct_openings_all_pass():
    seen = []
    for hook in VARIED:
        assert EmailQualityEngine.score_draft(hook, previous_bodies=seen)["passed"] is True
        seen.append(hook)


def test_repetition_is_detected_despite_differing_business_names():
    """The name legitimately varies and can dominate a whole-string compare."""
    a = "X Ltd still takes orders over phone, so mistakes must slip through."
    b = ("A Very Much Longer Business Name Private Limited still takes orders "
         "over phone, so mistakes must slip through.")
    assert EmailQualityEngine.find_similar(b, [a]) is not None


def test_repetition_costs_more_than_a_single_style_issue():
    """Repetition scales across a batch, so it outweighs one cliché."""
    style_only = EmailQualityEngine.score_draft("We streamline your workflow today.")
    repeated = EmailQualityEngine.score_draft(CLONES[1], previous_bodies=[CLONES[0]])
    assert repeated["quality_score"] < style_only["quality_score"]


def test_scoring_without_history_is_unchanged():
    """Existing callers that pass no history keep their previous behaviour."""
    assert EmailQualityEngine.score_draft(VARIED[0])["quality_score"] == 100


def test_cloned_whole_body_with_distinct_openings_is_blocked():
    """Four drafts sharing the same middle+closing but with unique hooks must be caught."""
    body_a = (
        "I noticed Apex Precision has 45 Google reviews in Denver.\n\n"
        "We build private order portals for manufacturers and distributors in Denver "
        "to cut down the back-and-forth on repeat wholesale orders.\n\n"
        "How do your dealers and distributors usually send over their repeat orders?"
    )
    body_b = (
        "I saw Acme Steel exports parts to 12 countries from Austin.\n\n"
        "We build private order portals for manufacturers and distributors in Austin "
        "to cut down the back-and-forth on repeat wholesale orders.\n\n"
        "How do your dealers and distributors usually send over their repeat orders?"
    )
    result = EmailQualityEngine.score_draft(body_b, previous_bodies=[body_a])
    assert result["passed"] is False
    assert result["quality_score"] <= 60
    assert any("Email body is" in i for i in result["issues"])


def test_slot_varied_bodies_all_pass_repetition_check():
    """Drafts composed with varied slot combinations pass repetition checks clean."""
    b1 = (
        "I noticed Apex Precision has 45 Google reviews in Denver.\n\n"
        "Taking dealer orders over WhatsApp or phone means part numbers get mixed up and staff spend hours re-typing quantities into the accounts system. We set up simple dealer order portals for manufacturers in Denver.\n\n"
        "Do your distributors call in their repeat orders right now?"
    )
    b2 = (
        "I saw Acme Steel exports parts to 12 countries from Austin.\n\n"
        "When distributors place repeat orders by message, manual entry often causes wrong quantities or delayed dispatches. We build dedicated order portals where dealers log in and submit purchase orders directly.\n\n"
        "How much time does your team spend typing up dealer orders each day?"
    )
    b3 = (
        "Found your manufacturing listing in Chicago.\n\n"
        "Handling distributor orders manually takes up hours of desk time every week and creates dispatch errors. We build clean dealer portals where your distributors place orders against your actual catalog.\n\n"
        "Would a simple order portal for your distributors be worth a quick look?"
    )
    seen = []
    for b in [b1, b2, b3]:
        res = EmailQualityEngine.score_draft(b, previous_bodies=seen)
        assert res["passed"] is True
        assert res["quality_score"] == 100
        seen.append(b)


def test_bulk_approve_holds_back_batch_internal_duplicates(tmp_path, monkeypatch):
    """Bulk approval must hold back drafts whose bodies closely match another draft in the SAME batch."""
    import asyncio
    import uuid
    db = tmp_path / "batch.db"
    monkeypatch.setenv("LEADFORGE_SKIP_BOOTSTRAP", "1")
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db))

    import leadforge.database as database
    monkeypatch.setattr(database, "DB_PATH", db)
    database.initialize_database()

    b1_id, b2_id = str(uuid.uuid4()), str(uuid.uuid4())
    o1_id, o2_id = str(uuid.uuid4()), str(uuid.uuid4())
    d1_id, d2_id = str(uuid.uuid4()), str(uuid.uuid4())

    body_1 = (
        "I noticed Apex Precision in Denver.\n\n"
        "We build private order portals for manufacturers and distributors in Denver to cut down repeat order friction.\n\n"
        "How do your dealers usually send over repeat orders?"
    )
    body_2 = (
        "I saw Acme Steel in Austin.\n\n"
        "We build private order portals for manufacturers and distributors in Austin to cut down repeat order friction.\n\n"
        "How do your dealers usually send over repeat orders?"
    )

    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO businesses (id, normalized_name, name) VALUES (?, 'b1', 'Apex Precision'), (?, 'b2', 'Acme Steel')", (b1_id, b2_id))
    cursor.execute("INSERT INTO opportunities (id, business_id, title, pipeline_stage) VALUES (?, ?, 'Opp 1', 'PROSPECTING'), (?, ?, 'Opp 2', 'PROSPECTING')", (o1_id, b1_id, o2_id, b2_id))
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status, quality_score, quality_passed, hook_source)
        VALUES (?, ?, 'Camp', 'a@apex.com', 'Subj 1', ?, 'PENDING_APPROVAL', 100, 1, 'llm'),
               (?, ?, 'Camp', 'b@acme.com', 'Subj 2', ?, 'PENDING_APPROVAL', 100, 1, 'llm')
        """,
        (d1_id, o1_id, body_1, d2_id, o2_id, body_2),
    )
    conn.commit()
    conn.close()

    from leadforge.server import bulk_approve_drafts
    res = asyncio.run(bulk_approve_drafts())

    assert res["approved_count"] == 1
    assert res["skipped_count"] == 1
    assert res["skipped"][0]["draft_id"] == d2_id
    assert "identical to another draft in this batch" in res["skipped"][0]["reason"]

    # Verify d2 is still PENDING_APPROVAL and regenerable
    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT id, status FROM email_drafts ORDER BY id")
    statuses = dict(cursor.fetchall())
    conn.close()

    assert statuses[d1_id] == "APPROVED"
    assert statuses[d2_id] == "PENDING_APPROVAL"


def test_bulk_approve_passes_genuinely_varied_batch(tmp_path, monkeypatch):
    """Genuinely varied drafts in a batch all pass bulk approval clean."""
    import asyncio
    import uuid
    db = tmp_path / "batch_clean.db"
    monkeypatch.setenv("LEADFORGE_SKIP_BOOTSTRAP", "1")
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db))

    import leadforge.database as database
    monkeypatch.setattr(database, "DB_PATH", db)
    database.initialize_database()

    b1_id, b2_id = str(uuid.uuid4()), str(uuid.uuid4())
    o1_id, o2_id = str(uuid.uuid4()), str(uuid.uuid4())
    d1_id, d2_id = str(uuid.uuid4()), str(uuid.uuid4())

    b1 = (
        "I noticed Apex Precision in Denver.\n\n"
        "Taking dealer orders over WhatsApp or phone means part numbers get mixed up. We set up simple dealer order portals.\n\n"
        "Do your distributors call in their repeat orders right now?"
    )
    b2 = (
        "I saw Acme Steel in Austin.\n\n"
        "When distributors place repeat orders by message, manual entry often causes wrong quantities. We build dedicated order portals.\n\n"
        "How much time does your team spend typing up dealer orders each day?"
    )

    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO businesses (id, normalized_name, name) VALUES (?, 'b1', 'Apex Precision'), (?, 'b2', 'Acme Steel')", (b1_id, b2_id))
    cursor.execute("INSERT INTO opportunities (id, business_id, title, pipeline_stage) VALUES (?, ?, 'Opp 1', 'PROSPECTING'), (?, ?, 'Opp 2', 'PROSPECTING')", (o1_id, b1_id, o2_id, b2_id))
    cursor.execute(
        """
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email, subject, body, status, quality_score, quality_passed, hook_source)
        VALUES (?, ?, 'Camp', 'a@apex.com', 'Subj 1', ?, 'PENDING_APPROVAL', 100, 1, 'llm'),
               (?, ?, 'Camp', 'b@acme.com', 'Subj 2', ?, 'PENDING_APPROVAL', 100, 1, 'llm')
        """,
        (d1_id, o1_id, b1, d2_id, o2_id, b2),
    )
    conn.commit()
    conn.close()

    from leadforge.server import bulk_approve_drafts
    res = asyncio.run(bulk_approve_drafts())

    assert res["approved_count"] == 2
    assert res["skipped_count"] == 0


# --------------------------------------------------------------------------
# Exemplars require evidence
# --------------------------------------------------------------------------

def test_a_sent_draft_without_a_reply_is_not_an_exemplar(tmp_path, monkeypatch):
    """Selecting on APPROVED/SENT taught the model from two bounced emails.

    A draft reaching SENT means someone clicked approve, not that the copy
    worked. Only an inbound reply proves a human read it.
    """
    db = tmp_path / "ex.db"
    monkeypatch.setenv("LEADFORGE_SKIP_BOOTSTRAP", "1")
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db))

    import leadforge.database as database
    monkeypatch.setattr(database, "DB_PATH", db)
    database.initialize_database()

    conn = sqlite3.connect(db)
    conn.executescript("""
        INSERT INTO businesses (id, normalized_name, name)
        VALUES ('b0000000-0000-4000-8000-000000000001', 'acme', 'Acme Steel');
        INSERT INTO opportunities (id, business_id, title, pipeline_stage)
        VALUES ('o0000000-0000-4000-8000-000000000001',
                'b0000000-0000-4000-8000-000000000001', 'Acme', 'PROSPECTING');
        INSERT INTO email_drafts (id, opportunity_id, campaign_name, recipient_email,
                                  subject, body, status)
        VALUES ('d0000000-0000-4000-8000-000000000001',
                'o0000000-0000-4000-8000-000000000001', 'C', 'a@acme.in',
                'subj', 'Acme Steel has no website, so buyers cannot find you.', 'SENT');
    """)
    conn.commit()
    conn.close()

    assert OllamaHookGenerator.get_approved_exemplars(limit=5) == [], (
        "a SENT draft with no inbound reply must not be used as an exemplar"
    )


def test_exemplars_are_empty_when_nothing_has_earned_a_reply():
    """With no replies recorded, the model writes from the prompt alone."""
    assert OllamaHookGenerator.get_approved_exemplars(limit=5) == []


def test_banned_list_is_appended_to_a_custom_prompt():
    """A custom prompt has no placeholder, and previously lost the guard."""
    out = resolve_system_prompt("You write cold emails. One sentence only.")
    assert "streamline" in out and "leverage" in out


def test_migration_025_persists_prompt_and_retry_setting(tmp_path, monkeypatch):
    """Migration 025 must persist strengthened evidence-priority prompt and hook_max_retries."""
    db = tmp_path / "m025.db"
    monkeypatch.setenv("LEADFORGE_SKIP_BOOTSTRAP", "1")
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db))

    import leadforge.database as database
    monkeypatch.setattr(database, "DB_PATH", db)
    database.initialize_database()

    conn = sqlite3.connect(db)
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'llm.hook_max_retries'")
    row = cursor.fetchone()
    assert row is not None and row[0] == "3"

    cursor.execute("SELECT value FROM settings WHERE key = 'llm.system_prompt'")
    prompt_row = cursor.fetchone()
    assert prompt_row is not None
    sys_prompt = prompt_row[0]
    assert "Evidence Priority (STRICT ORDER)" in sys_prompt
    assert "FIRST PRIORITY" in sys_prompt
    assert "LAST RESORT ONLY" in sys_prompt
    assert "{banned_vocabulary}" in sys_prompt
    conn.close()

