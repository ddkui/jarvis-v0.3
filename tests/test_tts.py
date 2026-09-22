import sys
import types

import pytest

from delphi import settings as voice_settings
from delphi import tts


def _install_fake_torch_stack(monkeypatch, *, cuda_available=False, generate_fails=False):
    torch_module = types.ModuleType("torch")
    torch_module.cuda = types.SimpleNamespace(is_available=lambda: cuda_available)
    monkeypatch.setitem(sys.modules, "torch", torch_module)

    saved = {}
    torchaudio_module = types.ModuleType("torchaudio")

    def save(path, wav, sr):
        saved["path"] = path
        saved["wav"] = wav
        saved["sr"] = sr

    torchaudio_module.save = save
    monkeypatch.setitem(sys.modules, "torchaudio", torchaudio_module)

    generate_calls = []

    class FakeModel:
        sr = 24000

        def generate(self, text, audio_prompt_path=None, exaggeration=0.5, cfg_weight=0.5):
            generate_calls.append(
                {
                    "text": text,
                    "audio_prompt_path": audio_prompt_path,
                    "exaggeration": exaggeration,
                    "cfg_weight": cfg_weight,
                }
            )
            if generate_fails:
                raise RuntimeError("model exploded")
            return f"wav-for:{text}"

    chatterbox_pkg = types.ModuleType("chatterbox")
    chatterbox_tts_module = types.ModuleType("chatterbox.tts")
    chatterbox_tts_module.ChatterboxTTS = types.SimpleNamespace(from_pretrained=lambda device: FakeModel())
    chatterbox_pkg.tts = chatterbox_tts_module
    monkeypatch.setitem(sys.modules, "chatterbox", chatterbox_pkg)
    monkeypatch.setitem(sys.modules, "chatterbox.tts", chatterbox_tts_module)

    return saved, generate_calls


@pytest.fixture(autouse=True)
def _reset_model_cache(monkeypatch):
    monkeypatch.setattr(tts, "_model", None)
    yield
    tts._model = None


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_VOICE", raising=False)
    assert tts.is_enabled() is False


def test_ensure_ready_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_VOICE", raising=False)
    with pytest.raises(tts.VoiceUnavailable, match="DELPHI_ENABLE_VOICE"):
        tts.ensure_ready()


def test_ensure_ready_raises_when_dependency_missing(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    monkeypatch.delitem(sys.modules, "chatterbox", raising=False)
    monkeypatch.delitem(sys.modules, "torch", raising=False)

    with pytest.raises(tts.VoiceUnavailable, match="isn't usable"):
        tts.ensure_ready()


def test_ensure_ready_succeeds_when_available(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch)

    tts.ensure_ready()


def test_synthesize_writes_generated_wav(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    saved, _ = _install_fake_torch_stack(monkeypatch)

    out = tmp_path / "out.wav"
    tts.synthesize("Hello **world**", out, tmp_path)

    assert saved["wav"] == "wav-for:Hello world"
    assert saved["sr"] == 24000
    assert str(out) == saved["path"]


def test_synthesize_uses_default_settings_when_none_saved(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    _, generate_calls = _install_fake_torch_stack(monkeypatch)

    tts.synthesize("hi", tmp_path / "out.wav", tmp_path)

    assert generate_calls[-1]["audio_prompt_path"] is None
    assert generate_calls[-1]["exaggeration"] == 0.5
    assert generate_calls[-1]["cfg_weight"] == 0.5


def test_synthesize_uses_saved_voice_settings(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    _, generate_calls = _install_fake_torch_stack(monkeypatch)

    settings = voice_settings.VoiceSettings(
        active_voice="ada",
        exaggeration=1.2,
        cfg_weight=0.3,
        voices={"ada": "/path/to/ada.wav"},
    )
    voice_settings.save_settings(tmp_path, settings)

    tts.synthesize("hi", tmp_path / "out.wav", tmp_path)

    assert generate_calls[-1]["audio_prompt_path"] == "/path/to/ada.wav"
    assert generate_calls[-1]["exaggeration"] == 1.2
    assert generate_calls[-1]["cfg_weight"] == 0.3


def test_synthesize_applies_speaking_rate(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    saved, _ = _install_fake_torch_stack(monkeypatch)

    stretch_calls = []

    def fake_apply_speaking_rate(wav, rate):
        stretch_calls.append((wav, rate))
        return f"stretched:{wav}"

    monkeypatch.setattr(tts, "_apply_speaking_rate", fake_apply_speaking_rate)

    settings = voice_settings.VoiceSettings(speaking_rate=1.4)
    voice_settings.save_settings(tmp_path, settings)

    tts.synthesize("hi", tmp_path / "out.wav", tmp_path)

    assert stretch_calls == [("wav-for:hi", 1.4)]
    assert saved["wav"] == "stretched:wav-for:hi"


def test_apply_speaking_rate_noop_at_1x():
    assert tts._apply_speaking_rate("unchanged", 1.0) == "unchanged"


def test_apply_speaking_rate_uses_real_librosa_and_torch():
    import numpy as np

    silence = np.zeros(24000, dtype=np.float32)
    result = tts._apply_speaking_rate(silence, 1.5)

    assert result.shape[0] == 1
    assert result.shape[1] < len(silence)


def test_strip_markdown_removes_common_syntax():
    text = "**Bold** and `code` and # Heading and [a link](https://example.com)"
    assert tts._strip_markdown(text) == "Bold and code and  Heading and a link"


def test_strip_markdown_removes_code_blocks():
    text = "before\n```\ncode here\n```\nafter"
    assert tts._strip_markdown(text) == "before\n\nafter"


def test_speak_raises_voice_unavailable_on_synthesis_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch, generate_fails=True)

    with pytest.raises(tts.VoiceUnavailable, match="synthesis failed"):
        tts.speak("hello", tmp_path)


def test_speak_empty_text_is_a_noop(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch)

    tts.speak("   ", tmp_path)


def test_speak_plays_audio_via_platform_player(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch)

    played = []
    monkeypatch.setattr(tts.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/bin/paplay" if name == "paplay" else None)
    monkeypatch.setattr(tts.subprocess, "run", lambda args, check: played.append(args))

    tts.speak("hello there", tmp_path)

    assert played
    assert played[0][0] == "paplay"


def test_speak_wraps_playback_failure_as_voice_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch)

    monkeypatch.setattr(tts.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/bin/paplay" if name == "paplay" else None)

    import subprocess as real_subprocess

    def _raise(args, check):
        raise real_subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(tts.subprocess, "run", _raise)

    with pytest.raises(tts.VoiceUnavailable, match="playback failed"):
        tts.speak("hello there", tmp_path)


def test_play_raises_when_no_player_found(monkeypatch, tmp_path):
    monkeypatch.setattr(tts.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)

    with pytest.raises(tts.VoiceUnavailable, match="No audio player found"):
        tts._play(tmp_path / "x.wav")
