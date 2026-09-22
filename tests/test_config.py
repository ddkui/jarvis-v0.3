import os
from pathlib import Path

from jarvis.config import _load_dotenv


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
