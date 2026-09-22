from __future__ import annotations

from pathlib import Path

from jarvis.memory import facts
from jarvis.models import Tool


def _require(input: dict, key: str) -> object:
    if key not in input or input[key] in (None, ""):
        raise ValueError(f"missing required field: {key}")
    return input[key]


def build_tools(vault_dir: Path) -> list[Tool]:
    def remember(input: dict) -> str:
        text = _require(input, "text")
        fact = facts.add_fact(vault_dir, text)
        return f"Remembered ({fact.id}): {fact.text}"

    def forget(input: dict) -> str:
        fact_id = _require(input, "fact_id")
        if not facts.remove_fact(vault_dir, fact_id):
            return f"No memory found with id {fact_id}"
        return f"Forgot memory {fact_id}"

    def list_memory(input: dict) -> str:
        items = facts.list_facts(vault_dir)
        if not items:
            return "Nothing remembered yet."
        return "\n".join(f"{f.id} | {f.text}" for f in items)

    return [
        Tool(
            name="remember",
            description=(
                "Silently save a short, durable fact about the user for future conversations "
                "(their name, a preference, an ongoing situation). Use this proactively the "
                "moment you learn something worth remembering — don't ask first. One clear "
                "sentence; don't remember trivia. For longer content, use add_note instead."
            ),
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string", "description": "The fact to remember"}},
                "required": ["text"],
            },
            handler=remember,
        ),
        Tool(
            name="forget",
            description="Remove a previously remembered fact by id, e.g. if the user corrects or retracts it.",
            input_schema={
                "type": "object",
                "properties": {"fact_id": {"type": "string", "description": "Memory fact id"}},
                "required": ["fact_id"],
            },
            handler=forget,
        ),
        Tool(
            name="list_memory",
            description="List everything currently remembered about the user.",
            input_schema={"type": "object", "properties": {}},
            handler=list_memory,
        ),
    ]
