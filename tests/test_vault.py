from jarvis.vault import Vault


def test_create_and_get_note(tmp_path):
    vault = Vault(tmp_path / "vault")
    note = vault.create_note("My First Note", "Hello world", tags=["intro"])

    fetched = vault.get_note(note.id)
    assert fetched is not None
    assert fetched.id == note.id
    assert fetched.title == "My First Note"
    assert fetched.content == "Hello world"
    assert fetched.tags == ["intro"]
    assert fetched.created_at == note.created_at
    assert fetched.updated_at == note.updated_at


def test_get_note_missing_returns_none(tmp_path):
    vault = Vault(tmp_path / "vault")
    assert vault.get_note("doesnotexist") is None


def test_update_note(tmp_path):
    vault = Vault(tmp_path / "vault")
    note = vault.create_note("Title", "Original content", tags=["a"])

    updated = vault.update_note(note.id, content="New content", tags=["a", "b"], title="New Title")
    assert updated is not None
    assert updated.content == "New content"
    assert updated.tags == ["a", "b"]
    assert updated.title == "New Title"
    assert updated.updated_at >= note.created_at

    refetched = vault.get_note(note.id)
    assert refetched.content == "New content"
    assert refetched.title == "New Title"


def test_update_note_missing_returns_none(tmp_path):
    vault = Vault(tmp_path / "vault")
    assert vault.update_note("nope", content="x") is None


def test_delete_note(tmp_path):
    vault = Vault(tmp_path / "vault")
    note = vault.create_note("To Delete", "content")

    assert vault.delete_note(note.id) is True
    assert vault.get_note(note.id) is None
    assert vault.delete_note(note.id) is False


def test_list_notes_ordering(tmp_path):
    vault = Vault(tmp_path / "vault")
    first = vault.create_note("First", "content 1")
    second = vault.create_note("Second", "content 2")
    third = vault.create_note("Third", "content 3")

    vault.update_note(first.id, content="updated content 1")

    notes = vault.list_notes()
    assert len(notes) == 3
    assert notes[0].id == first.id
    ids = {n.id for n in notes}
    assert ids == {first.id, second.id, third.id}
