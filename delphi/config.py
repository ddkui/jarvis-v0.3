from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from delphi import secrets

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        # Skip blank placeholders (e.g. unset "GEMINI_API_KEY=") - setting them to ""
        # makes some SDKs treat the key as present-but-empty instead of unset.
        if key and value:
            os.environ.setdefault(key, value)


@dataclass
class DelphiConfig:
    model: str
    vault_dir: Path
    db_path: Path
    reminders_db_path: Path


def load_config() -> DelphiConfig:
    _load_dotenv(REPO_ROOT / ".env")
    secrets.apply_to_environ(secrets.KNOWN_KEYS)

    model = os.environ.get("DELPHI_MODEL", "anthropic/claude-opus-5")
    vault_dir = Path(os.environ.get("DELPHI_VAULT_DIR", "./vault"))
    default_db_path = vault_dir / ".delphi" / "memory.db"
    db_path = Path(os.environ.get("DELPHI_DB_PATH", str(default_db_path)))
    reminders_db_path = vault_dir / ".delphi" / "reminders.db"

    return DelphiConfig(
        model=model,
        vault_dir=vault_dir,
        db_path=db_path,
        reminders_db_path=reminders_db_path,
    )
