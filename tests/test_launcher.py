import platform
import sys
from pathlib import Path

import pytest

from jarvis import launcher

_jarvis_exe_installed = (Path(sys.executable).parent / "jarvis").is_file()
_requires_linux_jarvis_install = pytest.mark.skipif(
    platform.system() != "Linux" or not _jarvis_exe_installed,
    reason="requires Linux with jarvis installed (pip install -e .)",
)


def test_install_launcher_raises_on_non_linux(monkeypatch):
    monkeypatch.setattr(launcher.platform, "system", lambda: "Darwin")
    with pytest.raises(RuntimeError, match="only supported on Linux"):
        launcher.install_launcher()


def test_install_launcher_raises_when_executable_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.platform, "system", lambda: "Linux")
    monkeypatch.setattr(launcher.sys, "executable", str(tmp_path / "nonexistent" / "python"))
    with pytest.raises(RuntimeError, match="Couldn't find the jarvis executable"):
        launcher.install_launcher()


@_requires_linux_jarvis_install
def test_install_launcher_writes_desktop_file_and_icon(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    desktop_path = launcher.install_launcher()

    assert desktop_path == fake_home / ".local" / "share" / "applications" / "jarvis.desktop"
    assert desktop_path.is_file()

    content = desktop_path.read_text()
    assert "[Desktop Entry]" in content
    assert "Name=Jarvis" in content
    assert f"Exec={sys.executable.rsplit('/', 1)[0]}/jarvis tray" in content

    icon_path = fake_home / ".local" / "share" / "icons" / "jarvis.png"
    assert icon_path.is_file()
    assert f"Icon={icon_path}" in content


@_requires_linux_jarvis_install
def test_install_launcher_wraps_icon_generation_failure(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    def _broken_icon():
        raise ImportError("no module named PIL")

    monkeypatch.setattr("jarvis.tray._build_icon_image", _broken_icon)

    with pytest.raises(RuntimeError, match="Couldn't generate the launcher icon"):
        launcher.install_launcher()
