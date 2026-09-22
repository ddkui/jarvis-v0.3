"""Persisted conversation history, so delphi chat and the web chat pick up
where you left off across restarts instead of starting from zero every time.
Stores the raw message list DelphiAgent.send() builds (JSON-serializable
dicts - no special objects), at <vault_dir>/.delphi/conversation.json.

This holds one ongoing conversation, not a history of past sessions - "New
conversation" (the CLI's --new flag, the dashboard's reset button) clears it
and starts fresh. There's no automatic trimming, so a very long-running
conversation will keep growing; that's a known limit, not handled here.
"""

from __future__ import annotations

import json
from pathlib import Path


def _conversation_path(vault_dir: Path) -> Path:
    return vault_dir / ".delphi" / "conversation.json"


def load_messages(vault_dir: Path) -> list[dict]:
    path = _conversation_path(vault_dir)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def save_messages(vault_dir: Path, messages: list[dict]) -> None:
    path = _conversation_path(vault_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(messages, indent=2), encoding="utf-8")


def clear(vault_dir: Path) -> None:
    _conversation_path(vault_dir).unlink(missing_ok=True)
