from delphi.cli import (
    _run_turn,
    _summarize,
    build_parser,
    cmd_auth_delete,
    cmd_auth_list,
    cmd_auth_set,
    cmd_note_add,
    cmd_note_delete,
    console,
)


def test_chat_command():
    args = build_parser().parse_args(["chat"])
    assert args.command == "chat"
    assert args.speak is False
    assert args.new is False


def test_chat_command_with_speak_flag():
    args = build_parser().parse_args(["chat", "--speak"])
    assert args.speak is True


def test_chat_command_with_new_flag():
    args = build_parser().parse_args(["chat", "--new"])
    assert args.new is True


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


def test_note_delete_command():
    args = build_parser().parse_args(["note", "delete", "abc123"])
    assert args.command == "note"
    assert args.note_command == "delete"
    assert args.note_id == "abc123"


def test_cmd_note_delete_removes_note_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_VAULT_DIR", str(tmp_path / "vault"))
    monkeypatch.delenv("DELPHI_DB_PATH", raising=False)

    add_args = build_parser().parse_args(
        ["note", "add", "--title", "Throwaway", "--content", "Delete me via CLI"]
    )
    cmd_note_add(add_args)

    from delphi.vault import Vault
    from delphi.config import load_config

    config = load_config()
    note_id = Vault(config.vault_dir).list_notes()[0].id

    delete_args = build_parser().parse_args(["note", "delete", note_id])
    assert cmd_note_delete(delete_args) == 0
    assert Vault(config.vault_dir).list_notes() == []

    missing_args = build_parser().parse_args(["note", "delete", "does-not-exist"])
    assert cmd_note_delete(missing_args) == 1


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


def test_memory_list_command():
    args = build_parser().parse_args(["memory", "list"])
    assert args.command == "memory"
    assert args.memory_command == "list"


def test_memory_forget_command():
    args = build_parser().parse_args(["memory", "forget", "abc123"])
    assert args.command == "memory"
    assert args.memory_command == "forget"
    assert args.fact_id == "abc123"


def test_cmd_memory_list_and_forget_end_to_end(monkeypatch, tmp_path, capsys):
    from delphi.cli import cmd_memory_forget, cmd_memory_list
    from delphi.memory import facts

    monkeypatch.setenv("DELPHI_VAULT_DIR", str(tmp_path))
    monkeypatch.delenv("DELPHI_DB_PATH", raising=False)

    from delphi.config import load_config

    config = load_config()
    fact = facts.add_fact(config.vault_dir, "The user's name is Dan.")

    assert cmd_memory_list(build_parser().parse_args(["memory", "list"])) == 0
    output = capsys.readouterr().out
    assert "Dan" in output

    assert cmd_memory_forget(build_parser().parse_args(["memory", "forget", fact.id])) == 0
    assert cmd_memory_forget(build_parser().parse_args(["memory", "forget", "nope"])) == 1

    assert cmd_memory_list(build_parser().parse_args(["memory", "list"])) == 0
    output = capsys.readouterr().out
    assert "Nothing remembered yet." in output


def test_dashboard_command_defaults():
    args = build_parser().parse_args(["dashboard"])
    assert args.command == "dashboard"
    assert args.port == 8734
    assert args.no_browser is False


def test_dashboard_command_with_options():
    args = build_parser().parse_args(["dashboard", "--port", "9000", "--no-browser"])
    assert args.port == 9000
    assert args.no_browser is True


def test_tray_command_defaults():
    args = build_parser().parse_args(["tray"])
    assert args.command == "tray"
    assert args.port == 8734


def test_tray_command_with_port():
    args = build_parser().parse_args(["tray", "--port", "9001"])
    assert args.port == 9001


def test_install_launcher_command():
    args = build_parser().parse_args(["install-launcher"])
    assert args.command == "install-launcher"


def test_no_command_raises():
    import pytest

    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_summarize_keeps_only_first_line():
    error = Exception("short reason\nTraceback (most recent call last):\n  File ...")
    assert _summarize(error) == "short reason"


def test_summarize_single_line_message_unchanged():
    assert _summarize(Exception("plain message")) == "plain message"


def test_auth_set_command():
    args = build_parser().parse_args(["auth", "set", "ANTHROPIC_API_KEY"])
    assert args.command == "auth"
    assert args.auth_command == "set"
    assert args.name == "ANTHROPIC_API_KEY"


def test_auth_list_command():
    args = build_parser().parse_args(["auth", "list"])
    assert args.command == "auth"
    assert args.auth_command == "list"


def test_auth_delete_command():
    args = build_parser().parse_args(["auth", "delete", "GEMINI_API_KEY"])
    assert args.command == "auth"
    assert args.auth_command == "delete"
    assert args.name == "GEMINI_API_KEY"


def test_cmd_auth_set_stores_entered_value(monkeypatch):
    stored = {}
    monkeypatch.setattr(console, "input", lambda *a, **k: "sk-ant-typed")
    monkeypatch.setattr("delphi.cli.secrets.set_secret", lambda name, value: stored.__setitem__(name, value))

    args = build_parser().parse_args(["auth", "set", "ANTHROPIC_API_KEY"])
    assert cmd_auth_set(args) == 0
    assert stored == {"ANTHROPIC_API_KEY": "sk-ant-typed"}


def test_cmd_auth_set_empty_value_not_stored(monkeypatch):
    monkeypatch.setattr(console, "input", lambda *a, **k: "")

    def _fail(*_a, **_k):
        raise AssertionError("set_secret should not be called for an empty value")

    monkeypatch.setattr("delphi.cli.secrets.set_secret", _fail)

    args = build_parser().parse_args(["auth", "set", "ANTHROPIC_API_KEY"])
    assert cmd_auth_set(args) == 1


def test_cmd_auth_list_shows_stored_state(monkeypatch, capsys):
    monkeypatch.setattr(
        "delphi.cli.secrets.get_secret",
        lambda name: "value" if name == "ANTHROPIC_API_KEY" else None,
    )

    assert cmd_auth_list(build_parser().parse_args(["auth", "list"])) == 0
    output = capsys.readouterr().out
    assert "ANTHROPIC_API_KEY" in output
    assert "GEMINI_API_KEY" in output


def test_cmd_auth_delete_reports_success_and_failure(monkeypatch):
    monkeypatch.setattr("delphi.cli.secrets.delete_secret", lambda name: name == "ANTHROPIC_API_KEY")

    assert cmd_auth_delete(build_parser().parse_args(["auth", "delete", "ANTHROPIC_API_KEY"])) == 0
    assert cmd_auth_delete(build_parser().parse_args(["auth", "delete", "GEMINI_API_KEY"])) == 1


def test_conversation_persists_across_agent_rebuilds(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from delphi import runtime
    from delphi.config import DelphiConfig

    config = DelphiConfig(
        model="anthropic/claude-opus-5",
        vault_dir=tmp_path,
        db_path=tmp_path / ".delphi" / "memory.db",
        reminders_db_path=tmp_path / ".delphi" / "reminders.db",
    )

    def fake_completion(**kwargs):
        delta = SimpleNamespace(content="Hi there!", tool_calls=None)
        return iter([SimpleNamespace(choices=[SimpleNamespace(delta=delta)])])

    monkeypatch.setattr("delphi.agent.core.litellm.completion", fake_completion)

    agent = runtime.build_agent(config)
    _run_turn(agent, "hello delphi")
    runtime.save_conversation(config, agent)

    resumed_agent = runtime.build_agent(config)
    assert resumed_agent.messages == agent.messages
    assert resumed_agent.messages[0] == {"role": "user", "content": "hello delphi"}
    assert resumed_agent.messages[1] == {"role": "assistant", "content": "Hi there!"}


def test_new_flag_clears_persisted_conversation(tmp_path):
    from delphi import conversation, runtime
    from delphi.config import DelphiConfig

    config = DelphiConfig(
        model="anthropic/claude-opus-5",
        vault_dir=tmp_path,
        db_path=tmp_path / ".delphi" / "memory.db",
        reminders_db_path=tmp_path / ".delphi" / "reminders.db",
    )
    conversation.save_messages(config.vault_dir, [{"role": "user", "content": "old conversation"}])

    args = build_parser().parse_args(["chat", "--new"])
    assert args.new is True
    conversation.clear(config.vault_dir)  # what cmd_chat does when args.new is set

    fresh_agent = runtime.build_agent(config)
    assert fresh_agent.messages == []
