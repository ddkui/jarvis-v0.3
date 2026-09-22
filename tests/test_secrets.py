import keyring.errors
import pytest

from delphi import secrets


class _FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        if (service, name) not in self.store:
            raise keyring.errors.PasswordDeleteError("not found")
        del self.store[(service, name)]


class _BrokenKeyring:
    def get_password(self, service, name):
        raise keyring.errors.NoKeyringError("no backend available")

    def set_password(self, service, name, value):
        raise keyring.errors.NoKeyringError("no backend available")

    def delete_password(self, service, name):
        raise keyring.errors.NoKeyringError("no backend available")


def test_set_then_get_secret(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(secrets.keyring, "get_password", fake.get_password)
    monkeypatch.setattr(secrets.keyring, "set_password", fake.set_password)

    secrets.set_secret("ANTHROPIC_API_KEY", "sk-ant-test")
    assert secrets.get_secret("ANTHROPIC_API_KEY") == "sk-ant-test"


def test_get_secret_missing_returns_none(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(secrets.keyring, "get_password", fake.get_password)

    assert secrets.get_secret("NOT_STORED") is None


def test_get_secret_returns_none_when_no_backend(monkeypatch):
    broken = _BrokenKeyring()
    monkeypatch.setattr(secrets.keyring, "get_password", broken.get_password)

    assert secrets.get_secret("ANTHROPIC_API_KEY") is None


def test_delete_secret_returns_false_when_missing(monkeypatch):
    fake = _FakeKeyring()
    monkeypatch.setattr(secrets.keyring, "delete_password", fake.delete_password)

    assert secrets.delete_secret("NEVER_STORED") is False


def test_delete_secret_returns_true_when_removed(monkeypatch):
    fake = _FakeKeyring()
    fake.store[(secrets._SERVICE_NAME, "ANTHROPIC_API_KEY")] = "sk-ant-test"
    monkeypatch.setattr(secrets.keyring, "delete_password", fake.delete_password)

    assert secrets.delete_secret("ANTHROPIC_API_KEY") is True


def test_delete_secret_returns_false_when_no_backend_available(monkeypatch):
    def _raise_no_backend(service, name):
        raise keyring.errors.NoKeyringError("no backend available")

    monkeypatch.setattr(secrets.keyring, "delete_password", _raise_no_backend)

    assert secrets.delete_secret("ANTHROPIC_API_KEY") is False


def test_apply_to_environ_fills_gaps_from_keychain(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    fake = _FakeKeyring()
    fake.store[(secrets._SERVICE_NAME, "GEMINI_API_KEY")] = "from-keychain"
    monkeypatch.setattr(secrets.keyring, "get_password", fake.get_password)

    secrets.apply_to_environ(["GEMINI_API_KEY"])

    import os

    assert os.environ["GEMINI_API_KEY"] == "from-keychain"


def test_apply_to_environ_does_not_override_existing_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "from-shell")
    fake = _FakeKeyring()
    fake.store[(secrets._SERVICE_NAME, "GEMINI_API_KEY")] = "from-keychain"
    monkeypatch.setattr(secrets.keyring, "get_password", fake.get_password)

    secrets.apply_to_environ(["GEMINI_API_KEY"])

    import os

    assert os.environ["GEMINI_API_KEY"] == "from-shell"


def test_apply_to_environ_no_backend_is_a_silent_noop(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    broken = _BrokenKeyring()
    monkeypatch.setattr(secrets.keyring, "get_password", broken.get_password)

    secrets.apply_to_environ(["DEEPSEEK_API_KEY"])

    import os

    assert "DEEPSEEK_API_KEY" not in os.environ
