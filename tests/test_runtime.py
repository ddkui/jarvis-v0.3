from pathlib import Path

from jarvis import runtime
from jarvis.agent.core import _MAX_TOOL_ITERATIONS
from jarvis.config import JarvisConfig


def _config(tmp_path: Path) -> JarvisConfig:
    vault_dir = tmp_path / "vault"
    return JarvisConfig(
        model="anthropic/claude-opus-5",
        vault_dir=vault_dir,
        db_path=vault_dir / ".jarvis" / "memory.db",
        reminders_db_path=vault_dir / ".jarvis" / "reminders.db",
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
    from jarvis.models import Tool

    tools = [
        Tool(name="computer_click", description="", input_schema={"type": "object", "properties": {}}, handler=lambda a: "")
    ]
    assert runtime.max_tool_iterations_for(tools) == runtime.COMPUTER_USE_MAX_TOOL_ITERATIONS


def test_build_agent_constructs_jarvis_agent(tmp_path):
    from jarvis.agent.core import JarvisAgent

    agent = runtime.build_agent(_config(tmp_path))
    assert isinstance(agent, JarvisAgent)
    assert agent.model == "anthropic/claude-opus-5"


def test_build_agent_resumes_persisted_conversation_by_default(tmp_path):
    from jarvis import conversation

    config = _config(tmp_path)
    saved = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    conversation.save_messages(config.vault_dir, saved)

    agent = runtime.build_agent(config)

    assert agent.messages == saved


def test_build_agent_resume_false_starts_empty_even_with_saved_history(tmp_path):
    from jarvis import conversation

    config = _config(tmp_path)
    conversation.save_messages(config.vault_dir, [{"role": "user", "content": "hi"}])

    agent = runtime.build_agent(config, resume=False)

    assert agent.messages == []


def test_build_agent_includes_memory_facts_in_system_prompt(tmp_path):
    from jarvis.memory import facts

    config = _config(tmp_path)
    facts.add_fact(config.vault_dir, "The user's name is Dan.")

    agent = runtime.build_agent(config)

    assert "The user's name is Dan." in agent.system_prompt


def test_build_agent_system_prompt_has_no_memory_section_when_empty(tmp_path):
    agent = runtime.build_agent(_config(tmp_path))
    from jarvis.agent.prompts import SYSTEM_PROMPT

    assert agent.system_prompt == SYSTEM_PROMPT


def test_save_conversation_persists_agent_messages(tmp_path):
    from jarvis import conversation

    config = _config(tmp_path)
    agent = runtime.build_agent(config)
    agent.messages = [{"role": "user", "content": "remember this"}]

    runtime.save_conversation(config, agent)

    assert conversation.load_messages(config.vault_dir) == agent.messages
