import threading
import time

from delphi import listen


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_WAKE_WORD", raising=False)
    assert listen.is_enabled() is False


def test_enabled_via_env(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_WAKE_WORD", "1")
    assert listen.is_enabled() is True


def test_ensure_ready_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_WAKE_WORD", raising=False)
    try:
        listen.ensure_ready()
        assert False, "expected WakeWordUnavailable"
    except listen.WakeWordUnavailable as e:
        assert "DELPHI_ENABLE_WAKE_WORD" in str(e)


def test_ensure_ready_raises_when_dependency_missing(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_WAKE_WORD", "1")
    try:
        listen.ensure_ready()
        assert False, "expected WakeWordUnavailable"
    except listen.WakeWordUnavailable as e:
        assert "pip install -e .[listen]" in str(e)


class TestConversationGate:
    def test_wake_word_with_command_in_same_utterance(self):
        gate = listen._ConversationGate("delphi")
        command, needs_prompt = gate.handle_transcript("Delphi, what time is it", now=0.0)
        assert command == "what time is it"
        assert needs_prompt is False

    def test_wake_word_alone_asks_for_follow_up(self):
        gate = listen._ConversationGate("delphi")
        command, needs_prompt = gate.handle_transcript("delphi", now=0.0)
        assert command is None
        assert needs_prompt is True

    def test_follow_up_within_window_becomes_the_command(self):
        gate = listen._ConversationGate("delphi", follow_up_window=8.0)
        gate.handle_transcript("delphi", now=0.0)
        command, needs_prompt = gate.handle_transcript("remind me to call mom", now=2.0)
        assert command == "remind me to call mom"
        assert needs_prompt is False

    def test_follow_up_after_window_expires_is_ignored(self):
        gate = listen._ConversationGate("delphi", follow_up_window=8.0)
        gate.handle_transcript("delphi", now=0.0)
        command, needs_prompt = gate.handle_transcript("remind me to call mom", now=20.0)
        assert command is None
        assert needs_prompt is False

    def test_transcript_without_wake_word_is_ignored(self):
        gate = listen._ConversationGate("delphi")
        command, needs_prompt = gate.handle_transcript("just some background chatter", now=0.0)
        assert command is None
        assert needs_prompt is False

    def test_wake_word_is_case_insensitive(self):
        gate = listen._ConversationGate("delphi")
        command, _ = gate.handle_transcript("DELPHI what's on my calendar", now=0.0)
        assert command == "what's on my calendar"

    def test_wake_word_mid_sentence(self):
        gate = listen._ConversationGate("delphi")
        command, _ = gate.handle_transcript("sorry, delphi, can you help", now=0.0)
        assert command == "can you help"

    def test_empty_transcript_does_nothing(self):
        gate = listen._ConversationGate("delphi")
        command, needs_prompt = gate.handle_transcript("   ", now=0.0)
        assert command is None
        assert needs_prompt is False

    def test_a_second_bare_wake_word_resets_the_follow_up_window(self):
        gate = listen._ConversationGate("delphi", follow_up_window=8.0)
        gate.handle_transcript("delphi", now=0.0)
        gate.handle_transcript("delphi", now=1.0)
        command, needs_prompt = gate.handle_transcript("what time is it", now=8.5)
        assert command == "what time is it"
        assert needs_prompt is False


class TestUtteranceSegmenter:
    def test_finalizes_an_utterance_after_speech_then_silence(self):
        segmenter = listen._UtteranceSegmenter(padding_frames=3, min_ratio=0.9)
        speech_frames = [f"s{i}".encode() for i in range(5)]
        silence_frames = [f"q{i}".encode() for i in range(3)]

        results = [segmenter.push(f, True) for f in speech_frames]
        assert all(r is None for r in results)

        *silence_results, last = [segmenter.push(f, False) for f in silence_frames]
        assert all(r is None for r in silence_results)
        # The trailing padding frames that confirmed silence are included in
        # the utterance too (same as the standard webrtcvad-collector
        # pattern) - Whisper handles a little trailing silence just fine.
        assert last == b"".join(speech_frames + silence_frames)

    def test_never_triggers_on_silence_alone(self):
        segmenter = listen._UtteranceSegmenter(padding_frames=3, min_ratio=0.9)
        results = [segmenter.push(f"q{i}".encode(), False) for i in range(10)]
        assert all(r is None for r in results)

    def test_captures_a_second_utterance_after_the_first_finalizes(self):
        segmenter = listen._UtteranceSegmenter(padding_frames=2, min_ratio=0.9)
        for f in [b"a", b"b"]:
            segmenter.push(f, True)
        for f in [b"x", b"y"]:
            segmenter.push(f, False)

        for f in [b"c", b"d"]:
            segmenter.push(f, True)
        results = [segmenter.push(f, False) for f in [b"x", b"y"]]
        assert results[-1] == b"cdxy"


def test_run_background_is_a_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_WAKE_WORD", raising=False)
    called = []
    monkeypatch.setattr(listen, "run", lambda config: called.append(config))

    listen.run_background(config=object())

    time.sleep(0.05)
    assert called == []
    assert threading.active_count() == 1  # only the main test thread


def test_run_background_starts_a_daemon_thread_when_enabled(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_WAKE_WORD", "1")
    started = threading.Event()
    monkeypatch.setattr(listen, "run", lambda config: started.set())

    listen.run_background(config=object())

    assert started.wait(timeout=2.0)
