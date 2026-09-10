"""Configuration, model selection, and the free-only spend guard."""

from __future__ import annotations

import pytest

from app.llm import config


class TestModelSelection:
    def test_defaults_to_a_free_model(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
        assert config.model() == config.DEFAULT_MODEL
        assert config.model().endswith(":free")

    def test_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_MODEL", "vendor/other:free")
        assert config.model() == "vendor/other:free"

    def test_strips_an_existing_openrouter_prefix(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/vendor/other:free")
        assert config.model() == "vendor/other:free"

    def test_litellm_model_is_always_prefixed_exactly_once(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_MODEL", "openrouter/vendor/other:free")
        assert config.litellm_model() == "openrouter/vendor/other:free"
        monkeypatch.setenv("OPENROUTER_MODEL", "vendor/other:free")
        assert config.litellm_model() == "openrouter/vendor/other:free"


class TestTimeout:
    def test_default_is_thirty_seconds(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_TIMEOUT", raising=False)
        assert config.timeout_seconds() == 30.0

    def test_reads_the_environment(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_TIMEOUT", "12.5")
        assert config.timeout_seconds() == 12.5

    @pytest.mark.parametrize("raw", ["", "not-a-number", "0", "-5"])
    def test_falls_back_on_unusable_values(self, monkeypatch, raw):
        monkeypatch.setenv("OPENROUTER_TIMEOUT", raw)
        assert config.timeout_seconds() == 30.0


class TestProviderOrder:
    def test_empty_by_default(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_PROVIDER_ORDER", raising=False)
        assert config.provider_order() == []

    def test_parses_a_comma_separated_list(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_PROVIDER_ORDER", " cerebras , groq ,, ")
        assert config.provider_order() == ["cerebras", "groq"]


class TestReasoningEffort:
    def test_defaults_to_low(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_REASONING_EFFORT", raising=False)
        assert config.reasoning_effort() == "low"

    def test_empty_string_means_omit(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "")
        assert config.reasoning_effort() == ""


class TestMockReason:
    def test_llm_mock_wins(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "true")
        monkeypatch.setenv("OPENROUTER_API_KEY", "real-key")
        assert config.mock_reason() == "LLM_MOCK=true"

    def test_missing_key(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        assert "OPENROUTER_API_KEY" in config.mock_reason()

    def test_placeholder_key_counts_as_missing(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "REPLACE_ME")
        assert "OPENROUTER_API_KEY" in config.mock_reason()

    def test_free_only_blocks_a_paid_model(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "real-key")
        monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-oss-120b")
        reason = config.mock_reason()
        assert reason is not None
        assert "OPENROUTER_FREE_ONLY" in reason
        assert config.mock_enabled() is True

    def test_free_only_allows_a_free_model(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "real-key")
        monkeypatch.setenv("OPENROUTER_MODEL", "vendor/model:free")
        assert config.mock_reason() is None
        assert config.mock_enabled() is False

    def test_free_only_can_be_disabled_explicitly(self, monkeypatch):
        monkeypatch.setenv("LLM_MOCK", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "real-key")
        monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-oss-120b")
        monkeypatch.setenv("OPENROUTER_FREE_ONLY", "false")
        assert config.mock_reason() is None
