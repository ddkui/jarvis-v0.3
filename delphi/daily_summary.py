"""Automatic twice-daily Gmail + notes/reminders digest for `delphi tray`.

Off by default: this is a new proactive/scheduled behavior, so it needs
explicit opt-in (DELPHI_ENABLE_DAILY_SUMMARY=1) the same way the wake-word
listener (delphi/listen.py) does. Each run reuses the existing daily_digest()
(delphi/scheduler/jobs.py) plus email_tools.summarize_inbox(), writes the
result as a note in the vault, and - only if DELPHI_ENABLE_DAILY_SUMMARY_SPEAK
is *also* set, a separate opt-in from just enabling the summary - speaks a
short version aloud via delphi/tts.py.
"""

from __future__ import annotations

import datetime
import os
import sys
import threading
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from delphi.config import DelphiConfig

_ENABLE_ENV_VAR = "DELPHI_ENABLE_DAILY_SUMMARY"
_TIMES_ENV_VAR = "DELPHI_DAILY_SUMMARY_TIMES"
_SPEAK_ENV_VAR = "DELPHI_ENABLE_DAILY_SUMMARY_SPEAK"
_DEFAULT_TIMES = "08:00,20:00"
_SPOKEN_SUMMARY_MAX_CHARS = 500


def is_enabled() -> bool:
    return os.environ.get(_ENABLE_ENV_VAR) == "1"


def _should_speak() -> bool:
    return os.environ.get(_SPEAK_ENV_VAR) == "1"


def _log(message: str) -> None:
    print(f"[daily_summary] {message}", file=sys.stderr, flush=True)


def _parse_times(raw: str) -> list[datetime.time]:
    """Parse a comma-separated "HH:MM,HH:MM" string. Any entry that doesn't
    parse as a valid 24h time is skipped (logged, not fatal) rather than
    crashing the whole schedule over one typo."""
    times = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        hour_str, _, minute_str = chunk.partition(":")
        try:
            times.append(datetime.time(int(hour_str), int(minute_str)))
        except ValueError:
            _log(f"skipping unparseable time {chunk!r} in {_TIMES_ENV_VAR}")
    return times


def _configured_times() -> list[datetime.time]:
    times = _parse_times(os.environ.get(_TIMES_ENV_VAR, _DEFAULT_TIMES))
    if not times:
        _log(f"no valid times found in {_TIMES_ENV_VAR}; falling back to default {_DEFAULT_TIMES}")
        times = _parse_times(_DEFAULT_TIMES)
    return times


def _seconds_until_next(times: list[datetime.time], now: datetime.datetime) -> float:
    """Seconds until the next occurrence of any of the given times - today,
    if one is still ahead, else the earliest one tomorrow. Takes `now`
    explicitly so this is trivially testable without mocking the clock."""
    candidates = []
    for t in times:
        candidate = now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        if candidate <= now:
            candidate += datetime.timedelta(days=1)
        candidates.append(candidate)
    return (min(candidates) - now).total_seconds()


def run_once(config: "DelphiConfig") -> str:
    """Build the digest, save it as a note, and (if opted in) speak a short
    version of it. Never lets one bad piece (a Gmail hiccup, a TTS failure)
    stop the rest of the run - each is caught and logged on its own."""
    from delphi.scheduler.jobs import ReminderStore, daily_digest
    from delphi.tools import email_tools
    from delphi.vault import Vault

    vault = Vault(config.vault_dir)
    reminders = ReminderStore(config.reminders_db_path)

    try:
        email_summary = email_tools.summarize_inbox()
    except Exception as e:
        _log(f"email summary failed: {e}")
        email_summary = None

    digest = daily_digest(vault, reminders, email_summary=email_summary)

    try:
        vault.create_note(f"Daily summary - {datetime.datetime.now():%Y-%m-%d %H:%M}", digest)
    except Exception as e:
        _log(f"failed to save daily summary note: {e}")

    if _should_speak():
        from delphi import tts

        if tts.is_enabled():
            spoken = digest if len(digest) <= _SPOKEN_SUMMARY_MAX_CHARS else digest[:_SPOKEN_SUMMARY_MAX_CHARS] + "..."
            try:
                tts.speak(spoken, config.vault_dir)
            except tts.VoiceUnavailable as e:
                _log(f"speaking the summary failed: {e}")

    return digest


def run_background(config: "DelphiConfig") -> None:
    """Loop forever on a background daemon thread, running the summary at
    each configured time. No-op if disabled."""
    if not is_enabled():
        return
    times = _configured_times()

    def _loop() -> None:
        while True:
            time.sleep(_seconds_until_next(times, datetime.datetime.now()))
            try:
                run_once(config)
            except Exception as e:
                _log(f"run failed: {e}")

    threading.Thread(target=_loop, daemon=True).start()
