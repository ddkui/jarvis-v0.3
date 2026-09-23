from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from delphi.models import Reminder

if TYPE_CHECKING:
    from delphi.vault import Vault


def _parse_iso(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class ReminderStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS reminders ("
            "id TEXT PRIMARY KEY, text TEXT, due_at TEXT, done INTEGER)"
        )
        self._conn.commit()

    def add(self, text: str, due_at: str) -> Reminder:
        try:
            _parse_iso(due_at)
        except (ValueError, TypeError) as e:
            raise ValueError(f"due_at must be an ISO8601 date/time, got {due_at!r}") from e
        reminder = Reminder(id=uuid.uuid4().hex[:12], text=text, due_at=due_at, done=False)
        self._conn.execute(
            "INSERT INTO reminders (id, text, due_at, done) VALUES (?, ?, ?, ?)",
            (reminder.id, reminder.text, reminder.due_at, int(reminder.done)),
        )
        self._conn.commit()
        return reminder

    def list(self, include_done: bool = False) -> list[Reminder]:
        query = "SELECT id, text, due_at, done FROM reminders"
        if not include_done:
            query += " WHERE done = 0"
        query += " ORDER BY due_at ASC"
        cursor = self._conn.execute(query)
        return [
            Reminder(id=row[0], text=row[1], due_at=row[2], done=bool(row[3]))
            for row in cursor.fetchall()
        ]

    def complete(self, reminder_id: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,)
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def due(self, now: str) -> list[Reminder]:
        cursor = self._conn.execute(
            "SELECT id, text, due_at, done FROM reminders "
            "WHERE due_at <= ? AND done = 0 ORDER BY due_at ASC",
            (now,),
        )
        return [
            Reminder(id=row[0], text=row[1], due_at=row[2], done=bool(row[3]))
            for row in cursor.fetchall()
        ]


def daily_digest(vault: "Vault", reminders: ReminderStore, email_summary: str | None = None) -> str:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    end_of_today = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    recent_notes = []
    for note in vault.list_notes():
        try:
            updated = _parse_iso(note.updated_at)
        except (ValueError, TypeError):
            continue
        if updated >= cutoff:
            recent_notes.append(note)

    due_reminders = []
    for reminder in reminders.list(include_done=False):
        try:
            due = _parse_iso(reminder.due_at)
        except (ValueError, TypeError):
            continue
        if due <= end_of_today:
            due_reminders.append(reminder)

    lines = ["Here's your daily digest:"]

    if not recent_notes and not due_reminders:
        lines.append("Nothing new to report - no notes updated in the last 24h, no reminders due.")
    else:
        if recent_notes:
            lines.append("")
            lines.append(f"Notes updated in the last 24h ({len(recent_notes)}):")
            for note in recent_notes:
                lines.append(f"  - {note.title} ({note.id})")
        else:
            lines.append("")
            lines.append("Notes updated in the last 24h: none")

        if due_reminders:
            lines.append("")
            lines.append(f"Reminders due today or overdue ({len(due_reminders)}):")
            for reminder in due_reminders:
                lines.append(f"  - {reminder.text} (due {reminder.due_at})")
        else:
            lines.append("")
            lines.append("Reminders due today or overdue: none")

    if email_summary:
        lines.append("")
        lines.append("Email:")
        lines.append(f"  {email_summary}")

    return "\n".join(lines)
