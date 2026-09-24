import io

import litellm
import pytest

from delphi import dashboard as dashboard_module
from delphi import runtime, settings as voice_settings
from delphi import tts
from delphi.config import DelphiConfig
from delphi.dashboard import create_app
from delphi.models import AgentAbort


def _config(vault_dir):
    return DelphiConfig(
        model="anthropic/claude-opus-5",
        vault_dir=vault_dir,
        db_path=vault_dir / ".delphi" / "memory.db",
        reminders_db_path=vault_dir / ".delphi" / "reminders.db",
    )


@pytest.fixture
def client(tmp_path):
    app = create_app(_config(tmp_path))
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, tmp_path


class _FakeAgent:
    def __init__(self, reply=None, raises=None):
        self._reply = reply
        self._raises = raises
        self.sent = []
        self.messages = []

    def send(self, message):
        self.sent.append(message)
        if self._raises is not None:
            raise self._raises
        return self._reply


def test_index_renders_defaults(client):
    c, _ = client
    res = c.get("/")
    assert res.status_code == 200
    assert b"Voice Settings" in res.data
    assert b"Default (Chatterbox built-in)" in res.data


def test_index_warns_when_voice_disabled(client, monkeypatch):
    c, _ = client
    monkeypatch.delenv("DELPHI_ENABLE_VOICE", raising=False)
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


def test_delete_best_effort_ignores_permission_error(tmp_path):
    # On Windows, a file still open elsewhere (e.g. mid-streaming via send_file)
    # raises PermissionError on unlink rather than succeeding as it would on
    # POSIX - cleanup should swallow that rather than crashing the request.
    path = tmp_path / "locked.wav"
    path.write_bytes(b"x")

    def _raise_permission_error(self, missing_ok=False):
        raise PermissionError("file in use")

    import unittest.mock

    with unittest.mock.patch.object(type(path), "unlink", _raise_permission_error):
        dashboard_module._delete_best_effort(path)  # must not raise


def test_delete_best_effort_removes_existing_file(tmp_path):
    path = tmp_path / "cleanup.wav"
    path.write_bytes(b"x")

    dashboard_module._delete_best_effort(path)

    assert not path.exists()


def test_preview_returns_error_when_voice_disabled(client, monkeypatch):
    c, _ = client
    monkeypatch.delenv("DELPHI_ENABLE_VOICE", raising=False)

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


def test_chat_page_renders(client):
    c, _ = client
    res = c.get("/chat")
    assert res.status_code == 200
    assert b"Delphi" in res.data


def test_chat_history_empty_for_fresh_conversation(client):
    c, _ = client
    res = c.get("/chat/history")
    assert res.status_code == 200
    assert res.get_json() == {"ok": True, "turns": []}


def test_chat_history_reflects_resumed_conversation(client, monkeypatch):
    c, vault_dir = client
    from delphi import conversation

    conversation.save_messages(
        vault_dir,
        [
            {"role": "user", "content": "hi"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "remember", "arguments": "{}"}}],
            },
            {"role": "tool", "tool_call_id": "c1", "content": "Remembered: something"},
            {"role": "assistant", "content": "Got it."},
        ],
    )

    res = c.get("/chat/history")

    assert res.get_json() == {
        "ok": True,
        "turns": [{"role": "you", "text": "hi"}, {"role": "delphi", "text": "Got it."}],
    }


def test_chat_send_rejects_empty_message(client):
    c, _ = client
    res = c.post("/chat/send", data={"message": "   "})
    assert res.status_code == 400
    assert res.get_json()["ok"] is False


def test_chat_send_returns_agent_reply(client, monkeypatch):
    c, _ = client
    fake_agent = _FakeAgent(reply="Hi there!")
    monkeypatch.setattr(runtime, "build_agent", lambda config: fake_agent)

    res = c.post("/chat/send", data={"message": "hello"})

    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["reply"] == "Hi there!"
    assert fake_agent.sent == ["hello"]


def test_chat_send_reuses_same_agent_across_requests(client, monkeypatch):
    c, _ = client
    built = []

    def _build(config):
        agent = _FakeAgent(reply="ok")
        built.append(agent)
        return agent

    monkeypatch.setattr(runtime, "build_agent", _build)

    c.post("/chat/send", data={"message": "first"})
    c.post("/chat/send", data={"message": "second"})

    assert len(built) == 1
    assert built[0].sent == ["first", "second"]


def test_chat_reset_builds_a_fresh_agent(client, monkeypatch):
    c, _ = client
    built = []

    def _build(config):
        agent = _FakeAgent(reply="ok")
        built.append(agent)
        return agent

    monkeypatch.setattr(runtime, "build_agent", _build)

    c.post("/chat/send", data={"message": "first"})
    c.post("/chat/reset")
    c.post("/chat/send", data={"message": "second"})

    assert len(built) == 2


def test_chat_send_handles_agent_abort(client, monkeypatch):
    c, _ = client
    fake_agent = _FakeAgent(raises=AgentAbort("failsafe tripped"))
    monkeypatch.setattr(runtime, "build_agent", lambda config: fake_agent)

    res = c.post("/chat/send", data={"message": "click something"})

    data = res.get_json()
    assert data["ok"] is False
    assert "Stopped" in data["error"]


def test_chat_send_handles_authentication_error(client, monkeypatch):
    c, _ = client
    fake_agent = _FakeAgent(raises=litellm.exceptions.AuthenticationError("bad key", llm_provider="anthropic", model="x"))
    monkeypatch.setattr(runtime, "build_agent", lambda config: fake_agent)

    res = c.post("/chat/send", data={"message": "hi"})

    data = res.get_json()
    assert data["ok"] is False
    assert "authenticate" in data["error"].lower()


def test_chat_send_error_names_the_failing_model_not_the_primary(client, monkeypatch):
    # With DELPHI_FALLBACK_MODELS configured, an error can come from a
    # fallback model rather than config.model - the reported name should
    # reflect whichever one actually failed, not always blame the primary.
    c, _ = client
    fake_agent = _FakeAgent(
        raises=litellm.exceptions.NotFoundError(
            "model not found", llm_provider="nvidia_nim", model="nvidia_nim/meta/llama3-70b-instruct"
        )
    )
    monkeypatch.setattr(runtime, "build_agent", lambda config: fake_agent)

    res = c.post("/chat/send", data={"message": "hi"})

    data = res.get_json()
    assert data["ok"] is False
    assert "nvidia_nim/meta/llama3-70b-instruct" in data["error"]
    assert "anthropic/claude-opus-5" not in data["error"]


def test_chat_send_suggests_new_conversation_for_multimodal_errors(client, monkeypatch):
    c, _ = client
    fake_agent = _FakeAgent(
        raises=litellm.exceptions.BadRequestError(
            "Multimodal data provided, but model does not support multimodal requests.",
            llm_provider="ollama",
            model="ollama/qwen2.5-coder:7b",
        )
    )
    monkeypatch.setattr(runtime, "build_agent", lambda config: fake_agent)

    res = c.post("/chat/send", data={"message": "hi"})

    data = res.get_json()
    assert data["ok"] is False
    assert "new conversation" in data["error"].lower()


def test_chat_send_handles_unexpected_errors_gracefully(client, monkeypatch):
    c, _ = client
    fake_agent = _FakeAgent(raises=RuntimeError("quota exceeded"))
    monkeypatch.setattr(runtime, "build_agent", lambda config: fake_agent)

    res = c.post("/chat/send", data={"message": "hi"})

    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is False
    assert "hit a problem" in data["error"].lower()
