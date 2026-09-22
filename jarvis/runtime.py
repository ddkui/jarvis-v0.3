"""Shared agent-construction logic used by every surface that runs a
JarvisAgent - the terminal chat (jarvis/cli.py) and the background web chat
(jarvis/dashboard.py) - so they stay wired to the exact same tool stack instead
of two copies drifting apart.
"""

from __future__ import annotations

from jarvis.config import JarvisConfig
from jarvis.memory.store import MemoryStore
from jarvis.scheduler.jobs import ReminderStore
from jarvis.tools import calendar_tools, computer_tools, email_tools, notes_tools, reminder_tools
from jarvis.vault import Vault

COMPUTER_USE_MAX_TOOL_ITERATIONS = 25


def build_agent_stack(config: JarvisConfig):
    vault = Vault(config.vault_dir)
    store = MemoryStore(config.db_path)
    reminders = ReminderStore(config.reminders_db_path)

    tools = []
    tools.extend(notes_tools.build_tools(vault, store))
    tools.extend(reminder_tools.build_tools(reminders))
    tools.extend(calendar_tools.build_tools())
    tools.extend(email_tools.build_tools())
    tools.extend(computer_tools.build_tools())

    return vault, store, reminders, tools


def max_tool_iterations_for(tools) -> int:
    from jarvis.agent.core import _MAX_TOOL_ITERATIONS

    computer_use_active = any(tool.name.startswith("computer_") for tool in tools)
    return COMPUTER_USE_MAX_TOOL_ITERATIONS if computer_use_active else _MAX_TOOL_ITERATIONS


def build_agent(config: JarvisConfig):
    """Build a ready-to-use JarvisAgent from a JarvisConfig, wired up with the
    full tool stack (notes, reminders, calendar/email stubs, computer-use)."""
    from jarvis.agent.core import JarvisAgent

    _vault, _store, _reminders, tools = build_agent_stack(config)
    return JarvisAgent(model=config.model, tools=tools, max_tool_iterations=max_tool_iterations_for(tools))
