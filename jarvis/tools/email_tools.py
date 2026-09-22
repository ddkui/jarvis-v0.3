"""Extension point for a future Gmail integration.

Not implemented in this build. When wired up, this module should expose:

  - search_email(query): search the user's mailbox.
  - send_email(to, subject, body): send an email on the user's behalf.

build_tools() returns [] unless GOOGLE_GMAIL_CREDENTIALS is set in the
environment, in which case it raises NotImplementedError pointing here, since
the real OAuth-backed implementation has not been built yet.
"""

from __future__ import annotations

import os

from jarvis.models import Tool


def build_tools() -> list[Tool]:
    if os.environ.get("GOOGLE_GMAIL_CREDENTIALS"):
        raise NotImplementedError(
            "GOOGLE_GMAIL_CREDENTIALS is set, but the Gmail integration has not been "
            "implemented yet. Add the real search_email/send_email tools in "
            "jarvis/tools/email_tools.py."
        )
    return []
