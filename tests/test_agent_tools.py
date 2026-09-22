from pathlib import Path

import pytest

from jarvis.memory.store import MemoryStore
from jarvis.vault import Vault
from jarvis.tools import calendar_tools, email_tools, memory_tools, notes_tools, reminder_tools


def _tools_by_name(tools):
    return {t.name: t for t in tools}


def test_add_note_then_search_notes(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")
    tools = _tools_by_name(notes_tools.build_tools(vault, store))

    add_result = tools["add_note"].handler(
        {"title": "Rocket Fuel Recipe", "content": "Mix hydrazine with dinitrogen tetroxide.", "tags": ["chemistry"]}
    )
    assert "Rocket Fuel Recipe" in add_result

    search_result = tools["search_notes"].handler({"query": "hydrazine"})
    assert "Rocket Fuel Recipe" in search_result


def test_delete_note_removes_from_vault_and_search_index(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")
    tools = _tools_by_name(notes_tools.build_tools(vault, store))

    add_result = tools["add_note"].handler({"title": "Temporary Note", "content": "Delete me soon."})
    note_id = add_result.split()[2].rstrip(":")

    delete_result = tools["delete_note"].handler({"note_id": note_id})
    assert "Deleted note" in delete_result

    assert vault.get_note(note_id) is None
    assert tools["search_notes"].handler({"query": "Delete me soon"}) == "No matching notes found."


def test_delete_note_missing_id(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")
    tools = _tools_by_name(notes_tools.build_tools(vault, store))

    result = tools["delete_note"].handler({"note_id": "does-not-exist"})
    assert "no note found" in result.lower()


def test_search_notes_no_match(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")
    tools = _tools_by_name(notes_tools.build_tools(vault, store))

    result = tools["search_notes"].handler({"query": "nonexistent"})
    assert result == "No matching notes found."


def test_list_notes_and_get_note(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")
    tools = _tools_by_name(notes_tools.build_tools(vault, store))

    tools["add_note"].handler({"title": "First Note", "content": "Body one"})
    tools["add_note"].handler({"title": "Second Note", "content": "Body two"})

    listing = tools["list_notes"].handler({})
    assert "First Note" in listing
    assert "Second Note" in listing

    note_id = listing.splitlines()[0].split(" | ")[0]
    detail = tools["get_note"].handler({"note_id": note_id})
    assert "Body" in detail

    missing = tools["get_note"].handler({"note_id": "does-not-exist"})
    assert "not found" in missing.lower() or "no note found" in missing.lower()


def test_add_note_missing_required_field_raises(tmp_path: Path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")
    tools = _tools_by_name(notes_tools.build_tools(vault, store))

    with pytest.raises(ValueError):
        tools["add_note"].handler({"title": "No content here"})


def test_add_reminder_then_list_reminders(tmp_path: Path):
    scheduler_jobs = pytest.importorskip("jarvis.scheduler.jobs")
    reminders = scheduler_jobs.ReminderStore(tmp_path / "reminders.db")
    tools = _tools_by_name(reminder_tools.build_tools(reminders))

    add_result = tools["add_reminder"].handler(
        {"text": "Water the plants", "due_at": "2026-09-23T09:00:00"}
    )
    assert "Water the plants" in add_result

    listing = tools["list_reminders"].handler({})
    assert "Water the plants" in listing
    assert "pending" in listing

    reminder_id = listing.split(" | ")[0]
    complete_result = tools["complete_reminder"].handler({"reminder_id": reminder_id})
    assert "done" in complete_result.lower()

    listing_after = tools["list_reminders"].handler({})
    assert "Water the plants" not in listing_after

    listing_with_done = tools["list_reminders"].handler({"include_done": True})
    assert "Water the plants" in listing_with_done


def test_complete_reminder_missing_id(tmp_path: Path):
    scheduler_jobs = pytest.importorskip("jarvis.scheduler.jobs")
    reminders = scheduler_jobs.ReminderStore(tmp_path / "reminders.db")
    tools = _tools_by_name(reminder_tools.build_tools(reminders))

    result = tools["complete_reminder"].handler({"reminder_id": "nope"})
    assert "no reminder found" in result.lower()


def test_calendar_tools_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GOOGLE_CALENDAR_CREDENTIALS", raising=False)
    assert calendar_tools.build_tools() == []


def test_calendar_tools_raises_when_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CALENDAR_CREDENTIALS", "some-path.json")
    with pytest.raises(NotImplementedError):
        calendar_tools.build_tools()


def test_email_tools_disabled_by_default(monkeypatch):
    monkeypatch.delenv("GOOGLE_GMAIL_CREDENTIALS", raising=False)
    assert email_tools.build_tools() == []


def test_email_tools_raises_when_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", "some-path.json")
    with pytest.raises(NotImplementedError):
        email_tools.build_tools()


def test_remember_then_list_memory(tmp_path: Path):
    tools = _tools_by_name(memory_tools.build_tools(tmp_path))

    remember_result = tools["remember"].handler({"text": "The user's name is Dan."})
    assert "Remembered" in remember_result

    listing = tools["list_memory"].handler({})
    assert "The user's name is Dan." in listing


def test_list_memory_empty(tmp_path: Path):
    tools = _tools_by_name(memory_tools.build_tools(tmp_path))
    assert tools["list_memory"].handler({}) == "Nothing remembered yet."


def test_remember_then_forget(tmp_path: Path):
    tools = _tools_by_name(memory_tools.build_tools(tmp_path))

    remember_result = tools["remember"].handler({"text": "likes dark mode"})
    fact_id = remember_result.split("(")[1].split(")")[0]

    forget_result = tools["forget"].handler({"fact_id": fact_id})
    assert "Forgot memory" in forget_result
    assert tools["list_memory"].handler({}) == "Nothing remembered yet."


def test_forget_missing_id(tmp_path: Path):
    tools = _tools_by_name(memory_tools.build_tools(tmp_path))
    result = tools["forget"].handler({"fact_id": "does-not-exist"})
    assert "no memory found" in result.lower()


def test_remember_missing_text_raises(tmp_path: Path):
    tools = _tools_by_name(memory_tools.build_tools(tmp_path))
    with pytest.raises(ValueError):
        tools["remember"].handler({})
