from __future__ import annotations

from jarvis.memory.retrieval import retrieve_context
from jarvis.memory.store import MemoryStore
from jarvis.models import Tool
from jarvis.vault import Vault


def _require(input: dict, key: str) -> object:
    if key not in input or input[key] in (None, ""):
        raise ValueError(f"missing required field: {key}")
    return input[key]


def build_tools(vault: Vault, store: MemoryStore) -> list[Tool]:
    def search_notes(input: dict) -> str:
        query = _require(input, "query")
        limit = input.get("limit", 5)
        context = retrieve_context(store, vault, query, limit=limit)
        return context or "No matching notes found."

    def add_note(input: dict) -> str:
        title = _require(input, "title")
        content = _require(input, "content")
        tags = input.get("tags") or []
        note = vault.create_note(title, content, tags=tags)
        store.index_note(note)
        return f"Created note {note.id}: {note.title}"

    def list_notes(input: dict) -> str:
        limit = input.get("limit")
        notes = vault.list_notes()
        if limit is not None:
            notes = notes[: int(limit)]
        if not notes:
            return "No notes yet."
        return "\n".join(f"{n.id} | {n.title} | updated {n.updated_at}" for n in notes)

    def get_note(input: dict) -> str:
        note_id = _require(input, "note_id")
        note = vault.get_note(note_id)
        if note is None:
            return f"No note found with id {note_id}"
        tags = ", ".join(note.tags) if note.tags else "none"
        return f"# {note.title}\ntags: {tags}\nupdated: {note.updated_at}\n\n{note.content}"

    return [
        Tool(
            name="search_notes",
            description=(
                "Search the user's note vault for content relevant to a query. "
                "Use this before claiming you don't know something."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 5)",
                    },
                },
                "required": ["query"],
            },
            handler=search_notes,
        ),
        Tool(
            name="add_note",
            description="Create a new note in the vault and index it for search.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "Note title"},
                    "content": {"type": "string", "description": "Note body"},
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional list of tags",
                    },
                },
                "required": ["title", "content"],
            },
            handler=add_note,
        ),
        Tool(
            name="list_notes",
            description="List notes in the vault, most recently updated first.",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Max notes to return (default: all)",
                    }
                },
                "required": [],
            },
            handler=list_notes,
        ),
        Tool(
            name="get_note",
            description="Fetch the full content of a single note by id.",
            input_schema={
                "type": "object",
                "properties": {
                    "note_id": {"type": "string", "description": "Note id"},
                },
                "required": ["note_id"],
            },
            handler=get_note,
        ),
    ]
