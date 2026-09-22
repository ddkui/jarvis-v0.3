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
