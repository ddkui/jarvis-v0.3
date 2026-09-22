"""Automatic updates: periodically checks the git remote for new commits on
the current branch and, if any are found, fast-forwards and restarts the
running process into the new code.

On by default (DELPHI_ENABLE_AUTOUPDATE, default "1") for the long-running
background surfaces (`delphi tray`, `delphi dashboard`) and as a one-shot
startup check for `delphi chat`. Set DELPHI_ENABLE_AUTOUPDATE=0 to disable.

Only ever fast-forwards (fetch + `git merge --ff-only`) and only when the
working tree is clean - if there are uncommitted local changes (e.g. a
pending self-update, see self_update_tools.py) or local history has diverged
from the remote, it skips the update rather than risk discarding or
conflicting with anything. This is deliberately dumb and conservative: it is
not a merge tool.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time

from delphi.config import REPO_ROOT

_ENABLE_ENV_VAR = "DELPHI_ENABLE_AUTOUPDATE"
_INTERVAL_ENV_VAR = "DELPHI_AUTOUPDATE_INTERVAL"
_DEFAULT_INTERVAL_SECONDS = 3600


def is_enabled() -> bool:
    return os.environ.get(_ENABLE_ENV_VAR, "1") == "1"


def _interval_seconds() -> int:
    try:
        return max(60, int(os.environ.get(_INTERVAL_ENV_VAR, _DEFAULT_INTERVAL_SECONDS)))
    except ValueError:
        return _DEFAULT_INTERVAL_SECONDS


def _log(message: str) -> None:
    print(f"[autoupdate] {message}", file=sys.stderr, flush=True)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)


def _current_branch() -> str | None:
    result = _git("rev-parse", "--abbrev-ref", "HEAD")
    branch = result.stdout.strip()
    return branch if result.returncode == 0 and branch and branch != "HEAD" else None


def check_and_pull() -> bool:
    """Fetch the remote and fast-forward if there are new commits. Returns
    True if an update was pulled. Never touches the working tree if there are
    local changes or history has diverged - it just skips silently."""
    try:
        if not (REPO_ROOT / ".git").is_dir():
            return False
        branch = _current_branch()
        if branch is None:
            return False
        if _git("status", "--porcelain").stdout.strip():
            return False  # uncommitted local changes - don't touch it

        if _git("fetch", "origin", branch).returncode != 0:
            return False

        local = _git("rev-parse", "HEAD").stdout.strip()
        remote = _git("rev-parse", f"origin/{branch}").stdout.strip()
        if not local or not remote or local == remote:
            return False

        if _git("merge", "--ff-only", f"origin/{branch}").returncode != 0:
            _log("update available but local history has diverged - skipping")
            return False

        _log(f"pulled new commits on {branch}")
        return True
    except OSError:
        return False


def _restart() -> None:
    _log("restarting into the new code...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


def check_once_and_restart_if_updated() -> None:
    if is_enabled() and check_and_pull():
        _restart()


def run_background(interval_seconds: int | None = None) -> None:
    """Poll for updates forever on a background daemon thread; restarts the
    process in place (os.execv) the moment an update is found. No-op if
    auto-update is disabled."""
    if not is_enabled():
        return
    interval = interval_seconds if interval_seconds is not None else _interval_seconds()

    def _loop() -> None:
        while True:
            time.sleep(interval)
            if check_and_pull():
                _restart()

    threading.Thread(target=_loop, daemon=True).start()
