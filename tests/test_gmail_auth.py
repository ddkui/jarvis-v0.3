import json
import sys
import types

import pytest

from delphi import gmail_auth


def _install_fake_google_stack(monkeypatch, *, refresh_raises=False):
    """Fakes the three google-auth/googleapiclient pieces gmail_auth imports
    lazily, the same sys.modules-injection pattern as tests/test_tts.py's
    _install_fake_torch_stack. Real client credential info round-trips
    through FakeCredentials.to_json()/from_authorized_user_info() as plain
    JSON, same shape as the real library."""
    calls = {"build": [], "refresh": 0}

    class FakeCredentials:
        def __init__(self, info):
            self._info = dict(info)
            self.expired = bool(info.get("expired"))
            self.refresh_token = info.get("refresh_token")

        @classmethod
        def from_authorized_user_info(cls, info, scopes):
            return cls(info)

        def refresh(self, request):
            calls["refresh"] += 1
            if refresh_raises:
                raise RuntimeError("refresh failed")
            self.expired = False

        def to_json(self):
            return json.dumps({**self._info, "expired": self.expired})

    credentials_module = types.ModuleType("google.oauth2.credentials")
    credentials_module.Credentials = FakeCredentials
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", credentials_module)

    class FakeRequest:
        pass

    requests_module = types.ModuleType("google.auth.transport.requests")
    requests_module.Request = FakeRequest
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", requests_module)

    def fake_build(service_name, version, credentials=None):
        calls["build"].append((service_name, version, credentials))
        return f"service:{service_name}:{version}"

    discovery_module = types.ModuleType("googleapiclient.discovery")
    discovery_module.build = fake_build
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery_module)

    return calls, FakeCredentials


def _install_fake_flow(monkeypatch, *, returned_creds):
    calls = {}

    class FakeFlow:
        def __init__(self, path, scopes):
            calls["path"] = path
            calls["scopes"] = scopes

        def run_local_server(self, port=0):
            calls["port"] = port
            return returned_creds

    class FakeInstalledAppFlow:
        @staticmethod
        def from_client_secrets_file(path, scopes):
            return FakeFlow(path, scopes)

    flow_module = types.ModuleType("google_auth_oauthlib.flow")
    flow_module.InstalledAppFlow = FakeInstalledAppFlow
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", flow_module)
    return calls


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_EMAIL", raising=False)
    assert gmail_auth.is_enabled() is False


def test_enabled_via_env(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    assert gmail_auth.is_enabled() is True


def test_ensure_ready_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_EMAIL", raising=False)
    with pytest.raises(gmail_auth.GmailUnavailable, match="DELPHI_ENABLE_EMAIL"):
        gmail_auth.ensure_ready()


def test_ensure_ready_raises_when_credentials_env_var_unset(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    monkeypatch.delenv("GOOGLE_GMAIL_CREDENTIALS", raising=False)
    with pytest.raises(gmail_auth.GmailUnavailable, match="GOOGLE_GMAIL_CREDENTIALS"):
        gmail_auth.ensure_ready()


def test_ensure_ready_raises_when_credentials_file_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", str(tmp_path / "does-not-exist.json"))
    with pytest.raises(gmail_auth.GmailUnavailable, match="GOOGLE_GMAIL_CREDENTIALS"):
        gmail_auth.ensure_ready()


def test_ensure_ready_raises_when_dependency_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", str(creds_file))
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", None)

    with pytest.raises(gmail_auth.GmailUnavailable, match=r"pip install -e \.\[gmail\]"):
        gmail_auth.ensure_ready()


def test_ensure_ready_raises_when_no_stored_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", str(creds_file))
    _install_fake_google_stack(monkeypatch)
    monkeypatch.setattr("delphi.gmail_auth.secrets.get_secret", lambda name: None)

    with pytest.raises(gmail_auth.GmailUnavailable, match="delphi auth gmail"):
        gmail_auth.ensure_ready()


def test_ensure_ready_raises_when_refresh_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", str(creds_file))
    _install_fake_google_stack(monkeypatch, refresh_raises=True)
    stored = json.dumps({"expired": True, "refresh_token": "r-token"})
    monkeypatch.setattr("delphi.gmail_auth.secrets.get_secret", lambda name: stored)

    with pytest.raises(gmail_auth.GmailUnavailable, match="refresh failed"):
        gmail_auth.ensure_ready()


def test_get_client_returns_service_without_refresh_when_token_is_fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", str(creds_file))
    calls, _ = _install_fake_google_stack(monkeypatch)
    stored = json.dumps({"expired": False, "refresh_token": "r-token"})
    monkeypatch.setattr("delphi.gmail_auth.secrets.get_secret", lambda name: stored)
    set_calls = []
    monkeypatch.setattr("delphi.gmail_auth.secrets.set_secret", lambda name, value: set_calls.append((name, value)))

    service = gmail_auth.get_client()

    assert service == "service:gmail:v1"
    assert calls["refresh"] == 0
    assert set_calls == []  # nothing to re-save - the token wasn't touched


def test_get_client_refreshes_and_resaves_expired_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", str(creds_file))
    calls, _ = _install_fake_google_stack(monkeypatch)
    stored = json.dumps({"expired": True, "refresh_token": "r-token"})
    monkeypatch.setattr("delphi.gmail_auth.secrets.get_secret", lambda name: stored)
    set_calls = []
    monkeypatch.setattr(
        "delphi.gmail_auth.secrets.set_secret", lambda name, value: set_calls.append((name, value))
    )

    service = gmail_auth.get_client()

    assert service == "service:gmail:v1"
    assert calls["refresh"] == 1
    assert len(set_calls) == 1
    saved_name, saved_value = set_calls[0]
    assert saved_name == gmail_auth._TOKEN_SECRET_NAME
    assert json.loads(saved_value)["expired"] is False


def test_run_interactive_auth_flow_saves_token(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", str(creds_file))

    class FakeCreds:
        def to_json(self):
            return json.dumps({"token": "brand-new"})

    _install_fake_flow(monkeypatch, returned_creds=FakeCreds())
    set_calls = []
    monkeypatch.setattr(
        "delphi.gmail_auth.secrets.set_secret", lambda name, value: set_calls.append((name, value))
    )

    gmail_auth.run_interactive_auth_flow()

    assert set_calls == [(gmail_auth._TOKEN_SECRET_NAME, json.dumps({"token": "brand-new"}))]


def test_run_interactive_auth_flow_raises_when_disabled(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_EMAIL", raising=False)
    with pytest.raises(gmail_auth.GmailUnavailable, match="DELPHI_ENABLE_EMAIL"):
        gmail_auth.run_interactive_auth_flow()


def test_run_interactive_auth_flow_raises_when_dependency_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_EMAIL", "1")
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text("{}")
    monkeypatch.setenv("GOOGLE_GMAIL_CREDENTIALS", str(creds_file))
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", None)

    with pytest.raises(gmail_auth.GmailUnavailable, match=r"pip install -e \.\[gmail\]"):
        gmail_auth.run_interactive_auth_flow()
