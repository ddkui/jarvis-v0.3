import sys
import types

import pytest

from delphi import tray
from delphi.config import DelphiConfig


def _config(tmp_path):
    return DelphiConfig(
        model="anthropic/claude-opus-5",
        vault_dir=tmp_path,
        db_path=tmp_path / ".delphi" / "memory.db",
        reminders_db_path=tmp_path / ".delphi" / "reminders.db",
    )


@pytest.fixture(autouse=True)
def _no_autoupdate(monkeypatch):
    # run_tray checks for updates (a real git fetch) and starts a background
    # poller on every call - keep tests hermetic and fast by stubbing both out;
    # autoupdate itself is covered by tests/test_autoupdate.py.
    monkeypatch.setattr(tray.autoupdate, "check_once_and_restart_if_updated", lambda: None)
    monkeypatch.setattr(tray.autoupdate, "run_background", lambda: None)


def test_run_tray_raises_when_pystray_unavailable_for_real(tmp_path):
    # No mocking here: this sandbox genuinely has no display, so importing
    # pystray really does fail - the same way it would on any headless box.
    with pytest.raises(tray.TrayUnavailable, match="isn't usable here"):
        tray.run_tray(_config(tmp_path), port=18734)


def test_build_icon_image_produces_a_real_image(tmp_path):
    image = tray._build_icon_image()
    out = tmp_path / "icon.png"
    image.save(out)
    assert out.is_file()
    assert out.stat().st_size > 0


def test_run_tray_builds_menu_and_runs_icon_event_loop(monkeypatch, tmp_path):
    fake_pystray = types.ModuleType("pystray")
    created_icons = []

    class FakeMenuItem:
        def __init__(self, text, action, default=False):
            self.text = text
            self.action = action
            self.default = default

    class FakeMenu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class FakeIcon:
        def __init__(self, name, image, title, menu):
            self.name = name
            self.image = image
            self.title = title
            self.menu = menu
            self.ran = False
            created_icons.append(self)

        def run(self):
            self.ran = True

        def stop(self):
            self.ran = False

    fake_pystray.Menu = FakeMenu
    fake_pystray.MenuItem = FakeMenuItem
    fake_pystray.Icon = FakeIcon
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)

    fake_app = types.SimpleNamespace(run=lambda **kwargs: None)
    monkeypatch.setattr("delphi.dashboard.create_app", lambda config: fake_app)

    captured_thread = {}

    class FakeThread:
        def __init__(self, target=None, kwargs=None, daemon=None):
            captured_thread["target"] = target
            captured_thread["kwargs"] = kwargs
            captured_thread["daemon"] = daemon

        def start(self):
            captured_thread["started"] = True

    monkeypatch.setattr(tray.threading, "Thread", FakeThread)

    tray.run_tray(_config(tmp_path), port=18735)

    assert captured_thread["daemon"] is True
    assert captured_thread["started"] is True
    assert captured_thread["target"] == fake_app.run
    assert captured_thread["kwargs"] == {"host": "127.0.0.1", "port": 18735, "debug": False}

    assert len(created_icons) == 1
    icon = created_icons[0]
    assert icon.ran is True
    assert icon.name == "delphi"
    menu_texts = [item.text for item in icon.menu.items if item is not FakeMenu.SEPARATOR]
    assert "Open Dashboard" in menu_texts
    assert "Open Chat" in menu_texts
    assert "Quit" in menu_texts


def test_run_tray_starts_the_wake_word_listener(monkeypatch, tmp_path):
    fake_pystray = types.ModuleType("pystray")
    fake_pystray.MenuItem = lambda *a, **k: None

    class FakeMenu:
        SEPARATOR = object()

        def __init__(self, *a, **k):
            pass

    fake_pystray.Menu = FakeMenu
    fake_pystray.Icon = lambda *a, **k: types.SimpleNamespace(run=lambda: None)
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    monkeypatch.setattr("delphi.dashboard.create_app", lambda config: types.SimpleNamespace(run=lambda **k: None))
    monkeypatch.setattr(tray.threading.Thread, "start", lambda self: None)

    started_with = {}
    monkeypatch.setattr(tray.listen, "run_background", lambda config: started_with.setdefault("config", config))

    config = _config(tmp_path)
    tray.run_tray(config, port=18736)

    assert started_with["config"] is config


def test_run_tray_wraps_unexpected_setup_errors(monkeypatch, tmp_path):
    fake_pystray = types.ModuleType("pystray")
    fake_pystray.MenuItem = lambda *a, **k: None

    class FakeMenu:
        SEPARATOR = object()

        def __init__(self, *a, **k):
            pass

    fake_pystray.Menu = FakeMenu

    def _explode(*a, **k):
        raise RuntimeError("boom")

    fake_pystray.Icon = _explode
    monkeypatch.setitem(sys.modules, "pystray", fake_pystray)
    monkeypatch.setattr("delphi.dashboard.create_app", lambda config: types.SimpleNamespace(run=lambda **k: None))
    monkeypatch.setattr(tray.threading.Thread, "start", lambda self: None)

    with pytest.raises(tray.TrayUnavailable, match="boom"):
        tray.run_tray(_config(tmp_path), port=18736)
