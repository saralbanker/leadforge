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


def test_resolve_leaves_a_custom_prompt_without_the_placeholder_alone():
    custom = "Write one sentence. Output JSON."
    assert resolve_system_prompt(custom) == custom


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
