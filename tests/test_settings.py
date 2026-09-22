from pathlib import Path

import pytest

from delphi import settings as voice_settings


def test_load_settings_defaults_when_missing(tmp_path: Path):
    settings = voice_settings.load_settings(tmp_path)
    assert settings.active_voice is None
    assert settings.exaggeration == 0.5
    assert settings.cfg_weight == 0.5
    assert settings.speaking_rate == 1.0
    assert settings.voices == {}


def test_save_then_load_round_trip(tmp_path: Path):
    original = voice_settings.VoiceSettings(
        active_voice="ada", exaggeration=1.1, cfg_weight=0.4, speaking_rate=1.3, voices={"ada": "/x/ada.wav"}
    )
    voice_settings.save_settings(tmp_path, original)

    loaded = voice_settings.load_settings(tmp_path)

    assert loaded == original


def test_load_settings_clamps_out_of_range_values_from_disk(tmp_path: Path):
    path = tmp_path / ".delphi" / "voice_settings.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"exaggeration": 99, "cfg_weight": -5, "speaking_rate": 10}')

    loaded = voice_settings.load_settings(tmp_path)

    assert loaded.exaggeration == voice_settings.EXAGGERATION_RANGE[1]
    assert loaded.cfg_weight == voice_settings.CFG_WEIGHT_RANGE[0]
    assert loaded.speaking_rate == voice_settings.SPEAKING_RATE_RANGE[1]


def test_load_settings_recovers_from_corrupt_json(tmp_path: Path):
    path = tmp_path / ".delphi" / "voice_settings.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not valid json")

    loaded = voice_settings.load_settings(tmp_path)

    assert loaded == voice_settings.VoiceSettings()


def test_clamp():
    assert voice_settings.clamp(5, (0, 2)) == 2
    assert voice_settings.clamp(-1, (0, 2)) == 0
    assert voice_settings.clamp(1, (0, 2)) == 1


def test_add_voice_copies_file_and_registers_it(tmp_path: Path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"fake-audio-bytes")

    dest = voice_settings.add_voice(tmp_path, "ada", source)

    assert dest.read_bytes() == b"fake-audio-bytes"
    assert dest.parent == tmp_path / ".delphi" / "voices"

    settings = voice_settings.load_settings(tmp_path)
    assert settings.voices["ada"] == str(dest)


def test_add_voice_rejects_empty_name(tmp_path: Path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"x")

    with pytest.raises(ValueError):
        voice_settings.add_voice(tmp_path, "   ", source)


def test_remove_voice_deletes_file_and_unregisters(tmp_path: Path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"x")
    dest = voice_settings.add_voice(tmp_path, "ada", source)

    assert voice_settings.remove_voice(tmp_path, "ada") is True
    assert not dest.exists()
    assert "ada" not in voice_settings.load_settings(tmp_path).voices


def test_remove_voice_clears_active_voice_if_it_was_active(tmp_path: Path):
    source = tmp_path / "source.wav"
    source.write_bytes(b"x")
    voice_settings.add_voice(tmp_path, "ada", source)
    settings = voice_settings.load_settings(tmp_path)
    settings.active_voice = "ada"
    voice_settings.save_settings(tmp_path, settings)

    voice_settings.remove_voice(tmp_path, "ada")

    assert voice_settings.load_settings(tmp_path).active_voice is None


def test_remove_voice_returns_false_when_not_found(tmp_path: Path):
    assert voice_settings.remove_voice(tmp_path, "does-not-exist") is False
