import pytest
from unittest.mock import patch, MagicMock
import requests
from leadforge.outreach.generator import OllamaHookGenerator


@pytest.fixture
def generator() -> OllamaHookGenerator:
    return OllamaHookGenerator(api_url="http://mock-ollama:11434")


@patch("requests.post")
def test_generate_hook_success(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Verify that a successful HTTP response is parsed correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": '{"observation_hook": "I saw your clinic on Maps and noticed there is no website listed."}'
    }
    mock_post.return_value = mock_response

    hook = generator.generate_hook(
        business_name="Star Dental",
        review_count=12,
        rating=4.5,
        city="Ahmedabad",
        scraped_text="",
    )

    assert hook == "I saw your clinic on Maps and noticed there is no website listed."
    mock_post.assert_called_once()

    # Assert correct parameters were sent
    called_args, called_kwargs = mock_post.call_args
    assert called_kwargs["json"]["model"] == generator.model_name
    assert called_kwargs["json"]["format"] == "json"
    assert called_kwargs["json"]["options"]["num_predict"] == 150


@patch("requests.post")
def test_generate_hook_markdown_wrapping(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Verify that markdown wrapped JSON from Ollama is extracted and parsed correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": '```json\n{"observation_hook": "I noticed your website takes 6 seconds to load on mobile."}\n```'
    }
    mock_post.return_value = mock_response

    hook = generator.generate_hook(
        business_name="Apex Logistics",
        review_count=5,
        rating=4.0,
        city="Ahmedabad",
        scraped_text="",
    )

    assert hook == "I noticed your website takes 6 seconds to load on mobile."


@patch("requests.post")
def test_generate_hook_connection_error_fallback(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Verify connection errors return a safe review-count-based fallback hook."""
    mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")

    hook = generator.generate_hook(
        business_name="Apex Logistics",
        review_count=23,
        rating=4.8,
        city="Ahmedabad",
        scraped_text="",
    )

    # Fallback should use the rating & review count
    assert "4.8" in hook
    assert "23" in hook



@patch("requests.post")
def test_generate_hook_malformed_json_fallback(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Verify that malformed JSON strings from Ollama trigger the review-count fallback."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "response": 'invalid json output'
    }
    mock_post.return_value = mock_response

    hook = generator.generate_hook(
        business_name="Apex Logistics",
        review_count=10,
        rating=3.9,
        city="Ahmedabad",
        scraped_text="",
    )

    assert "3.9" in hook
    assert "10" in hook


# ============================================================================
# Task C Tests: Evidence-Bound & De-Indianized Prompts & Premise Plumbing
# ============================================================================


def test_prompts_contain_no_geo_hardcoding():
    """Verify DEFAULT_SYSTEM_PROMPT and DEFAULT_USER_PROMPT_TEMPLATE contain no Ahmedabad/Gujarat/India hardcoding."""
    from leadforge.outreach.generator import DEFAULT_SYSTEM_PROMPT, DEFAULT_USER_PROMPT_TEMPLATE
    hardcoded_terms = ["ahmedabad", "gujarat", "india", "indian", "vatva", "odhav", "gidc"]
    sys_lower = DEFAULT_SYSTEM_PROMPT.lower()
    user_lower = DEFAULT_USER_PROMPT_TEMPLATE.lower()

    for term in hardcoded_terms:
        assert term not in sys_lower, f"Found hardcoded term '{term}' in DEFAULT_SYSTEM_PROMPT"
        assert term not in user_lower, f"Found hardcoded term '{term}' in DEFAULT_USER_PROMPT_TEMPLATE"


def test_settings_contain_no_geo_hardcoding(tmp_path, monkeypatch):
    """Verify live settings for system prompt, user prompt template, and composer body contain no Ahmedabad/Gujarat/India hardcoding."""
    db = tmp_path / "settings_test.db"
    monkeypatch.setenv("LEADFORGE_SKIP_BOOTSTRAP", "1")
    monkeypatch.setenv("LEADFORGE_DB_PATH", str(db))

    import leadforge.database as database
    monkeypatch.setattr(database, "DB_PATH", db)
    database.initialize_database()

    from leadforge.repositories.settings import SQLiteSettingsRepository
    settings = SQLiteSettingsRepository()
    sys_prompt = (settings.get("llm.system_prompt") or "").lower()
    user_template = (settings.get("llm.user_prompt_template") or "").lower()
    composer_body = (settings.get("outreach.composer_body") or "").lower()

    hardcoded_terms = ["ahmedabad", "gujarat", "india", "indian"]
    for term in hardcoded_terms:
        assert term not in sys_prompt, f"Found hardcoded term '{term}' in llm.system_prompt setting"
        assert term not in user_template, f"Found hardcoded term '{term}' in llm.user_prompt_template setting"
        assert term not in composer_body, f"Found hardcoded term '{term}' in outreach.composer_body setting"

    assert "{operational_premise}" in user_template
    assert "{observation_hook}" in composer_body


def test_banned_phrase_list_survives():
    """Verify that all banned phrases survive in the resolved system prompt."""
    from leadforge.outreach.generator import DEFAULT_SYSTEM_PROMPT, resolve_system_prompt
    from leadforge.outreach.quality import EmailQualityEngine

    resolved = resolve_system_prompt(DEFAULT_SYSTEM_PROMPT).lower()
    banned = EmailQualityEngine.AI_JARGON_PHRASES | EmailQualityEngine.SPAM_KEYWORDS
    missing = [t for t in banned if t.lower() not in resolved]
    assert missing == [], f"Banned terms missing from resolved system prompt: {missing}"

    core_banned = [
        "online presence",
        "digital footprint",
        "digital age",
        "solutions",
        "leverage",
        "optimize",
        "streamline",
    ]
    for phrase in core_banned:
        assert phrase in resolved, f"Core banned phrase '{phrase}' missing from resolved system prompt"


def test_json_output_contract_unchanged():
    """Verify that raw JSON output contract format is maintained."""
    from leadforge.outreach.generator import DEFAULT_SYSTEM_PROMPT
    assert '{"observation_hook":' in DEFAULT_SYSTEM_PROMPT
    assert '"observation_hook"' in DEFAULT_SYSTEM_PROMPT


@patch("requests.post")
def test_unconfirmed_premise_flag_reaches_rendered_prompt(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Verify premise_verified=False injects 'Operational Premise: UNCONFIRMED' into the prompt sent to Ollama."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": '{"observation_hook": "A valid hook."}'}
    mock_post.return_value = mock_resp

    # 1. Unconfirmed premise
    generator.generate_hook(
        business_name="ATX Family Dental",
        review_count=128,
        rating=4.9,
        city="Austin",
        scraped_text="Family and cosmetic dentistry",
        category="Dentist",
        area="Downtown",
        has_website=True,
        premise_verified=False,
    )
    called_kwargs = mock_post.call_args[1]["json"]
    sent_prompt = called_kwargs["prompt"]
    assert "Operational Premise: UNCONFIRMED" in sent_prompt
    assert "ATX Family Dental" in sent_prompt
    assert "Austin" in sent_prompt

    # 2. Confirmed premise
    generator.generate_hook(
        business_name="Sydney Roof Masters",
        review_count=45,
        rating=4.7,
        city="Sydney",
        scraped_text="",
        category="Roofing Contractor",
        area="CBD",
        has_website=False,
        premise_verified=True,
    )
    called_kwargs_2 = mock_post.call_args[1]["json"]
    sent_prompt_2 = called_kwargs_2["prompt"]
    assert "Operational Premise: CONFIRMED" in sent_prompt_2
    assert "Sydney Roof Masters" in sent_prompt_2


@patch("requests.post")
def test_generate_hook_with_source_passes_premise_verified(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Verify generate_hook_with_source passes premise_verified through kwargs."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"response": '{"observation_hook": "A valid hook."}'}
    mock_post.return_value = mock_resp

    hook, source = generator.generate_hook_with_source(
        business_name="Apex Law Group",
        review_count=30,
        rating=4.6,
        city="Denver",
        scraped_text="Commercial litigation",
        category="Law Firm",
        area="Downtown",
        has_website=True,
        premise_verified=False,
    )
    assert source == "llm"
    assert hook == "A valid hook."
    sent_prompt = mock_post.call_args[1]["json"]["prompt"]
    assert "Operational Premise: UNCONFIRMED" in sent_prompt


def test_system_prompt_evidence_bound_multinational_examples():
    """Verify system prompt includes evidence-bound rules and multinational examples."""
    from leadforge.outreach.generator import DEFAULT_SYSTEM_PROMPT
    assert "EVIDENCE-BOUND" in DEFAULT_SYSTEM_PROMPT
    assert "UNCONFIRMED" in DEFAULT_SYSTEM_PROMPT
    assert "Austin" in DEFAULT_SYSTEM_PROMPT
    assert "Sydney" in DEFAULT_SYSTEM_PROMPT
    assert "Denver" in DEFAULT_SYSTEM_PROMPT
    assert "Chicago" in DEFAULT_SYSTEM_PROMPT
    assert "Dentist" in DEFAULT_SYSTEM_PROMPT
    assert "Roofing" in DEFAULT_SYSTEM_PROMPT
    assert "Law Firm" in DEFAULT_SYSTEM_PROMPT


# ============================================================================
# Task E Tests: Hook Quality Validation, Retries & Evidence Priority
# ============================================================================

def test_system_prompt_evidence_ordering():
    """Verify system prompt explicitly establishes evidence hierarchy."""
    from leadforge.outreach.generator import DEFAULT_SYSTEM_PROMPT
    assert "Evidence Priority (STRICT ORDER)" in DEFAULT_SYSTEM_PROMPT
    assert "FIRST PRIORITY" in DEFAULT_SYSTEM_PROMPT
    assert "SECOND PRIORITY" in DEFAULT_SYSTEM_PROMPT
    assert "LAST RESORT ONLY" in DEFAULT_SYSTEM_PROMPT
    assert "Never recite Google ratings if usable website text was provided" in DEFAULT_SYSTEM_PROMPT


@patch("requests.post")
def test_generator_retry_on_invalid_hook_and_recover(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Verify generator retries on invalid hook output and succeeds when subsequent attempt passes."""
    # Attempt 1: Too long (18 words)
    resp1 = MagicMock()
    resp1.status_code = 200
    resp1.json.return_value = {
        "response": '{"observation_hook": "Sakar Plastic Industries has a website with over 50 years of experience as an eco-friendly packaging provider."}'
    }

    # Attempt 2: Clean & valid (11 words)
    resp2 = MagicMock()
    resp2.status_code = 200
    resp2.json.return_value = {
        "response": '{"observation_hook": "I noticed Sakar Plastic produces eco-friendly packaging for industrial clients."}'
    }

    mock_post.side_effect = [resp1, resp2]

    hook, source = generator.generate_hook_with_source(
        business_name="Sakar Plastic Industries",
        review_count=10,
        rating=4.5,
        city="Denver",
        scraped_text="Eco-friendly packaging manufacturer for industrial clients",
        category="Packaging",
    )

    assert mock_post.call_count == 2
    assert hook == "I noticed Sakar Plastic produces eco-friendly packaging for industrial clients."
    assert source == "llm"


@patch("requests.post")
def test_generator_bounded_retry_cap_and_degraded_fallback(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Verify bounded retry cap and fallback to best candidate seen with degraded provenance."""
    # Attempt 1: Too long + banned phrase + filler (22 words, 3 issues)
    resp1 = MagicMock()
    resp1.status_code = 200
    resp1.json.return_value = {
        "response": '{"observation_hook": "Sakar Plastic Industries has a website with over 50 years of experience as an eco-friendly packaging solutions provider in Denver."}'
    }

    # Attempt 2: Only slightly too long (16 words, 1 issue, no banned words or filler)
    resp2 = MagicMock()
    resp2.status_code = 200
    resp2.json.return_value = {
        "response": '{"observation_hook": "I noticed Sakar Plastic Industries manufactures specialized custom packaging for industrial clients across multiple commercial sectors."}'
    }

    # Attempt 3: Rating recital + filler (14 words, 2 issues)
    resp3 = MagicMock()
    resp3.status_code = 200
    resp3.json.return_value = {
        "response": '{"observation_hook": "Sakar Plastic Industries has a Google rating of 4.5 from 10 reviews in various locations."}'
    }

    mock_post.side_effect = [resp1, resp2, resp3]

    hook, source = generator.generate_hook_with_source(
        business_name="Sakar Plastic Industries",
        review_count=10,
        rating=4.5,
        city="Denver",
        scraped_text="Eco-friendly packaging manufacturer for industrial clients",
        category="Packaging",
    )

    assert mock_post.call_count == 3
    assert source.startswith("fallback:degraded:")
    assert "degraded" in source
    assert hook == "I noticed Sakar Plastic Industries manufactures specialized custom packaging for industrial clients across multiple commercial sectors."


@patch("requests.post")
def test_generator_custom_max_retries_setting(mock_post: MagicMock):
    """Verify generator respects configured max_retries setting."""
    class _CustomSettings:
        def get_str(self, k, d=""):
            return d
        def get_int(self, k, d=0):
            if k in ("llm.hook_max_retries", "llm.max_retries"):
                return 2
            return d
        def get_float(self, k, d=0.0):
            return d

    gen = OllamaHookGenerator(settings_getter=_CustomSettings())

    # Return invalid hooks on every attempt
    invalid_resp = MagicMock()
    invalid_resp.status_code = 200
    invalid_resp.json.return_value = {
        "response": '{"observation_hook": "This is an extremely long sentence that definitely exceeds the fifteen word limit set for outreach hooks in our system."}'
    }
    mock_post.return_value = invalid_resp

    gen.generate_hook_with_source(
        business_name="Apex Corp",
        review_count=5,
        rating=4.0,
        city="Austin",
        scraped_text="Custom metal fabrication",
    )

    assert mock_post.call_count == 2


@patch("requests.post")
def test_generator_rating_recital_retried_when_site_text_present(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Rating recital must be retried when usable site text is supplied, accepting clean site hook on attempt 2."""
    # Attempt 1: Rating recital
    resp1 = MagicMock()
    resp1.status_code = 200
    resp1.json.return_value = {
        "response": '{"observation_hook": "Ratan Plastics has a Google rating of 4.5 based on 30 reviews."}'
    }

    # Attempt 2: Site evidence hook
    resp2 = MagicMock()
    resp2.status_code = 200
    resp2.json.return_value = {
        "response": '{"observation_hook": "I saw Ratan Plastics exports packaging to over 45 countries."}'
    }

    mock_post.side_effect = [resp1, resp2]

    hook, source = generator.generate_hook_with_source(
        business_name="Ratan Plastics",
        review_count=30,
        rating=4.5,
        city="Chicago",
        scraped_text="Leading manufacturer of plastic packaging exporting to 45 countries worldwide.",
        category="Packaging",
    )

    assert mock_post.call_count == 2
    assert hook == "I saw Ratan Plastics exports packaging to over 45 countries."
    assert source == "llm"


@patch("requests.post")
def test_generator_rating_recital_accepted_when_no_site_text(mock_post: MagicMock, generator: OllamaHookGenerator):
    """Rating recital is accepted on first attempt when no website text is available."""
    resp1 = MagicMock()
    resp1.status_code = 200
    resp1.json.return_value = {
        "response": '{"observation_hook": "I saw ATX Family Dental has 128 reviews with a 4.9 rating in Austin."}'
    }
    mock_post.return_value = resp1

    hook, source = generator.generate_hook_with_source(
        business_name="ATX Family Dental",
        review_count=128,
        rating=4.9,
        city="Austin",
        scraped_text="",
        category="Dentist",
    )

    assert mock_post.call_count == 1
    assert hook == "I saw ATX Family Dental has 128 reviews with a 4.9 rating in Austin."
    assert source == "llm"


def test_validate_specific_topic():
    from leadforge.outreach.generator import validate_specific_topic

    # Valid short grounded topics (1-3 words)
    assert validate_specific_topic("servo voltage stabilizers")[0] is True
    assert validate_specific_topic("servo voltage stabilizers")[1] == "servo voltage stabilizers"
    assert validate_specific_topic('"temperature instruments."')[0] is True
    assert validate_specific_topic('"temperature instruments."')[1] == "temperature instruments"
    assert validate_specific_topic("thermochromic pigments")[0] is True
    assert validate_specific_topic("thermochromic pigments")[1] == "thermochromic pigments"

    # Over-length topics compressed to 1-3 words
    valid_gum, compressed_gum = validate_specific_topic("cassia tora gum powder")
    assert valid_gum is True
    assert compressed_gum == "cassia tora gum"
    assert len(compressed_gum.split()) <= 3

    valid_dyes, compressed_dyes = validate_specific_topic("reactive dyes manufacturing")
    assert valid_dyes is True
    assert compressed_dyes == "reactive dyes"
    assert len(compressed_dyes.split()) <= 3

    valid_stabilizers, compressed_stabilizers = validate_specific_topic("oil cooled servo voltage stabilizers")
    assert valid_stabilizers is True
    assert compressed_stabilizers == "servo voltage stabilizers"
    assert len(compressed_stabilizers.split()) <= 3

    # Over-length topic rejected when compression is disabled
    assert validate_specific_topic("four word product phrase", allow_compression=False)[0] is False

    # Invalid topics: empty / sentence garbage / generic / banned
    assert validate_specific_topic("")[0] is False
    assert validate_specific_topic("   ")[0] is False
    assert validate_specific_topic("products")[0] is False
    assert validate_specific_topic("solutions")[0] is False
    assert validate_specific_topic("digital footprint")[0] is False
    assert validate_specific_topic("this is way too many words for a concise specific product topic tag")[0] is False


@patch("requests.post")
def test_generate_hook_extracts_specific_topic(mock_post: MagicMock, generator: OllamaHookGenerator):
    """When LLM returns specific_topic and observation_hook, both are captured and validated."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "response": '{"observation_hook": "I noticed Aavad Instrument manufactures temperature and pressure instruments.", "specific_topic": "temperature instruments"}'
    }
    mock_post.return_value = resp

    hook, source, topic = generator.generate_hook_with_details(
        business_name="Aavad Instrument",
        review_count=45,
        rating=4.7,
        city="Ahmedabad",
        scraped_text="Precision instrumentation, temperature sensors, pressure gauges, and transmitters.",
        category="Manufacturers",
    )

    assert source == "llm"
    assert topic == "temperature instruments"
    assert generator.last_specific_topic == "temperature instruments"
    assert generator.last_classification is not None
    assert generator.last_classification.is_usable is True



