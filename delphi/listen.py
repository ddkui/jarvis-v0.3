"""Hands-free wake-word voice input for `delphi tray` - say "Delphi" (or
whatever DELPHI_WAKE_WORD is set to) followed by a command, and it's sent to
the same agent/conversation as `delphi chat` and the dashboard, with the
reply spoken back if voice output is enabled.

Disabled by default: enable with DELPHI_ENABLE_WAKE_WORD=1 plus the optional
dependency (`pip install -e .[listen]`). See README.md "Wake-word voice
input" for details.

There's no pretrained wake-word model for an arbitrary word like "Delphi"
(engines like openWakeWord/Porcupine ship a fixed set of trained words), so
this takes a different approach: a lightweight voice-activity detector
(webrtcvad) segments the microphone stream into utterances, each utterance is
transcribed locally with Whisper (faster-whisper; GPU-accelerated if
available), and the transcript is checked for the wake word. This costs more
CPU/GPU per utterance than a dedicated wake-word model, but works with any
word with zero training and runs fully offline - nothing is sent anywhere
until the wake word is actually heard and a command follows it.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections import deque
from pathlib import Path

_ENABLE_ENV_VAR = "DELPHI_ENABLE_WAKE_WORD"
_WAKE_WORD_ENV_VAR = "DELPHI_WAKE_WORD"
_WHISPER_MODEL_ENV_VAR = "DELPHI_WHISPER_MODEL"
_DEFAULT_WAKE_WORD = "delphi"
_DEFAULT_WHISPER_MODEL = "small.en"

_SAMPLE_RATE = 16000
_FRAME_MS = 30
_FRAME_SIZE = _SAMPLE_RATE * _FRAME_MS // 1000  # samples per frame
_PADDING_FRAMES = 10  # ~300ms of pre-roll/trailing-silence lookback
_MIN_RATIO = 0.9  # fraction of padding frames that must agree to flip state
_FOLLOW_UP_WINDOW_SECONDS = 8.0  # how long "Yes?" waits for the actual command

_whisper_model = None


class WakeWordUnavailable(Exception):
    """Raised when wake-word listening can't run right now (disabled, not
    installed, or no usable microphone) - always carries a human-readable
    reason."""


def is_enabled() -> bool:
    return os.environ.get(_ENABLE_ENV_VAR) == "1"


def _log(message: str) -> None:
    print(f"[listen] {message}", file=sys.stderr, flush=True)


def _summarize(e: Exception) -> str:
    return str(e).splitlines()[0]


def ensure_ready() -> None:
    """Raise WakeWordUnavailable with a clear reason if wake-word listening
    can't run right now."""
    if not is_enabled():
        raise WakeWordUnavailable(f"Set {_ENABLE_ENV_VAR}=1 to enable wake-word listening.")
    try:
        import faster_whisper  # noqa: F401
        import sounddevice as sd
        import webrtcvad  # noqa: F401
    except ImportError as e:
        raise WakeWordUnavailable(
            f"Missing optional dependency ({e}). Run `pip install -e .[listen]`."
        ) from e
    try:
        sd.check_input_settings(samplerate=_SAMPLE_RATE, channels=1, dtype="int16")
    except Exception as e:
        raise WakeWordUnavailable(f"No usable microphone found: {e}") from e


class _ConversationGate:
    """Decides, from each transcribed utterance, whether there's a command to
    dispatch. Pure logic (no audio/model I/O) so it's cheap to unit-test.

    Two ways a command is recognized:
    - the wake word followed by something in the same utterance
      ("Delphi, what time is it" -> "what time is it")
    - the wake word alone, then a follow-up utterance within
      _FOLLOW_UP_WINDOW_SECONDS (mirrors "Delphi" ... <pause> ... "what time
      is it", so you don't have to cram the command into one breath).
    """

    def __init__(self, wake_word: str, follow_up_window: float = _FOLLOW_UP_WINDOW_SECONDS):
        self._wake_word = wake_word.strip().lower()
        self._follow_up_window = follow_up_window
        self._awaiting_command_until = 0.0

    def handle_transcript(self, transcript: str, now: float) -> tuple[str | None, bool]:
        """Returns (command, needs_prompt). command is the text to send to
        the agent, or None if nothing should happen. needs_prompt is True
        when the wake word was heard alone - the caller should acknowledge
        (e.g. speak "Yes?") and keep listening for the next utterance as the
        command."""
        text = transcript.strip()
        if not text:
            return None, False
        lower = text.lower()

        if self._wake_word in lower:
            idx = lower.index(self._wake_word)
            remainder = text[idx + len(self._wake_word):].strip(" ,.:;!?-—")
            if remainder:
                self._awaiting_command_until = 0.0
                return remainder, False
            self._awaiting_command_until = now + self._follow_up_window
            return None, True

        if now < self._awaiting_command_until:
            self._awaiting_command_until = 0.0
            return text, False

        return None, False


class _UtteranceSegmenter:
    """Turns a stream of (frame_bytes, is_speech) classifications into
    complete utterances, with pre-roll so the very start of speech (heard
    before enough frames flip the detector) isn't clipped off. Pure logic
    (VAD classification is injected), so it's testable without real audio."""

    def __init__(self, padding_frames: int = _PADDING_FRAMES, min_ratio: float = _MIN_RATIO):
        self._ring: deque[tuple[bytes, bool]] = deque(maxlen=padding_frames)
        self._min_ratio = min_ratio
        self._triggered = False
        self._voiced: list[bytes] = []

    def push(self, frame: bytes, is_speech: bool) -> bytes | None:
        """Feed one frame in. Returns the complete utterance's raw PCM bytes
        once enough trailing silence follows speech, else None."""
        self._ring.append((frame, is_speech))

        if not self._triggered:
            if len(self._ring) == self._ring.maxlen:
                speech_count = sum(1 for _, s in self._ring if s)
                if speech_count > self._min_ratio * self._ring.maxlen:
                    self._triggered = True
                    self._voiced = [f for f, _ in self._ring]
                    self._ring.clear()
            return None

        self._voiced.append(frame)
        if len(self._ring) == self._ring.maxlen:
            silence_count = sum(1 for _, s in self._ring if not s)
            if silence_count > self._min_ratio * self._ring.maxlen:
                utterance = b"".join(self._voiced)
                self._triggered = False
                self._voiced = []
                self._ring.clear()
                return utterance
        return None


def _load_whisper_model():
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    from faster_whisper import WhisperModel

    model_name = os.environ.get(_WHISPER_MODEL_ENV_VAR, _DEFAULT_WHISPER_MODEL)
    _whisper_model = WhisperModel(model_name, device="auto", compute_type="auto")
    return _whisper_model


def _transcribe(model, audio_bytes: bytes) -> str:
    import numpy as np

    audio = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
    segments, _info = model.transcribe(audio, language="en")
    return " ".join(seg.text.strip() for seg in segments).strip()


def _iter_utterances():
    import queue

    import sounddevice as sd
    import webrtcvad

    vad = webrtcvad.Vad(2)
    segmenter = _UtteranceSegmenter()
    frames: queue.Queue[bytes] = queue.Queue()

    def _callback(indata, _frame_count, _time_info, _status) -> None:
        frames.put(bytes(indata))

    with sd.RawInputStream(
        samplerate=_SAMPLE_RATE,
        blocksize=_FRAME_SIZE,
        dtype="int16",
        channels=1,
        callback=_callback,
    ):
        while True:
            frame = frames.get()
            is_speech = vad.is_speech(frame, _SAMPLE_RATE)
            utterance = segmenter.push(frame, is_speech)
            if utterance is not None:
                yield utterance


def _speak_if_possible(text: str, vault_dir: Path) -> None:
    from delphi import tts

    if not tts.is_enabled():
        return
    try:
        tts.speak(text, vault_dir)
    except tts.VoiceUnavailable as e:
        _log(f"voice reply failed: {_summarize(e)}")


def run(config) -> None:
    """Blocking loop: listen for the wake word forever, dispatch recognized
    commands to the same agent/conversation used by delphi chat and the
    dashboard, and speak replies back if voice output is enabled. Never
    raises past a per-utterance error - logs and keeps listening so one bad
    transcription or a transient model error doesn't kill the listener."""
    ensure_ready()

    from delphi import runtime
    from delphi.models import AgentAbort

    wake_word = os.environ.get(_WAKE_WORD_ENV_VAR, _DEFAULT_WAKE_WORD)
    agent = runtime.build_agent(config)
    whisper_model = _load_whisper_model()
    gate = _ConversationGate(wake_word)

    _log(f'ready - say "{wake_word}" followed by a command')
    for utterance in _iter_utterances():
        try:
            transcript = _transcribe(whisper_model, utterance)
        except Exception as e:
            _log(f"transcription failed: {_summarize(e)}")
            continue
        if not transcript:
            continue

        command, needs_prompt = gate.handle_transcript(transcript, time.monotonic())
        if needs_prompt:
            _log(f'heard "{wake_word}" - listening for a command...')
            _speak_if_possible("Yes?", config.vault_dir)
            continue
        if command is None:
            continue

        _log(f"command: {command}")
        try:
            reply = agent.send(command)
        except AgentAbort as e:
            runtime.save_conversation(config, agent)
            _log(f"stopped: {e}")
            continue
        except Exception as e:
            _log(f"that turn hit a problem: {_summarize(e)}")
            continue
        runtime.save_conversation(config, agent)
        _speak_if_possible(reply, config.vault_dir)


def run_background(config) -> None:
    """Start the wake-word listener on a background daemon thread. No-op if
    disabled. If it can't start at all (missing deps, no mic), logs one line
    and gives up rather than crashing the caller (delphi tray)."""
    if not is_enabled():
        return

    def _loop() -> None:
        try:
            run(config)
        except WakeWordUnavailable as e:
            _log(f"unavailable: {e}")
        except Exception as e:
            _log(f"stopped unexpectedly: {_summarize(e)}")

    threading.Thread(target=_loop, daemon=True).start()
