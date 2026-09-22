"""Shared agent-construction logic used by every surface that runs a
DelphiAgent - the terminal chat (delphi/cli.py) and the background web chat
(delphi/dashboard.py) - so they stay wired to the exact same tool stack, memory
facts, and persisted conversation instead of drifting apart.
"""

from __future__ import annotations

from delphi.config import DelphiConfig
from delphi.memory.store import MemoryStore
from delphi.scheduler.jobs import ReminderStore
from delphi.tools import calendar_tools, computer_tools, email_tools, memory_tools, notes_tools, reminder_tools
from delphi.vault import Vault

COMPUTER_USE_MAX_TOOL_ITERATIONS = 25


def build_agent_stack(config: DelphiConfig):
    vault = Vault(config.vault_dir)
    store = MemoryStore(config.db_path)
    reminders = ReminderStore(config.reminders_db_path)

    tools = []
    tools.extend(notes_tools.build_tools(vault, store))
    tools.extend(reminder_tools.build_tools(reminders))
    tools.extend(memory_tools.build_tools(config.vault_dir))
    tools.extend(calendar_tools.build_tools())
    tools.extend(email_tools.build_tools())
    tools.extend(computer_tools.build_tools())

    return vault, store, reminders, tools


def max_tool_iterations_for(tools) -> int:
    from delphi.agent.core import _MAX_TOOL_ITERATIONS

    computer_use_active = any(tool.name.startswith("computer_") for tool in tools)
    return COMPUTER_USE_MAX_TOOL_ITERATIONS if computer_use_active else _MAX_TOOL_ITERATIONS


def build_agent(config: DelphiConfig, resume: bool = True):
    """Build a ready-to-use DelphiAgent from a DelphiConfig: the full tool
    stack (notes, reminders, memory, calendar/email stubs, computer-use), a
    system prompt carrying whatever's currently remembered about the user, and
    - unless resume=False - the persisted conversation history loaded back in
    so this picks up where the last session left off."""
    from delphi.agent.core import DelphiAgent
    from delphi.agent.prompts import build_system_prompt
    from delphi.memory import facts

    _vault, _store, _reminders, tools = build_agent_stack(config)
    memory_facts = [f.text for f in facts.list_facts(config.vault_dir)]

    agent = DelphiAgent(
        model=config.model,
        tools=tools,
        max_tool_iterations=max_tool_iterations_for(tools),
        system_prompt=build_system_prompt(memory_facts),
    )
    if resume:
        from delphi import conversation

        agent.messages = conversation.load_messages(config.vault_dir)
    return agent


def save_conversation(config: DelphiConfig, agent) -> None:
    from delphi import conversation

    conversation.save_messages(config.vault_dir, agent.messages)
