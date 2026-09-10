"""Tests for app.config: environment parsing and path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from app import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in (
        "FINALLY_DB_PATH",
        "FINALLY_STATIC_DIR",
        "DEV_CORS",
        "MASSIVE_API_KEY",
        "OPENROUTER_API_KEY",
        "LLM_MOCK",
    ):
        monkeypatch.delenv(name, raising=False)


def test_project_root_contains_the_backend_package():
    assert (config.PROJECT_ROOT / "backend" / "app").is_dir()


def test_db_path_defaults_under_the_project_root():
    assert config.db_path() == str(config.PROJECT_ROOT / "db" / "finally.db")


def test_relative_db_path_is_resolved_against_the_project_root(monkeypatch):
    monkeypatch.setenv("FINALLY_DB_PATH", "data/x.db")
    assert config.db_path() == str(config.PROJECT_ROOT / "data" / "x.db")


def test_absolute_db_path_is_left_alone(monkeypatch, tmp_path):
    absolute = str(tmp_path / "finally.db")
    monkeypatch.setenv("FINALLY_DB_PATH", absolute)
    assert config.db_path() == absolute


def test_static_dir_defaults_to_cwd_static():
    assert config.static_dir() == Path.cwd() / "static"


def test_static_dir_honours_an_absolute_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FINALLY_STATIC_DIR", str(tmp_path))
    assert config.static_dir() == tmp_path


@pytest.mark.parametrize("raw,expected", [("true", True), ("TRUE", True), ("1", True),
                                          ("yes", True), ("false", False), ("", False)])
def test_dev_cors_parsing(monkeypatch, raw, expected):
    monkeypatch.setenv("DEV_CORS", raw)
    assert config.dev_cors_enabled() is expected


def test_market_source_name_follows_the_massive_key(monkeypatch):
    assert config.market_source_name() == "simulator"
    monkeypatch.setenv("MASSIVE_API_KEY", "  ")
    assert config.market_source_name() == "simulator"
    monkeypatch.setenv("MASSIVE_API_KEY", "abc123")
    assert config.market_source_name() == "massive"


def test_placeholder_openrouter_key_counts_as_absent(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", config.PLACEHOLDER_API_KEY)
    assert config.openrouter_api_key() == ""
    assert config.llm_mock_enabled() is True


def test_real_key_disables_mock_mode(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-real")
    assert config.openrouter_api_key() == "sk-or-real"
    assert config.llm_mock_enabled() is False


def test_llm_mock_flag_wins_over_a_real_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-real")
    monkeypatch.setenv("LLM_MOCK", "true")
    assert config.llm_mock_enabled() is True
