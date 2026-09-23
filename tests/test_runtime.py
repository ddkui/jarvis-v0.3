from pathlib import Path

from delphi import runtime
from delphi.agent.core import _MAX_TOOL_ITERATIONS
from delphi.config import DelphiConfig


def _config(tmp_path: Path) -> DelphiConfig:
    vault_dir = tmp_path / "vault"
    return DelphiConfig(
        model="anthropic/claude-opus-5",
        vault_dir=vault_dir,
        db_path=vault_dir / ".delphi" / "memory.db",
        reminders_db_path=vault_dir / ".delphi" / "reminders.db",
    )


def test_build_agent_stack_returns_core_tools(tmp_path):
    _vault, _store, _reminders, tools = runtime.build_agent_stack(_config(tmp_path))
    names = {t.name for t in tools}
    assert {"search_notes", "add_note", "list_notes", "get_note", "delete_note"} <= names
    assert {"add_reminder", "list_reminders", "complete_reminder"} <= names
    assert {"remember", "forget", "list_memory"} <= names


def test_max_tool_iterations_default_without_computer_use(tmp_path):
    _vault, _store, _reminders, tools = runtime.build_agent_stack(_config(tmp_path))
    assert runtime.max_tool_iterations_for(tools) == _MAX_TOOL_ITERATIONS


def test_max_tool_iterations_raised_with_computer_use(tmp_path):
    from delphi.models import Tool

    tools = [
        Tool(name="computer_click", description="", input_schema={"type": "object", "properties": {}}, handler=lambda a: "")
    ]
    assert runtime.max_tool_iterations_for(tools) == runtime.COMPUTER_USE_MAX_TOOL_ITERATIONS


def test_max_tool_iterations_raised_with_code_tools(tmp_path):
    from delphi.models import Tool

    tools = [
        Tool(name="run_python", description="", input_schema={"type": "object", "properties": {}}, handler=lambda a: "")
    ]
    assert runtime.max_tool_iterations_for(tools) == runtime.COMPUTER_USE_MAX_TOOL_ITERATIONS


def test_max_tool_iterations_raised_with_self_update_tools(tmp_path):
    from delphi.models import Tool

    tools = [
        Tool(name="apply_pending_changes", description="", input_schema={"type": "object", "properties": {}}, handler=lambda a: "")
    ]
    assert runtime.max_tool_iterations_for(tools) == runtime.COMPUTER_USE_MAX_TOOL_ITERATIONS


def test_max_tool_iterations_not_raised_by_unrelated_list_tools(tmp_path):
    # list_notes/list_reminders/list_memory happen to share the "list_" prefix
    # with the new list_dir/list_own_dir tools - they must not trip the raised budget.
    _vault, _store, _reminders, tools = runtime.build_agent_stack(_config(tmp_path))
    assert {"list_notes", "list_reminders", "list_memory"} <= {t.name for t in tools}
    assert runtime.max_tool_iterations_for(tools) == _MAX_TOOL_ITERATIONS


def test_build_agent_stack_omits_code_and_self_update_tools_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_CODE", raising=False)
    monkeypatch.delenv("DELPHI_ENABLE_SELF_UPDATE", raising=False)
    _vault, _store, _reminders, tools = runtime.build_agent_stack(_config(tmp_path))
    names = {t.name for t in tools}
    assert "run_python" not in names
    assert "apply_pending_changes" not in names


def test_build_agent_stack_includes_code_tools_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    _vault, _store, _reminders, tools = runtime.build_agent_stack(_config(tmp_path))
    names = {t.name for t in tools}
    assert {"run_python", "run_shell", "read_file", "write_file", "list_dir"} <= names


def test_build_agent_stack_includes_self_update_tools_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    _vault, _store, _reminders, tools = runtime.build_agent_stack(_config(tmp_path))
    names = {t.name for t in tools}
    assert {"view_pending_changes", "run_own_tests", "apply_pending_changes"} <= names


def test_build_agent_constructs_delphi_agent(tmp_path):
    from delphi.agent.core import DelphiAgent

    agent = runtime.build_agent(_config(tmp_path))
    assert isinstance(agent, DelphiAgent)
    assert agent.model == "anthropic/claude-opus-5"


def test_build_agent_passes_fallback_models_through(tmp_path):
    config = _config(tmp_path)
    config.fallback_models = ["nvidia_nim/meta/llama3-70b-instruct"]

    agent = runtime.build_agent(config)

    assert agent.fallback_models == ["nvidia_nim/meta/llama3-70b-instruct"]


def test_build_agent_resumes_persisted_conversation_by_default(tmp_path):
    from delphi import conversation

    config = _config(tmp_path)
    saved = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    conversation.save_messages(config.vault_dir, saved)

    agent = runtime.build_agent(config)

    assert agent.messages == saved


def test_build_agent_resume_false_starts_empty_even_with_saved_history(tmp_path):
    from delphi import conversation

    config = _config(tmp_path)
    conversation.save_messages(config.vault_dir, [{"role": "user", "content": "hi"}])

    agent = runtime.build_agent(config, resume=False)

    assert agent.messages == []


def test_build_agent_includes_memory_facts_in_system_prompt(tmp_path):
    from delphi.memory import facts

    config = _config(tmp_path)
    facts.add_fact(config.vault_dir, "The user's name is Dan.")

    agent = runtime.build_agent(config)

    assert "The user's name is Dan." in agent.system_prompt


def test_build_agent_system_prompt_has_no_memory_section_when_empty(tmp_path):
    agent = runtime.build_agent(_config(tmp_path))
    from delphi.agent.prompts import SYSTEM_PROMPT

    assert agent.system_prompt == SYSTEM_PROMPT


def test_save_conversation_persists_agent_messages(tmp_path):
    from delphi import conversation

    config = _config(tmp_path)
    agent = runtime.build_agent(config)
    agent.messages = [{"role": "user", "content": "remember this"}]

    runtime.save_conversation(config, agent)

    assert conversation.load_messages(config.vault_dir) == agent.messages
