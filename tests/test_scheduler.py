from datetime import datetime, timedelta, timezone

import pytest

from delphi.models import Note
from delphi.scheduler.jobs import ReminderStore, daily_digest


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_reminder_store_add_and_list(tmp_path):
    store = ReminderStore(tmp_path / "reminders.db")
    r1 = store.add("Buy milk", "2026-09-25T09:00:00+00:00")
    r2 = store.add("Call dentist", "2026-09-23T09:00:00+00:00")

    items = store.list()

    assert [item.id for item in items] == [r2.id, r1.id]
    assert items[0].text == "Call dentist"
    assert all(not item.done for item in items)


def test_reminder_store_complete(tmp_path):
    store = ReminderStore(tmp_path / "reminders.db")
    reminder = store.add("Buy milk", "2026-09-25T09:00:00+00:00")

    assert store.complete(reminder.id) is True
    assert store.complete("does-not-exist") is False

    active = store.list(include_done=False)
    assert active == []

    everything = store.list(include_done=True)
    assert len(everything) == 1
    assert everything[0].done is True


def test_reminder_store_add_rejects_non_iso_due_at(tmp_path):
    store = ReminderStore(tmp_path / "reminders.db")

    with pytest.raises(ValueError, match="ISO8601"):
        store.add("Buy milk", "next Tuesday")

    assert store.list() == []


def test_reminder_store_due(tmp_path):
    store = ReminderStore(tmp_path / "reminders.db")
    overdue = store.add("Overdue task", "2026-01-01T00:00:00+00:00")
    store.add("Future task", "2099-01-01T00:00:00+00:00")

    due = store.due("2026-09-22T12:00:00+00:00")

    assert [item.id for item in due] == [overdue.id]


class _FakeVault:
    def __init__(self, notes):
        self._notes = notes

    def list_notes(self):
        return self._notes


def _make_note(note_id: str, title: str, updated_at: str) -> Note:
    return Note(
        id=note_id,
        title=title,
        content="content",
        tags=[],
        created_at=updated_at,
        updated_at=updated_at,
        path=f"{note_id}.md",
    )


def test_daily_digest_with_notes_and_reminders(tmp_path):
    now = datetime.now(timezone.utc)
    recent_note = _make_note("abc123", "Recent Note", _iso(now - timedelta(hours=2)))
    old_note = _make_note("def456", "Old Note", _iso(now - timedelta(days=5)))
    vault = _FakeVault([recent_note, old_note])

    reminders = ReminderStore(tmp_path / "reminders.db")
    due_reminder = reminders.add("Overdue thing", _iso(now - timedelta(days=1)))
    reminders.add("Far future thing", _iso(now + timedelta(days=30)))

    digest = daily_digest(vault, reminders)

    assert "Recent Note" in digest
    assert "abc123" in digest
    assert "Old Note" not in digest
    assert "Overdue thing" in digest
    assert due_reminder.due_at in digest
    assert "Far future thing" not in digest


def test_daily_digest_empty(tmp_path):
    vault = _FakeVault([])
    reminders = ReminderStore(tmp_path / "reminders.db")

    digest = daily_digest(vault, reminders)

    assert "Nothing new to report" in digest
