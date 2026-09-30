"""Tests for local WhatsApp opening-hook generation."""

import requests

from foundation.generator import WhatsAppHookGenerator, WHATSAPP_HOOK_WORD_LIMIT


class FakeSettings:
    """Small SettingsCache-compatible fixture with no database dependency."""

    def __init__(self, **values):
        self.values = values

    def get_str(self, key, default):
        return self.values.get(key, default)

    def get_int(self, key, default):
        return int(self.values.get(key, default))

    def get_float(self, key, default):
        return float(self.values.get(key, default))


def test_fallback_when_disabled():
    generator = WhatsAppHookGenerator(settings_getter=FakeSettings(**{"llm.enabled": "false"}))

    hook, source = generator.generate_hook_with_source(
        company_name="Acme Valves Pvt Ltd", products="valves", area="Vatva"
    )

    assert source == "fallback"
    assert hook == "Hello Sir, noticed Acme Valves operates with valves in Vatva."


def test_fallback_when_ollama_is_unreachable(monkeypatch):
    def unreachable(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("foundation.generator.requests.post", unreachable)
    generator = WhatsAppHookGenerator(
        api_url="http://localhost:9",
        settings_getter=FakeSettings(**{"llm.max_retries": 1}),
    )

    hook, source = generator.generate_hook_with_source(
        company_name="Acme Valves", products="valves", area="Vatva"
    )

    assert hook == "Hello Sir, noticed Acme Valves operates with valves in Vatva."
    assert source == "fallback"


def test_invalid_model_hook_is_rejected_then_degraded(monkeypatch):
    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"response": '{"observation_hook": "Hello Sir, optimize your sales with our solutions."}'}

    monkeypatch.setattr("foundation.generator.requests.post", lambda *args, **kwargs: Response())
    generator = WhatsAppHookGenerator(settings_getter=FakeSettings(**{"llm.max_retries": 1}))

    hook, source = generator.generate_hook_with_source(
        company_name="Acme Valves", products="valves", area="Vatva"
    )

    valid, issues = generator.validate_hook(hook)
    assert not valid
    assert any("banned phrase" in issue.lower() for issue in issues)
    assert source.startswith("fallback:degraded:")


def test_whatsapp_hook_has_hard_fifty_word_cap():
    hook = "Hello Sir, " + "word " * (WHATSAPP_HOOK_WORD_LIMIT - 1)

    valid, issues = WhatsAppHookGenerator.validate_hook(hook)

    assert not valid
    assert any(f"exceeds {WHATSAPP_HOOK_WORD_LIMIT} words" in issue for issue in issues)
