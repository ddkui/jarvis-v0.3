from jarvis.cli import build_parser


def test_chat_command():
    args = build_parser().parse_args(["chat"])
    assert args.command == "chat"


def test_note_add_command():
    args = build_parser().parse_args(
        ["note", "add", "--title", "My Title", "--content", "Some content", "--tags", "a,b"]
    )
    assert args.command == "note"
    assert args.note_command == "add"
    assert args.title == "My Title"
    assert args.content == "Some content"
    assert args.tags == "a,b"


def test_note_add_command_without_tags():
    args = build_parser().parse_args(
        ["note", "add", "--title", "My Title", "--content", "Some content"]
    )
    assert args.tags is None


def test_note_list_command():
    args = build_parser().parse_args(["note", "list"])
    assert args.command == "note"
    assert args.note_command == "list"


def test_note_search_command():
    args = build_parser().parse_args(["note", "search", "vacation plans"])
    assert args.command == "note"
    assert args.note_command == "search"
    assert args.query == "vacation plans"


def test_note_show_command():
    args = build_parser().parse_args(["note", "show", "abc123"])
    assert args.command == "note"
    assert args.note_command == "show"
    assert args.note_id == "abc123"


def test_remind_add_command():
    args = build_parser().parse_args(
        ["remind", "add", "Buy milk", "--due", "2026-09-25T09:00:00+00:00"]
    )
    assert args.command == "remind"
    assert args.remind_command == "add"
    assert args.text == "Buy milk"
    assert args.due_at == "2026-09-25T09:00:00+00:00"


def test_remind_list_command_default():
    args = build_parser().parse_args(["remind", "list"])
    assert args.command == "remind"
    assert args.remind_command == "list"
    assert args.all is False


def test_remind_list_command_all():
    args = build_parser().parse_args(["remind", "list", "--all"])
    assert args.all is True


def test_remind_done_command():
    args = build_parser().parse_args(["remind", "done", "xyz789"])
    assert args.command == "remind"
    assert args.remind_command == "done"
    assert args.reminder_id == "xyz789"


def test_digest_command():
    args = build_parser().parse_args(["digest"])
    assert args.command == "digest"


def test_no_command_raises():
    import pytest

    with pytest.raises(SystemExit):
        build_parser().parse_args([])
