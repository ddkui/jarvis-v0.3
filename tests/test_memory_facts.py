from pathlib import Path

import pytest

from jarvis.memory import facts


def test_list_facts_empty_when_missing(tmp_path: Path):
    assert facts.list_facts(tmp_path) == []


def test_add_then_list_fact(tmp_path: Path):
    fact = facts.add_fact(tmp_path, "The user's name is Dan.")

    items = facts.list_facts(tmp_path)
    assert len(items) == 1
    assert items[0].id == fact.id
    assert items[0].text == "The user's name is Dan."


def test_add_fact_strips_whitespace(tmp_path: Path):
    fact = facts.add_fact(tmp_path, "  likes concise answers  ")
    assert fact.text == "likes concise answers"


def test_add_fact_rejects_empty_text(tmp_path: Path):
    with pytest.raises(ValueError):
        facts.add_fact(tmp_path, "   ")


def test_remove_fact(tmp_path: Path):
    fact = facts.add_fact(tmp_path, "fact one")
    facts.add_fact(tmp_path, "fact two")

    assert facts.remove_fact(tmp_path, fact.id) is True
    remaining = facts.list_facts(tmp_path)
    assert len(remaining) == 1
    assert remaining[0].text == "fact two"


def test_remove_fact_returns_false_when_not_found(tmp_path: Path):
    assert facts.remove_fact(tmp_path, "does-not-exist") is False


def test_facts_capped_at_max_dropping_oldest(tmp_path: Path):
    for i in range(facts._MAX_FACTS + 5):
        facts.add_fact(tmp_path, f"fact {i}")

    items = facts.list_facts(tmp_path)
    assert len(items) == facts._MAX_FACTS
    assert items[0].text == "fact 5"
    assert items[-1].text == f"fact {facts._MAX_FACTS + 4}"


def test_list_facts_recovers_from_corrupt_json(tmp_path: Path):
    path = tmp_path / ".jarvis" / "memory_facts.json"
    path.parent.mkdir(parents=True)
    path.write_text("not json at all")

    assert facts.list_facts(tmp_path) == []
