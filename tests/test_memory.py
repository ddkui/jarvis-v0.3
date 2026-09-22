from jarvis.memory.retrieval import retrieve_context
from jarvis.memory.store import MemoryStore
from jarvis.vault import Vault


def test_search_empty_store_returns_empty_list(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    assert store.search("anything") == []


def test_index_and_search_by_content_keyword(tmp_path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")

    note = vault.create_note("Recipe Ideas", "A great recipe for chocolate lava cake", tags=["cooking"])
    store.index_note(note)

    results = store.search("chocolate")
    assert len(results) == 1
    assert results[0].note_id == note.id
    assert results[0].title == "Recipe Ideas"
    assert "chocolate" in results[0].snippet.lower()


def test_index_and_search_by_tag(tmp_path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")

    note = vault.create_note("Project Plan", "Some unrelated content", tags=["urgent-project"])
    store.index_note(note)

    results = store.search("urgent-project")
    assert len(results) == 1
    assert results[0].note_id == note.id


def test_remove_note(tmp_path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")

    note = vault.create_note("Temp Note", "Some searchable text here")
    store.index_note(note)
    assert len(store.search("searchable")) == 1

    store.remove_note(note.id)
    assert store.search("searchable") == []


def test_search_with_fts5_special_characters_does_not_raise(tmp_path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")

    note = vault.create_note("Chat Log", "what's up with the plan")
    store.index_note(note)

    for query in ['"what\'s up?"', "AND", '"', "col:val OR *"]:
        results = store.search(query)
        assert isinstance(results, list)


def test_index_note_upsert_replaces_existing(tmp_path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")

    note = vault.create_note("Title", "original keyword banana")
    store.index_note(note)
    assert len(store.search("banana")) == 1

    updated = vault.update_note(note.id, content="replaced keyword mango")
    store.index_note(updated)

    assert store.search("banana") == []
    assert len(store.search("mango")) == 1


def test_retrieve_context_formats_results(tmp_path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")

    note = vault.create_note("Meeting Notes", "We discussed the quarterly budget in detail")
    store.index_note(note)

    context = retrieve_context(store, vault, "budget")
    assert f"[1] Meeting Notes (note_id: {note.id})" in context
    assert "budget" in context.lower()


def test_retrieve_context_returns_empty_string_when_no_matches(tmp_path):
    vault = Vault(tmp_path / "vault")
    store = MemoryStore(tmp_path / "memory.db")

    context = retrieve_context(store, vault, "nonexistentkeyword")
    assert context == ""
