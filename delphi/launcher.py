"""Linux app-launcher entry for Delphi - `delphi install-launcher`.

Writes a standard freedesktop.org .desktop file to ~/.local/share/applications/
so Delphi shows up in the application launcher/grid like any other installed
app, plus a generated icon alongside it. Launching it runs `delphi tray` - the
system tray icon + background dashboard/chat server (delphi/tray.py).

Linux-only: macOS and Windows have their own app-registration mechanisms this
doesn't attempt to cover.
"""

from __future__ import annotations

import platform
import sys
from pathlib import Path

_DESKTOP_ENTRY_TEMPLATE = """[Desktop Entry]
Type=Application
Name=Delphi
Comment=Personal second-brain assistant
Exec={exec_path} tray
Icon={icon_path}
Terminal=false
Categories=Utility;
"""


def install_launcher() -> Path:
    """Write the .desktop file and icon, return the .desktop file's path.
    Raises RuntimeError on non-Linux platforms or if the delphi executable
    can't be found (delphi isn't installed, e.g. via `pip install -e .`)."""
    if platform.system() != "Linux":
        raise RuntimeError(
            f"App launcher entries are only supported on Linux (this is {platform.system()})."
        )

    delphi_exe = Path(sys.executable).parent / "delphi"
    if not delphi_exe.is_file():
        raise RuntimeError(
            f"Couldn't find the delphi executable at {delphi_exe}. Is delphi installed (pip install -e .)?"
        )

    apps_dir = Path.home() / ".local" / "share" / "applications"
    icons_dir = Path.home() / ".local" / "share" / "icons"
    apps_dir.mkdir(parents=True, exist_ok=True)
    icons_dir.mkdir(parents=True, exist_ok=True)

    icon_path = icons_dir / "delphi.png"
    try:
        from delphi.tray import _build_icon_image

        _build_icon_image().save(icon_path)
    except Exception as e:
        raise RuntimeError(
            f"Couldn't generate the launcher icon: {e}. Install the optional dependency: "
            "pip install -e .[tray]"
        ) from e

    desktop_path = apps_dir / "delphi.desktop"
    desktop_path.write_text(_DESKTOP_ENTRY_TEMPLATE.format(exec_path=delphi_exe, icon_path=icon_path))
    desktop_path.chmod(0o755)
    return desktop_path
