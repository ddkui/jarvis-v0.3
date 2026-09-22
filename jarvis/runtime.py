"""Shared agent-construction logic used by every surface that runs a
JarvisAgent - the terminal chat (jarvis/cli.py) and the background web chat
(jarvis/dashboard.py) - so they stay wired to the exact same tool stack, memory
facts, and persisted conversation instead of drifting apart.
"""

from __future__ import annotations

from jarvis.config import JarvisConfig
from jarvis.memory.store import MemoryStore
from jarvis.scheduler.jobs import ReminderStore
from jarvis.tools import calendar_tools, computer_tools, email_tools, memory_tools, notes_tools, reminder_tools
from jarvis.vault import Vault

COMPUTER_USE_MAX_TOOL_ITERATIONS = 25


def build_agent_stack(config: JarvisConfig):
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
    from jarvis.agent.core import _MAX_TOOL_ITERATIONS

    computer_use_active = any(tool.name.startswith("computer_") for tool in tools)
    return COMPUTER_USE_MAX_TOOL_ITERATIONS if computer_use_active else _MAX_TOOL_ITERATIONS


def build_agent(config: JarvisConfig, resume: bool = True):
    """Build a ready-to-use JarvisAgent from a JarvisConfig: the full tool
    stack (notes, reminders, memory, calendar/email stubs, computer-use), a
    system prompt carrying whatever's currently remembered about the user, and
    - unless resume=False - the persisted conversation history loaded back in
    so this picks up where the last session left off."""
    from jarvis.agent.core import JarvisAgent
    from jarvis.agent.prompts import build_system_prompt
    from jarvis.memory import facts

    _vault, _store, _reminders, tools = build_agent_stack(config)
    memory_facts = [f.text for f in facts.list_facts(config.vault_dir)]

    agent = JarvisAgent(
        model=config.model,
        tools=tools,
        max_tool_iterations=max_tool_iterations_for(tools),
        system_prompt=build_system_prompt(memory_facts),
    )
    if resume:
        from jarvis import conversation

        agent.messages = conversation.load_messages(config.vault_dir)
    return agent


def save_conversation(config: JarvisConfig, agent) -> None:
    from jarvis import conversation

    conversation.save_messages(config.vault_dir, agent.messages)
