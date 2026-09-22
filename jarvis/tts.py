"""Text-to-speech via Chatterbox (Resemble AI, MIT-licensed), for jarvis chat --speak.

Disabled by default: the model is large (~1-2GB download on first use) and slow to
run without a GPU. Enable with JARVIS_ENABLE_VOICE=1 plus the optional dependency
(`pip install -e .[voice]`). The model itself downloads from Hugging Face on first
use and is cached locally after that — see README.md "Voice output" for details.

Playback shells out to a platform audio player (afplay/paplay/aplay/ffplay/winsound)
rather than adding another native-audio Python dependency on top of an already heavy
one.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

_ENABLE_ENV_VAR = "JARVIS_ENABLE_VOICE"
_model = None


class VoiceUnavailable(Exception):
    """Raised when voice output can't be used right now (disabled, not installed,
    or the model failed to load) - always carries a human-readable reason."""


def is_enabled() -> bool:
    return os.environ.get(_ENABLE_ENV_VAR) == "1"


def _load_model():
    global _model
    if _model is not None:
        return _model
    import torch
    from chatterbox.tts import ChatterboxTTS

    device = "cuda" if torch.cuda.is_available() else "cpu"
    _model = ChatterboxTTS.from_pretrained(device=device)
    return _model


def ensure_ready() -> None:
    """Raise VoiceUnavailable with a clear reason if voice output can't run right
    now. Call this once at startup so a broken setup degrades to text-only instead
    of failing mid-conversation."""
    if not is_enabled():
        raise VoiceUnavailable(f"Set {_ENABLE_ENV_VAR}=1 to enable voice output.")
    try:
        _load_model()
    except Exception as e:
        raise VoiceUnavailable(f"Chatterbox isn't usable here: {e}") from e


def _strip_markdown(text: str) -> str:
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"[`*_#]", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.strip()


def synthesize(text: str, output_path: Path) -> Path:
    import torchaudio as ta

    model = _load_model()
    wav = model.generate(_strip_markdown(text))
    ta.save(str(output_path), wav, model.sr)
    return output_path


def _play(path: Path) -> None:
    system = platform.system()
    if system == "Darwin":
        subprocess.run(["afplay", str(path)], check=True)
        return
    if system == "Windows":
        import winsound

        winsound.PlaySound(str(path), winsound.SND_FILENAME)
        return
    for player, extra_args in (("paplay", []), ("aplay", []), ("ffplay", ["-nodisp", "-autoexit"])):
        if shutil.which(player):
            subprocess.run([player, *extra_args, str(path)], check=True)
            return
    raise VoiceUnavailable(
        "No audio player found (tried paplay, aplay, ffplay). "
        "Install one, e.g. `apt install pulseaudio-utils`."
    )


def speak(text: str) -> None:
    """Synthesize text and play it. Raises VoiceUnavailable on any failure - callers
    should catch it and fall back to text rather than crashing the chat session."""
    if not text.strip():
        return
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = Path(f.name)
    try:
        try:
            synthesize(text, path)
        except VoiceUnavailable:
            raise
        except Exception as e:
            raise VoiceUnavailable(f"Voice synthesis failed: {e}") from e
        _play(path)
    finally:
        path.unlink(missing_ok=True)
