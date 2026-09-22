"""System tray icon for Delphi - `delphi tray`.

Runs the same dashboard+chat web server as `delphi dashboard`, but as a
background daemon thread with a system tray icon (next to the clock/volume/
network indicators) instead of a blocking terminal session: click the icon to
open the dashboard or chat in your browser, or use its menu to quit.

Needs a real desktop session (X11/Wayland on Linux, or macOS/Windows) - like
computer-use, this can't run in a headless environment, and degrades to a
clear TrayUnavailable rather than crashing when no display is available.
"""

from __future__ import annotations

import threading

from delphi.config import DelphiConfig


class TrayUnavailable(Exception):
    """Raised when the system tray can't be used right now (no display,
    pystray not installed, or the backend failed to initialize)."""


def _build_icon_image():
    from pathlib import Path

    from PIL import Image

    mark_path = Path(__file__).resolve().parent.parent / "assets" / "brand" / "delphi_mark.png"
    return Image.open(mark_path).convert("RGBA").resize((64, 64), Image.LANCZOS)


def run_tray(config: DelphiConfig, port: int = 8734) -> None:
    """Start the dashboard+chat server on a background daemon thread and block
    on the tray icon's event loop until "Quit" is chosen (which stops the icon;
    the daemon server thread then goes down with the process). Raises
    TrayUnavailable if the tray can't be created at all."""
    try:
        import pystray

        from delphi.dashboard import create_app

        url = f"http://127.0.0.1:{port}"
        app = create_app(config)
        server_thread = threading.Thread(
            target=app.run,
            kwargs={"host": "127.0.0.1", "port": port, "debug": False},
            daemon=True,
        )
        server_thread.start()

        def _open_dashboard(icon=None, item=None) -> None:
            import webbrowser

            webbrowser.open(url)

        def _open_chat(icon=None, item=None) -> None:
            import webbrowser

            webbrowser.open(f"{url}/chat")

        def _quit(icon, item=None) -> None:
            icon.stop()

        menu = pystray.Menu(
            pystray.MenuItem("Open Dashboard", _open_dashboard, default=True),
            pystray.MenuItem("Open Chat", _open_chat),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", _quit),
        )
        icon = pystray.Icon("delphi", _build_icon_image(), "Delphi", menu)
    except Exception as e:
        raise TrayUnavailable(f"System tray isn't usable here: {e}") from e

    icon.run()
