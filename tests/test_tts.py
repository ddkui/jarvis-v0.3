import sys
import types

import pytest

from jarvis import tts


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

    class FakeModel:
        sr = 24000

        def generate(self, text):
            if generate_fails:
                raise RuntimeError("model exploded")
            return f"wav-for:{text}"

    chatterbox_pkg = types.ModuleType("chatterbox")
    chatterbox_tts_module = types.ModuleType("chatterbox.tts")
    chatterbox_tts_module.ChatterboxTTS = types.SimpleNamespace(from_pretrained=lambda device: FakeModel())
    chatterbox_pkg.tts = chatterbox_tts_module
    monkeypatch.setitem(sys.modules, "chatterbox", chatterbox_pkg)
    monkeypatch.setitem(sys.modules, "chatterbox.tts", chatterbox_tts_module)

    return saved


@pytest.fixture(autouse=True)
def _reset_model_cache(monkeypatch):
    monkeypatch.setattr(tts, "_model", None)
    yield
    tts._model = None


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_ENABLE_VOICE", raising=False)
    assert tts.is_enabled() is False


def test_ensure_ready_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("JARVIS_ENABLE_VOICE", raising=False)
    with pytest.raises(tts.VoiceUnavailable, match="JARVIS_ENABLE_VOICE"):
        tts.ensure_ready()


def test_ensure_ready_raises_when_dependency_missing(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_VOICE", "1")
    monkeypatch.delitem(sys.modules, "chatterbox", raising=False)
    monkeypatch.delitem(sys.modules, "torch", raising=False)

    with pytest.raises(tts.VoiceUnavailable, match="isn't usable"):
        tts.ensure_ready()


def test_ensure_ready_succeeds_when_available(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch)

    tts.ensure_ready()


def test_synthesize_writes_generated_wav(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ENABLE_VOICE", "1")
    saved = _install_fake_torch_stack(monkeypatch)

    out = tmp_path / "out.wav"
    tts.synthesize("Hello **world**", out)

    assert saved["wav"] == "wav-for:Hello world"
    assert saved["sr"] == 24000
    assert str(out) == saved["path"]


def test_strip_markdown_removes_common_syntax():
    text = "**Bold** and `code` and # Heading and [a link](https://example.com)"
    assert tts._strip_markdown(text) == "Bold and code and  Heading and a link"


def test_strip_markdown_removes_code_blocks():
    text = "before\n```\ncode here\n```\nafter"
    assert tts._strip_markdown(text) == "before\n\nafter"


def test_speak_raises_voice_unavailable_on_synthesis_failure(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch, generate_fails=True)

    with pytest.raises(tts.VoiceUnavailable, match="synthesis failed"):
        tts.speak("hello")


def test_speak_empty_text_is_a_noop(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch)

    tts.speak("   ")


def test_speak_plays_audio_via_platform_player(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ENABLE_VOICE", "1")
    _install_fake_torch_stack(monkeypatch)

    played = []
    monkeypatch.setattr(tts.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tts.shutil, "which", lambda name: "/usr/bin/paplay" if name == "paplay" else None)
    monkeypatch.setattr(tts.subprocess, "run", lambda args, check: played.append(args))

    tts.speak("hello there")

    assert played
    assert played[0][0] == "paplay"


def test_play_raises_when_no_player_found(monkeypatch, tmp_path):
    monkeypatch.setattr(tts.platform, "system", lambda: "Linux")
    monkeypatch.setattr(tts.shutil, "which", lambda name: None)

    with pytest.raises(tts.VoiceUnavailable, match="No audio player found"):
        tts._play(tmp_path / "x.wav")
