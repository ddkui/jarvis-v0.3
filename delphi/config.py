from __future__ import annotations

import os
from dataclasses import dataclass, field
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
    fallback_models: list[str] = field(default_factory=list)
    request_timeout_seconds: float = 60.0
    ollama_num_ctx: int | None = 8192


def load_config() -> DelphiConfig:
    _load_dotenv(REPO_ROOT / ".env")
    secrets.apply_to_environ(secrets.KNOWN_KEYS)

    model = os.environ.get("DELPHI_MODEL", "anthropic/claude-opus-5")
    vault_dir = Path(os.environ.get("DELPHI_VAULT_DIR", "./vault"))
    default_db_path = vault_dir / ".delphi" / "memory.db"
    db_path = Path(os.environ.get("DELPHI_DB_PATH", str(default_db_path)))
    reminders_db_path = vault_dir / ".delphi" / "reminders.db"
    fallback_models = [
        m.strip() for m in os.environ.get("DELPHI_FALLBACK_MODELS", "").split(",") if m.strip()
    ]
    try:
        request_timeout_seconds = float(os.environ.get("DELPHI_REQUEST_TIMEOUT", "60"))
    except ValueError:
        request_timeout_seconds = 60.0

    # "0" (not "" - _load_dotenv skips blank .env values entirely, so an
    # empty-string sentinel could never actually reach here from .env) opts
    # out of overriding num_ctx at all, e.g. if a custom Ollama Modelfile
    # already sets a larger one server-side and Delphi shouldn't clobber it.
    try:
        parsed_num_ctx = int(os.environ.get("DELPHI_OLLAMA_NUM_CTX", "8192").strip())
        ollama_num_ctx = parsed_num_ctx if parsed_num_ctx > 0 else None
    except ValueError:
        ollama_num_ctx = 8192

    return DelphiConfig(
        model=model,
        vault_dir=vault_dir,
        db_path=db_path,
        reminders_db_path=reminders_db_path,
        fallback_models=fallback_models,
        request_timeout_seconds=request_timeout_seconds,
        ollama_num_ctx=ollama_num_ctx,
    )
