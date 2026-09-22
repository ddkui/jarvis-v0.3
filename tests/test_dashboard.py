import io

import pytest

from jarvis import settings as voice_settings
from jarvis import tts
from jarvis.dashboard import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path)
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, tmp_path


def test_index_renders_defaults(client):
    c, _ = client
    res = c.get("/")
    assert res.status_code == 200
    assert b"Voice Settings" in res.data
    assert b"Default (Chatterbox built-in)" in res.data


def test_index_warns_when_voice_disabled(client, monkeypatch):
    c, _ = client
    monkeypatch.delenv("JARVIS_ENABLE_VOICE", raising=False)
    res = c.get("/")
    assert b"Voice output isn" in res.data


def test_update_settings_persists(client):
    c, vault_dir = client
    res = c.post(
        "/settings",
        data={"active_voice": "", "exaggeration": "1.2", "cfg_weight": "0.3", "speaking_rate": "1.4"},
    )
    assert res.status_code == 200
    assert res.get_json()["ok"] is True

    saved = voice_settings.load_settings(vault_dir)
    assert saved.exaggeration == 1.2
    assert saved.cfg_weight == 0.3
    assert saved.speaking_rate == 1.4


def test_update_settings_clamps_out_of_range(client):
    c, vault_dir = client
    c.post("/settings", data={"exaggeration": "99", "cfg_weight": "-5", "speaking_rate": "10"})

    saved = voice_settings.load_settings(vault_dir)
    assert saved.exaggeration == voice_settings.EXAGGERATION_RANGE[1]
    assert saved.cfg_weight == voice_settings.CFG_WEIGHT_RANGE[0]
    assert saved.speaking_rate == voice_settings.SPEAKING_RATE_RANGE[1]


def test_update_settings_rejects_unknown_active_voice(client):
    c, vault_dir = client
    res = c.post("/settings", data={"active_voice": "nonexistent"})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False
    assert voice_settings.load_settings(vault_dir).active_voice is None


def test_update_settings_rejects_non_numeric_values(client):
    c, _ = client
    res = c.post("/settings", data={"exaggeration": "not-a-number"})
    assert res.status_code == 400


def test_upload_voice_registers_it(client):
    c, vault_dir = client
    data = {"name": "ada", "file": (io.BytesIO(b"fake-wav-bytes"), "ada.wav")}
    res = c.post("/voices", data=data, content_type="multipart/form-data")

    assert res.status_code == 200
    assert res.get_json()["ok"] is True
    settings = voice_settings.load_settings(vault_dir)
    assert "ada" in settings.voices
    assert open(settings.voices["ada"], "rb").read() == b"fake-wav-bytes"


def test_upload_voice_requires_name_and_file(client):
    c, _ = client
    res = c.post("/voices", data={"name": "ada"}, content_type="multipart/form-data")
    assert res.status_code == 400


def test_upload_then_select_then_delete_voice(client):
    c, vault_dir = client
    data = {"name": "ada", "file": (io.BytesIO(b"x"), "ada.wav")}
    c.post("/voices", data=data, content_type="multipart/form-data")

    res = c.post("/settings", data={"active_voice": "ada"})
    assert res.get_json()["ok"] is True
    assert voice_settings.load_settings(vault_dir).active_voice == "ada"

    res = c.post("/voices/ada/delete")
    assert res.get_json()["ok"] is True
    settings = voice_settings.load_settings(vault_dir)
    assert "ada" not in settings.voices
    assert settings.active_voice is None


def test_delete_voice_not_found_returns_false(client):
    c, _ = client
    res = c.post("/voices/does-not-exist/delete")
    assert res.get_json()["ok"] is False


def test_preview_returns_error_when_voice_disabled(client, monkeypatch):
    c, _ = client
    monkeypatch.delenv("JARVIS_ENABLE_VOICE", raising=False)

    res = c.post("/preview", data={"text": "hello"})

    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_preview_uses_unsaved_form_values_not_saved_settings(client, monkeypatch):
    c, vault_dir = client
    # Save one set of settings...
    voice_settings.save_settings(vault_dir, voice_settings.VoiceSettings(exaggeration=0.5, cfg_weight=0.5))

    captured = {}

    def fake_ensure_ready():
        return None

    def fake_synthesize(text, output_path, vault_dir_arg, settings=None):
        captured["settings"] = settings
        output_path.write_bytes(b"RIFFfake-wav-data")
        return output_path

    monkeypatch.setattr(tts, "ensure_ready", fake_ensure_ready)
    monkeypatch.setattr(tts, "synthesize", fake_synthesize)

    # ...but preview with different, unsaved slider values.
    res = c.post(
        "/preview",
        data={"text": "hi", "exaggeration": "1.5", "cfg_weight": "0.1", "speaking_rate": "1.2"},
    )

    assert res.status_code == 200
    assert captured["settings"].exaggeration == 1.5
    assert captured["settings"].cfg_weight == 0.1
    assert captured["settings"].speaking_rate == 1.2
    # And the saved settings on disk are untouched by a preview.
    assert voice_settings.load_settings(vault_dir).exaggeration == 0.5
