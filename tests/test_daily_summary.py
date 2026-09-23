import datetime
import threading
import time

import pytest

from delphi import daily_summary
from delphi.config import DelphiConfig


def _config(tmp_path):
    return DelphiConfig(
        model="anthropic/claude-opus-5",
        vault_dir=tmp_path,
        db_path=tmp_path / ".delphi" / "memory.db",
        reminders_db_path=tmp_path / ".delphi" / "reminders.db",
    )


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_DAILY_SUMMARY", raising=False)
    assert daily_summary.is_enabled() is False


def test_enabled_via_env(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_DAILY_SUMMARY", "1")
    assert daily_summary.is_enabled() is True


def test_should_speak_is_a_separate_opt_in(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_DAILY_SUMMARY_SPEAK", raising=False)
    assert daily_summary._should_speak() is False
    monkeypatch.setenv("DELPHI_ENABLE_DAILY_SUMMARY_SPEAK", "1")
    assert daily_summary._should_speak() is True


class TestParseTimes:
    def test_parses_valid_comma_separated_times(self):
        assert daily_summary._parse_times("08:00,20:00") == [
            datetime.time(8, 0),
            datetime.time(20, 0),
        ]

    def test_tolerates_surrounding_whitespace(self):
        assert daily_summary._parse_times(" 08:00 , 20:00 ") == [
            datetime.time(8, 0),
            datetime.time(20, 0),
        ]

    def test_skips_malformed_entries(self):
        assert daily_summary._parse_times("08:00,not-a-time,20:00") == [
            datetime.time(8, 0),
            datetime.time(20, 0),
        ]

    def test_skips_out_of_range_entries(self):
        assert daily_summary._parse_times("25:00,20:00") == [datetime.time(20, 0)]

    def test_empty_string_yields_no_times(self):
        assert daily_summary._parse_times("") == []

    def test_default_string_parses_cleanly(self):
        assert daily_summary._parse_times(daily_summary._DEFAULT_TIMES) == [
            datetime.time(8, 0),
            datetime.time(20, 0),
        ]


class TestSecondsUntilNext:
    _TIMES = [datetime.time(8, 0), datetime.time(20, 0)]

    def test_before_first_time_today(self):
        now = datetime.datetime(2026, 1, 1, 7, 0)
        assert daily_summary._seconds_until_next(self._TIMES, now) == 3600.0

    def test_between_the_two_times_picks_the_later_one_today(self):
        now = datetime.datetime(2026, 1, 1, 12, 0)
        assert daily_summary._seconds_until_next(self._TIMES, now) == 8 * 3600.0

    def test_after_both_times_picks_tomorrows_first_one(self):
        now = datetime.datetime(2026, 1, 1, 21, 0)
        assert daily_summary._seconds_until_next(self._TIMES, now) == 11 * 3600.0

    def test_exactly_at_a_configured_time_rolls_to_the_next_one(self):
        now = datetime.datetime(2026, 1, 1, 8, 0)
        assert daily_summary._seconds_until_next(self._TIMES, now) == 12 * 3600.0


def test_run_once_writes_a_note_and_returns_digest(monkeypatch, tmp_path):
    monkeypatch.setattr("delphi.tools.email_tools.summarize_inbox", lambda **k: None)
    config = _config(tmp_path)

    digest = daily_summary.run_once(config)

    assert "daily digest" in digest.lower()
    from delphi.vault import Vault

    notes = Vault(config.vault_dir).list_notes()
    assert len(notes) == 1
    assert notes[0].title.startswith("Daily summary - ")
    assert notes[0].content == digest


def test_run_once_includes_email_summary_when_available(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "delphi.tools.email_tools.summarize_inbox", lambda **k: "Inbox: 3 unread."
    )
    config = _config(tmp_path)

    digest = daily_summary.run_once(config)

    assert "Inbox: 3 unread." in digest


def test_run_once_skips_speaking_when_speak_flag_is_off_even_if_voice_enabled(monkeypatch, tmp_path):
    monkeypatch.delenv("DELPHI_ENABLE_DAILY_SUMMARY_SPEAK", raising=False)
    monkeypatch.setattr("delphi.tools.email_tools.summarize_inbox", lambda **k: None)
    monkeypatch.setattr("delphi.tts.is_enabled", lambda: True)
    spoken = []
    monkeypatch.setattr("delphi.tts.speak", lambda text, vault_dir: spoken.append(text))

    daily_summary.run_once(_config(tmp_path))

    assert spoken == []


def test_run_once_speaks_when_both_flags_are_on(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_DAILY_SUMMARY_SPEAK", "1")
    monkeypatch.setattr("delphi.tools.email_tools.summarize_inbox", lambda **k: None)
    monkeypatch.setattr("delphi.tts.is_enabled", lambda: True)
    spoken = []
    monkeypatch.setattr("delphi.tts.speak", lambda text, vault_dir: spoken.append(text))

    digest = daily_summary.run_once(_config(tmp_path))

    assert len(spoken) == 1
    assert spoken[0] in digest  # the spoken text is drawn from the digest itself


def test_run_once_skips_speaking_gracefully_when_tts_raises(monkeypatch, tmp_path):
    from delphi import tts

    monkeypatch.setenv("DELPHI_ENABLE_DAILY_SUMMARY_SPEAK", "1")
    monkeypatch.setattr("delphi.tools.email_tools.summarize_inbox", lambda **k: None)
    monkeypatch.setattr("delphi.tts.is_enabled", lambda: True)

    def _raise(text, vault_dir):
        raise tts.VoiceUnavailable("no audio player")

    monkeypatch.setattr("delphi.tts.speak", _raise)

    digest = daily_summary.run_once(_config(tmp_path))  # must not raise

    assert digest  # the run still completes and returns the digest


def test_run_background_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_DAILY_SUMMARY", raising=False)
    called = []
    monkeypatch.setattr(daily_summary, "run_once", lambda config: called.append(config))

    daily_summary.run_background(config=object())

    time.sleep(0.05)
    assert called == []
    assert threading.active_count() == 1  # only the main test thread


def test_run_background_starts_a_daemon_thread_when_enabled(monkeypatch):
    # Unlike listen.run_background (whose target function returns on its own once
    # mocked), daily_summary's loop body is an unconditional `while True` - running
    # it on a real thread would leak a thread that outlives this test and throws
    # off threading.active_count() assertions elsewhere (e.g. tests/test_listen.py).
    # So this captures the thread the same way tests/test_autoupdate.py does, and
    # runs its target directly, in this test's own thread, stopping it deliberately
    # after one cycle.
    monkeypatch.setenv("DELPHI_ENABLE_DAILY_SUMMARY", "1")
    captured = {}

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            captured["target"] = target
            captured["daemon"] = daemon

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(daily_summary.threading, "Thread", FakeThread)
    run_once_calls = []
    monkeypatch.setattr(daily_summary, "run_once", lambda config: run_once_calls.append(config))

    sleep_calls = []

    def fake_sleep(seconds):
        sleep_calls.append(seconds)
        if len(sleep_calls) > 1:
            raise StopIteration  # stop after one full cycle

    monkeypatch.setattr(daily_summary.time, "sleep", fake_sleep)

    daily_summary.run_background(config="the-config")

    assert captured["daemon"] is True
    assert captured["started"] is True

    with pytest.raises(StopIteration):
        captured["target"]()

    assert run_once_calls == ["the-config"]
