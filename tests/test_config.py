import os
from pathlib import Path

from delphi.config import _load_dotenv, load_config


def test_blank_placeholder_does_not_set_env_var(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("SOME_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_KEY=\nOTHER_KEY=value\n")

    _load_dotenv(env_file)

    assert "SOME_KEY" not in os.environ
    assert os.environ["OTHER_KEY"] == "value"


def test_real_env_var_wins_over_dotenv_value(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("SOME_KEY", "from-shell")
    env_file = tmp_path / ".env"
    env_file.write_text("SOME_KEY=from-dotenv\n")

    _load_dotenv(env_file)

    assert os.environ["SOME_KEY"] == "from-shell"


def test_fallback_models_defaults_to_empty(monkeypatch):
    monkeypatch.delenv("DELPHI_FALLBACK_MODELS", raising=False)
    assert load_config().fallback_models == []


def test_fallback_models_parses_comma_separated_list(monkeypatch):
    monkeypatch.setenv(
        "DELPHI_FALLBACK_MODELS", "nvidia_nim/meta/llama3-70b-instruct, groq/llama-3.3-70b-versatile"
    )
    assert load_config().fallback_models == [
        "nvidia_nim/meta/llama3-70b-instruct",
        "groq/llama-3.3-70b-versatile",
    ]


def test_fallback_models_ignores_blank_entries(monkeypatch):
    monkeypatch.setenv("DELPHI_FALLBACK_MODELS", "nvidia_nim/meta/llama3-70b-instruct,,  ,")
    assert load_config().fallback_models == ["nvidia_nim/meta/llama3-70b-instruct"]
