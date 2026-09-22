"""Long-term fact memory: short, durable facts about the user (name,
preferences, ongoing context) that Delphi remembers silently and carries into
every future conversation - distinct from delphi.memory.store, which is the
searchable note-vault index you have to explicitly query.

Stored as JSON at <vault_dir>/.delphi/memory_facts.json. Capped at
_MAX_FACTS: past that, the oldest fact is dropped when a new one is added, so
the system prompt these get folded into (see delphi/agent/prompts.py) doesn't
grow without bound.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

_MAX_FACTS = 50


@dataclass
class MemoryFact:
    id: str
    text: str
    created_at: str


def _facts_path(vault_dir: Path) -> Path:
    return vault_dir / ".delphi" / "memory_facts.json"


def list_facts(vault_dir: Path) -> list[MemoryFact]:
    path = _facts_path(vault_dir)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    return [MemoryFact(**item) for item in data]


def _save(vault_dir: Path, facts: list[MemoryFact]) -> None:
    path = _facts_path(vault_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(f) for f in facts], indent=2), encoding="utf-8")


def add_fact(vault_dir: Path, text: str) -> MemoryFact:
    if not text.strip():
        raise ValueError("fact text must not be empty")
    facts = list_facts(vault_dir)
    fact = MemoryFact(
        id=uuid.uuid4().hex[:12],
        text=text.strip(),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    facts.append(fact)
    if len(facts) > _MAX_FACTS:
        facts = facts[-_MAX_FACTS:]
    _save(vault_dir, facts)
    return fact


def remove_fact(vault_dir: Path, fact_id: str) -> bool:
    facts = list_facts(vault_dir)
    remaining = [f for f in facts if f.id != fact_id]
    if len(remaining) == len(facts):
        return False
    _save(vault_dir, remaining)
    return True
