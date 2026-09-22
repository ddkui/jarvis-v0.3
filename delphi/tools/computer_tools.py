"""Desktop control: screenshots, mouse, and keyboard, via pyautogui.

Disabled by default — this is real, unconfirmed control of whatever computer runs
`delphi chat` (any app, any window, any file dialog). Enable it deliberately with
DELPHI_ENABLE_COMPUTER_USE=1 once you understand the risk (see README.md
"Computer use"). Two safety mechanisms are always on regardless of that setting:

  - pyautogui's failsafe: dragging the mouse to any screen corner mid-action raises
    pyautogui.FailSafeException, which every handler here turns into an AgentAbort —
    this stops the whole agent loop immediately rather than being retried as a
    normal tool error.
  - Every action is logged to stderr with its arguments as it happens, so whoever is
    watching the terminal has a live, real-time record of what Delphi is about to do.

Requires a real display (X11/Wayland/macOS/Windows desktop session) — importing
pyautogui without one raises immediately, which build_tools() catches and reports.
"""

from __future__ import annotations

import base64
import io
import os
import sys

from delphi.models import AgentAbort, Tool

_ENABLE_ENV_VAR = "DELPHI_ENABLE_COMPUTER_USE"
_VALID_BUTTONS = {"left", "right", "middle"}


def _log(action: str) -> None:
    print(f"[computer-use] {action}", file=sys.stderr, flush=True)


def _load_pyautogui():
    import pyautogui

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.3
    return pyautogui


def _require(args: dict, key: str):
    if key not in args or args[key] in (None, ""):
        raise ValueError(f"missing required field: {key}")
    return args[key]


def _guarded(pyautogui, fn):
    try:
        return fn()
    except pyautogui.FailSafeException as e:
        raise AgentAbort(
            "Computer-use failsafe triggered (mouse moved to a screen corner) — stopping."
        ) from e


def _handle_screenshot(pyautogui):
    def handler(_args: dict) -> str:
        _log("screenshot")
        image = _guarded(pyautogui, pyautogui.screenshot)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    return handler


def _handle_click(pyautogui):
    def handler(args: dict) -> str:
        x, y = int(_require(args, "x")), int(_require(args, "y"))
        button = args.get("button", "left")
        if button not in _VALID_BUTTONS:
            raise ValueError(f"button must be one of {sorted(_VALID_BUTTONS)}, got {button!r}")
        clicks = int(args.get("clicks", 1))
        double = bool(args.get("double", False))
        if double:
            clicks = 2
        _log(f"click at ({x}, {y}) button={button} clicks={clicks}")
        _guarded(pyautogui, lambda: pyautogui.click(x, y, button=button, clicks=clicks))
        return f"Clicked at ({x}, {y}) with {button} button."

    return handler


def _handle_move(pyautogui):
    def handler(args: dict) -> str:
        x, y = int(_require(args, "x")), int(_require(args, "y"))
        _log(f"move to ({x}, {y})")
        _guarded(pyautogui, lambda: pyautogui.moveTo(x, y, duration=0.2))
        return f"Moved mouse to ({x}, {y})."

    return handler


def _handle_type(pyautogui):
    def handler(args: dict) -> str:
        text = _require(args, "text")
        _log(f"type {len(text)} chars")
        _guarded(pyautogui, lambda: pyautogui.write(text, interval=0.02))
        return f"Typed {len(text)} characters."

    return handler


def _handle_key(pyautogui):
    def handler(args: dict) -> str:
        key = _require(args, "key")
        _log(f"key {key}")
        parts = [p.strip() for p in key.split("+") if p.strip()]
        if not parts:
            raise ValueError("key must not be empty")
        if len(parts) > 1:
            _guarded(pyautogui, lambda: pyautogui.hotkey(*parts))
        else:
            _guarded(pyautogui, lambda: pyautogui.press(parts[0]))
        return f"Pressed key(s): {key}."

    return handler


def _handle_scroll(pyautogui):
    def handler(args: dict) -> str:
        amount = int(_require(args, "amount"))
        x, y = args.get("x"), args.get("y")
        _log(f"scroll {amount} at ({x}, {y})")
        _guarded(pyautogui, lambda: pyautogui.scroll(amount, x=x, y=y))
        return f"Scrolled {amount}."

    return handler


def build_tools() -> list[Tool]:
    if os.environ.get(_ENABLE_ENV_VAR) != "1":
        return []

    try:
        pyautogui = _load_pyautogui()
        width, height = pyautogui.size()
    except Exception as e:
        print(
            f"[computer-use] DELPHI_ENABLE_COMPUTER_USE=1 but pyautogui isn't usable "
            f"here ({e}); computer-use tools are disabled for this session.",
            file=sys.stderr,
        )
        return []

    resolution_note = (
        f"The real screen resolution is {width}x{height} pixels. Always give "
        "coordinates in this pixel space, whatever size the screenshot image looks "
        "like to you."
    )

    return [
        Tool(
            name="computer_screenshot",
            description=(
                "Take a screenshot of the whole desktop and see it. Call this before "
                "acting, and again after any action whose result you need to check. "
                + resolution_note
            ),
            input_schema={"type": "object", "properties": {}},
            handler=_handle_screenshot(pyautogui),
        ),
        Tool(
            name="computer_click",
            description="Click the mouse at a screen position. " + resolution_note,
            input_schema={
                "type": "object",
                "properties": {
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                    "button": {"type": "string", "enum": sorted(_VALID_BUTTONS), "default": "left"},
                    "double": {"type": "boolean", "default": False},
                },
                "required": ["x", "y"],
            },
            handler=_handle_click(pyautogui),
        ),
        Tool(
            name="computer_move",
            description="Move the mouse to a screen position without clicking. " + resolution_note,
            input_schema={
                "type": "object",
                "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"],
            },
            handler=_handle_move(pyautogui),
        ),
        Tool(
            name="computer_type",
            description="Type text at the current keyboard focus.",
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
            handler=_handle_type(pyautogui),
        ),
        Tool(
            name="computer_key",
            description=(
                "Press a key or key combination, e.g. 'enter', 'escape', 'ctrl+c', 'cmd+tab'."
            ),
            input_schema={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
            },
            handler=_handle_key(pyautogui),
        ),
        Tool(
            name="computer_scroll",
            description="Scroll the mouse wheel. Positive amount scrolls up, negative scrolls down.",
            input_schema={
                "type": "object",
                "properties": {
                    "amount": {"type": "integer"},
                    "x": {"type": "integer"},
                    "y": {"type": "integer"},
                },
                "required": ["amount"],
            },
            handler=_handle_scroll(pyautogui),
        ),
    ]
