import base64
import sys
import types

import pytest

from jarvis.models import AgentAbort
from jarvis.tools import computer_tools


def _install_fake_pyautogui(monkeypatch, *, failsafe_on=None):
    fake = types.SimpleNamespace()
    fake.FAILSAFE = None
    fake.PAUSE = None
    fake.calls = []

    class FailSafeException(Exception):
        pass

    fake.FailSafeException = FailSafeException

    def _maybe_fail(name):
        if failsafe_on == name:
            raise FailSafeException("corner")

    def size():
        return (1920, 1080)

    def screenshot():
        _maybe_fail("screenshot")
        fake.calls.append(("screenshot",))
        image = types.SimpleNamespace()
        image.save = lambda buf, format: buf.write(b"fake-png-bytes")
        return image

    def click(x, y, button="left", clicks=1):
        _maybe_fail("click")
        fake.calls.append(("click", x, y, button, clicks))

    def moveTo(x, y, duration=0.0):
        _maybe_fail("move")
        fake.calls.append(("move", x, y))

    def write(text, interval=0.0):
        _maybe_fail("type")
        fake.calls.append(("type", text))

    def press(key):
        _maybe_fail("key")
        fake.calls.append(("press", key))

    def hotkey(*keys):
        _maybe_fail("key")
        fake.calls.append(("hotkey", keys))

    def scroll(amount, x=None, y=None):
        _maybe_fail("scroll")
        fake.calls.append(("scroll", amount, x, y))

    fake.size = size
    fake.screenshot = screenshot
    fake.click = click
    fake.moveTo = moveTo
    fake.write = write
    fake.press = press
    fake.hotkey = hotkey
    fake.scroll = scroll

    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


def _tools_by_name(tools):
    return {t.name: t for t in tools}


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_ENABLE_COMPUTER_USE", raising=False)
    assert computer_tools.build_tools() == []


def test_disabled_when_env_var_not_exactly_one(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "true")
    assert computer_tools.build_tools() == []


def test_returns_empty_list_when_pyautogui_unavailable(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    monkeypatch.delitem(sys.modules, "pyautogui", raising=False)

    real_import = __import__

    def _raise_import(name, *a, **k):
        if name == "pyautogui":
            raise KeyError("DISPLAY")
        return real_import(name, *a, **k)

    monkeypatch.setattr("builtins.__import__", _raise_import)
    assert computer_tools.build_tools() == []


def test_enabled_exposes_all_tools(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    _install_fake_pyautogui(monkeypatch)

    tools = _tools_by_name(computer_tools.build_tools())
    assert set(tools) == {
        "computer_screenshot",
        "computer_click",
        "computer_move",
        "computer_type",
        "computer_key",
        "computer_scroll",
    }
    assert "1920x1080" in tools["computer_screenshot"].description


def test_screenshot_returns_image_data_url(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    _install_fake_pyautogui(monkeypatch)

    tools = _tools_by_name(computer_tools.build_tools())
    result = tools["computer_screenshot"].handler({})

    assert result.startswith("data:image/png;base64,")
    payload = result.removeprefix("data:image/png;base64,")
    assert base64.b64decode(payload) == b"fake-png-bytes"


def test_click_invokes_pyautogui_with_expected_args(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    fake = _install_fake_pyautogui(monkeypatch)

    tools = _tools_by_name(computer_tools.build_tools())
    result = tools["computer_click"].handler({"x": 100, "y": 200, "button": "right"})

    assert "(100, 200)" in result
    assert fake.calls == [("click", 100, 200, "right", 1)]


def test_click_rejects_invalid_button(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    _install_fake_pyautogui(monkeypatch)

    tools = _tools_by_name(computer_tools.build_tools())
    with pytest.raises(ValueError):
        tools["computer_click"].handler({"x": 1, "y": 1, "button": "laser"})


def test_click_missing_required_field_raises(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    _install_fake_pyautogui(monkeypatch)

    tools = _tools_by_name(computer_tools.build_tools())
    with pytest.raises(ValueError):
        tools["computer_click"].handler({"x": 1})


def test_key_combo_uses_hotkey(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    fake = _install_fake_pyautogui(monkeypatch)

    tools = _tools_by_name(computer_tools.build_tools())
    tools["computer_key"].handler({"key": "ctrl+c"})

    assert fake.calls == [("hotkey", ("ctrl", "c"))]


def test_single_key_uses_press(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    fake = _install_fake_pyautogui(monkeypatch)

    tools = _tools_by_name(computer_tools.build_tools())
    tools["computer_key"].handler({"key": "enter"})

    assert fake.calls == [("press", "enter")]


def test_failsafe_trip_raises_agent_abort(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLE_COMPUTER_USE", "1")
    _install_fake_pyautogui(monkeypatch, failsafe_on="click")

    tools = _tools_by_name(computer_tools.build_tools())
    with pytest.raises(AgentAbort):
        tools["computer_click"].handler({"x": 1, "y": 1})
