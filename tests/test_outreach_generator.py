import json
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
    assert called_kwargs["json"]["model"] == "llama3.2:3b"
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
