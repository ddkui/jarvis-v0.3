"""Current date/time awareness for the agent.

An LLM has no live clock of its own - without this, Delphi has no way to
answer "what time is it" or reason accurately about "today"/"this week"/
"overdue" beyond whatever's in its training data. Always available, like
notes/reminders/memory - it's local-only (no network call, no privacy
exposure), unlike location below.
"""

from __future__ import annotations

from datetime import datetime

from delphi.models import Tool


def build_tools() -> list[Tool]:
    def get_current_time(input: dict) -> str:
        now = datetime.now().astimezone()
        return now.strftime("%A, %Y-%m-%d %H:%M:%S %Z (UTC%z)")

    return [
        Tool(
            name="get_current_time",
            description=(
                "Get the current local date and time, including day of week, and "
                "timezone offset. Use this whenever the user asks what time/day/date "
                "it is, or you need to reason about relative dates like 'today' or "
                "'this week', or whether a reminder is overdue."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=get_current_time,
        )
    ]
