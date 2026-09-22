"""Extension point for a future Google Calendar integration.

Not implemented in this build. When wired up, this module should expose:

  - list_events(start, end): list calendar events in a time range.
  - create_event(title, start, end): create a new calendar event.

build_tools() returns [] unless GOOGLE_CALENDAR_CREDENTIALS is set in the
environment, in which case it raises NotImplementedError pointing here, since
the real OAuth-backed implementation has not been built yet.
"""

from __future__ import annotations

import os

from jarvis.models import Tool


def build_tools() -> list[Tool]:
    if os.environ.get("GOOGLE_CALENDAR_CREDENTIALS"):
        raise NotImplementedError(
            "GOOGLE_CALENDAR_CREDENTIALS is set, but the Google Calendar integration "
            "has not been implemented yet. Add the real list_events/create_event tools "
            "in jarvis/tools/calendar_tools.py."
        )
    return []
