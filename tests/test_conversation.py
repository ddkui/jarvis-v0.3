from pathlib import Path

from jarvis import conversation


def test_load_messages_empty_when_missing(tmp_path: Path):
    assert conversation.load_messages(tmp_path) == []


def test_save_then_load_round_trip(tmp_path: Path):
    messages = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "result"},
    ]
    conversation.save_messages(tmp_path, messages)

    assert conversation.load_messages(tmp_path) == messages


def test_load_messages_recovers_from_corrupt_json(tmp_path: Path):
    path = tmp_path / ".jarvis" / "conversation.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json")

    assert conversation.load_messages(tmp_path) == []


def test_load_messages_recovers_from_non_list_json(tmp_path: Path):
    path = tmp_path / ".jarvis" / "conversation.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"not": "a list"}')

    assert conversation.load_messages(tmp_path) == []


def test_clear_removes_the_file(tmp_path: Path):
    conversation.save_messages(tmp_path, [{"role": "user", "content": "hi"}])
    conversation.clear(tmp_path)

    assert conversation.load_messages(tmp_path) == []


def test_clear_is_a_noop_when_nothing_saved(tmp_path: Path):
    conversation.clear(tmp_path)
