"""Linux app-launcher entry for Jarvis - `jarvis install-launcher`.

Writes a standard freedesktop.org .desktop file to ~/.local/share/applications/
so Jarvis shows up in the application launcher/grid like any other installed
app, plus a generated icon alongside it. Launching it runs `jarvis tray` - the
system tray icon + background dashboard/chat server (jarvis/tray.py).

Linux-only: macOS and Windows have their own app-registration mechanisms this
doesn't attempt to cover.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

_DESKTOP_ENTRY_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Jarvis
Comment=Personal second-brain assistant
Exec={exec_path} tray
Icon={icon_path}
Terminal=false
Categories=Utility;
"""


def install_launcher() -> Path:
    """Write the .desktop file and icon, return the .desktop file's path.
    Raises RuntimeError on non-Linux platforms or if the jarvis executable
    can't be found (jarvis isn't installed, e.g. via `pip install -e .`)."""
    if platform.system() != "Linux":
        raise RuntimeError(
            f"App launcher entries are only supported on Linux (this is {platform.system()})."
        )

    jarvis_exe = Path(sys.executable).parent / "jarvis"
    if not jarvis_exe.is_file():
        raise RuntimeError(
            f"Couldn't find the jarvis executable at {jarvis_exe}. Is jarvis installed (pip install -e .)?"
        )

    apps_dir = Path.home() / ".local" / "share" / "applications"
    icons_dir = Path.home() / ".local" / "share" / "icons"
    apps_dir.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)

    icon_path = icons_dir / "jarvis.png"
    try:
        from jarvis.tray import _build_icon_image

        _build_icon_image().save(icon_path)
    except Exception as e:
        raise RuntimeError(
            f"Couldn't generate the launcher icon: {e}. Install the optional dependency: "
            "pip install -e .[tray]"
        ) from e

    desktop_path = apps_dir / "jarvis.desktop"
    desktop_path.write_text(_DESKTOP_ENTRY_TEMPLATE.format(exec_path=jarvis_exe, icon_path=icon_path))
    desktop_path.chmod(0o755)
    return desktop_path
