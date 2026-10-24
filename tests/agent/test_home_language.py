"""h5 (HW-201): display.language sets the default reply language and the STT hint."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent import home_language as hl
from agent.i18n import reset_language_cache
from hermes_constants import get_hermes_home
from tools.transcription_tools import _resolve_stt_language


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("HERMES_LANGUAGE", raising=False)
    monkeypatch.delenv("HERMES_LOCAL_STT_LANGUAGE", raising=False)
    reset_language_cache()
    yield
    reset_language_cache()


def _write_config(text: str, home=None):
    home = home or get_hermes_home()
    home.mkdir(parents=True, exist_ok=True)
    (home / "config.yaml").write_text(text, encoding="utf-8")


def _agent():
    return SimpleNamespace(
        load_soul_identity=False, skip_context_files=True, valid_tool_names=[],
        _task_completion_guidance=False, _tool_use_enforcement=False, _environment_probe=False,
        _kanban_worker_guidance="", _memory_store=None, _memory_manager=None, model="", provider="",
        platform="", pass_session_id=False, session_id="", _emit_status=lambda *_a, **_k: None,
    )


def _volatile(agent) -> str:
    from agent.system_prompt import build_system_prompt_parts
    with patch("agent.prompt_builder.load_soul_md", return_value=""), \
         patch("agent.prompt_builder.build_environment_hints", return_value=""):
        return build_system_prompt_parts(agent)["volatile"]


def test_english_home_adds_nothing():
    _write_config("display:\n  language: en\n")
    assert hl.home_language() is None
    assert "home language" not in _volatile(_agent())


def test_unset_language_adds_nothing():
    _write_config("model: x\n")
    assert hl.reply_language_line() is None


def test_russian_home_asks_for_russian_replies():
    _write_config("display:\n  language: ru\n")
    assert hl.home_language() == "ru"
    assert "The user's home language is Русский (ru). Reply in it" in _volatile(_agent())


def test_change_is_read_fresh_without_cache_reset():
    _write_config("display:\n  language: ru\n")
    assert hl.home_language() == "ru"
    _write_config("display:\n  language: de\n")
    assert hl.home_language() == "de"


def test_env_language_wins(monkeypatch):
    _write_config("display:\n  language: ru\n")
    monkeypatch.setenv("HERMES_LANGUAGE", "en")
    assert hl.home_language() is None


def test_explicit_home_argument(tmp_path):
    other = tmp_path / "lera"
    _write_config("display:\n  language: ru\n", home=other)
    _write_config("display:\n  language: en\n")
    assert hl.home_language(other) == "ru"
    assert hl.home_language() is None


class TestSttHint:
    def test_seeded_default_follows_home_language(self):
        _write_config("display:\n  language: ru\n")
        assert _resolve_stt_language("openai", {"language": "en"}) == "ru"

    def test_regional_id_uses_base_code(self):
        _write_config("display:\n  language: zh-hant\n")
        assert _resolve_stt_language("openai", {"language": "en"}) == "zh"

    def test_explicit_global_language_wins(self):
        _write_config("display:\n  language: ru\nstt:\n  language: en\n")
        assert _resolve_stt_language("openai", {"language": "en"}) == "en"

    def test_managed_global_language_wins(self):
        _write_config("display:\n  language: ru\n")
        with patch("hermes_cli.managed_scope.load_managed_config", return_value={"stt": {"language": "en"}}):
            assert _resolve_stt_language("openai", {"language": "en"}) == "en"

    def test_provider_language_still_wins(self):
        _write_config("display:\n  language: ru\n")
        assert _resolve_stt_language("groq", {"language": "en", "groq": {"language": "he"}}) == "he"

    def test_non_default_value_untouched(self):
        _write_config("display:\n  language: ru\n")
        assert _resolve_stt_language("openai", {"language": "hu"}) == "hu"

    def test_english_home_keeps_default(self):
        _write_config("display:\n  language: en\n")
        assert _resolve_stt_language("openai", {"language": "en"}) == "en"
