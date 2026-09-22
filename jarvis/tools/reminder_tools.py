from __future__ import annotations

from jarvis.models import Tool


def _require(input: dict, key: str) -> object:
    if key not in input or input[key] in (None, ""):
        raise ValueError(f"missing required field: {key}")
    return input[key]


def build_tools(reminders) -> list[Tool]:
    def add_reminder(input: dict) -> str:
        text = _require(input, "text")
        due_at = _require(input, "due_at")
        reminder = reminders.add(text, due_at)
        return f"Added reminder {reminder.id}: {reminder.text} (due {reminder.due_at})"

    def list_reminders(input: dict) -> str:
        include_done = bool(input.get("include_done", False))
        items = reminders.list(include_done=include_done)
        if not items:
            return "No reminders."
        lines = []
        for r in items:
            status = "done" if r.done else "pending"
            lines.append(f"{r.id} | {r.text} | due {r.due_at} | {status}")
        return "\n".join(lines)

    def complete_reminder(input: dict) -> str:
        reminder_id = _require(input, "reminder_id")
        ok = reminders.complete(reminder_id)
        if ok:
            return f"Marked reminder {reminder_id} as done."
        return f"No reminder found with id {reminder_id}"

    return [
        Tool(
            name="add_reminder",
            description="Add a new reminder with due date/time.",
            input_schema={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to be reminded of"},
                    "due_at": {
                        "type": "string",
                        "description": "ISO8601 due date/time, e.g. 2026-09-23T09:00:00",
                    },
                },
                "required": ["text", "due_at"],
            },
            handler=add_reminder,
        ),
        Tool(
            name="list_reminders",
            description="List reminders, pending by default.",
            input_schema={
                "type": "object",
                "properties": {
                    "include_done": {
                        "type": "boolean",
                        "description": "Include completed reminders (default false)",
                    }
                },
                "required": [],
            },
            handler=list_reminders,
        ),
        Tool(
            name="complete_reminder",
            description="Mark a reminder as done by id.",
            input_schema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "string", "description": "Reminder id"},
                },
                "required": ["reminder_id"],
            },
            handler=complete_reminder,
        ),
    ]
