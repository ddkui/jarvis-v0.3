import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from jarvis.models import Note


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:50] or "note"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_note_file(path: Path) -> Note | None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end == -1:
        return None
    frontmatter_raw = text[4:end]
    content = text[end + 5:].lstrip("\n").rstrip("\n")
    meta = yaml.safe_load(frontmatter_raw) or {}
    return Note(
        id=meta.get("id", ""),
        title=meta.get("title", ""),
        content=content,
        tags=meta.get("tags") or [],
        created_at=meta.get("created_at", ""),
        updated_at=meta.get("updated_at", ""),
        path=path.name,
    )


def _render_note_file(note: Note) -> str:
    frontmatter = yaml.safe_dump(
        {
            "id": note.id,
            "title": note.title,
            "tags": note.tags,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        },
        sort_keys=False,
    )
    return f"---\n{frontmatter}---\n{note.content}\n"


class Vault:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _find_note_path(self, note_id: str) -> Path | None:
        for path in self.root.glob("*.md"):
            if path.name.startswith(f"{note_id}-") or path.stem == note_id:
                return path
        return None

    def create_note(self, title: str, content: str, tags: list[str] | None = None) -> Note:
        note_id = uuid.uuid4().hex[:12]
        slug = _slugify(title)
        filename = f"{note_id}-{slug}.md"
        now = _now()
        note = Note(
            id=note_id,
            title=title,
            content=content,
            tags=tags or [],
            created_at=now,
            updated_at=now,
            path=filename,
        )
        (self.root / filename).write_text(_render_note_file(note), encoding="utf-8")
        return note

    def get_note(self, note_id: str) -> Note | None:
        path = self._find_note_path(note_id)
        if path is None:
            return None
        return _parse_note_file(path)

    def update_note(
        self,
        note_id: str,
        content: str | None = None,
        tags: list[str] | None = None,
        title: str | None = None,
    ) -> Note | None:
        path = self._find_note_path(note_id)
        if path is None:
            return None
        note = _parse_note_file(path)
        if note is None:
            return None
        if content is not None:
            note.content = content
        if tags is not None:
            note.tags = tags
        if title is not None:
            note.title = title
        note.updated_at = _now()
        path.write_text(_render_note_file(note), encoding="utf-8")
        return note

    def list_notes(self) -> list[Note]:
        notes = []
        for path in self.root.glob("*.md"):
            note = _parse_note_file(path)
            if note is not None:
                notes.append(note)
        notes.sort(key=lambda n: n.updated_at, reverse=True)
        return notes

    def delete_note(self, note_id: str) -> bool:
        path = self._find_note_path(note_id)
        if path is None:
            return False
        path.unlink()
        return True
