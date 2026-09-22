import subprocess
from pathlib import Path

import pytest

from delphi import autoupdate


def _init_repo_with_remote(tmp_path: Path):
    remote = tmp_path / "remote.git"
    # --initial-branch=main so the bare repo's HEAD resolves to refs/heads/main
    # from the start - otherwise later clones (before "main" exists) can't tell
    # which branch to check out and silently default to "master" instead,
    # splitting the two clones onto different branches.
    subprocess.run(["git", "init", "-q", "--bare", "--initial-branch=main", str(remote)], check=True)

    local = tmp_path / "local"
    local.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=local, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=local, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=local, check=True)
    (local / "f.txt").write_text("v1\n")
    subprocess.run(["git", "add", "-A"], cwd=local, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "v1"], cwd=local, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=local, check=True)
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=local, check=True)
    subprocess.run(["git", "push", "-q", "-u", "origin", "main"], cwd=local, check=True)
    return remote, local


def _push_new_commit(tmp_path: Path, remote: Path, clone_name: str, content: str, message: str):
    clone = tmp_path / clone_name
    subprocess.run(["git", "clone", "-q", str(remote), str(clone)], check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=clone, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=clone, check=True)
    (clone / "f.txt").write_text(content)
    subprocess.run(["git", "add", "-A"], cwd=clone, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=clone, check=True)
    subprocess.run(["git", "push", "-q"], cwd=clone, check=True)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    remote, local = _init_repo_with_remote(tmp_path)
    monkeypatch.setattr(autoupdate, "REPO_ROOT", local)
    return local


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_AUTOUPDATE", "0")
    assert autoupdate.is_enabled() is False


def test_enabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_AUTOUPDATE", raising=False)
    assert autoupdate.is_enabled() is True


def test_check_and_pull_no_updates(repo):
    assert autoupdate.check_and_pull() is False


def test_check_and_pull_pulls_new_commit(tmp_path, repo):
    _push_new_commit(tmp_path, tmp_path / "remote.git", "other", "v2\n", "v2")

    assert autoupdate.check_and_pull() is True
    assert (repo / "f.txt").read_text() == "v2\n"


def test_check_and_pull_skips_when_local_changes_present(tmp_path, repo):
    (repo / "f.txt").write_text("local edit\n")
    _push_new_commit(tmp_path, tmp_path / "remote.git", "other", "v2\n", "v2")

    assert autoupdate.check_and_pull() is False
    assert (repo / "f.txt").read_text() == "local edit\n"


def test_check_and_pull_ignores_untracked_files(tmp_path, repo):
    (repo / "start-delphi.vbs").write_text("' launcher script, not part of the repo\n")
    _push_new_commit(tmp_path, tmp_path / "remote.git", "other", "v2\n", "v2")

    assert autoupdate.check_and_pull() is True
    assert (repo / "f.txt").read_text() == "v2\n"
    assert (repo / "start-delphi.vbs").is_file()


def test_check_and_pull_skips_when_diverged(tmp_path, repo):
    (repo / "f.txt").write_text("local v2\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "local v2"], cwd=repo, check=True)

    _push_new_commit(tmp_path, tmp_path / "remote.git", "other", "remote v2\n", "remote v2")

    assert autoupdate.check_and_pull() is False
    assert (repo / "f.txt").read_text() == "local v2\n"


def test_check_and_pull_returns_false_without_git_dir(tmp_path, monkeypatch):
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()
    monkeypatch.setattr(autoupdate, "REPO_ROOT", plain_dir)
    assert autoupdate.check_and_pull() is False


def test_check_once_and_restart_if_updated_restarts_on_update(monkeypatch):
    monkeypatch.setattr(autoupdate, "is_enabled", lambda: True)
    monkeypatch.setattr(autoupdate, "check_and_pull", lambda: True)
    restarted = []
    monkeypatch.setattr(autoupdate, "_restart", lambda: restarted.append(True))

    autoupdate.check_once_and_restart_if_updated()

    assert restarted == [True]


def test_check_once_and_restart_if_updated_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(autoupdate, "is_enabled", lambda: False)
    called = []
    monkeypatch.setattr(autoupdate, "check_and_pull", lambda: called.append(True) or True)
    restarted = []
    monkeypatch.setattr(autoupdate, "_restart", lambda: restarted.append(True))

    autoupdate.check_once_and_restart_if_updated()

    assert called == []
    assert restarted == []


def test_check_once_and_restart_if_updated_noop_when_no_update(monkeypatch):
    monkeypatch.setattr(autoupdate, "is_enabled", lambda: True)
    monkeypatch.setattr(autoupdate, "check_and_pull", lambda: False)
    restarted = []
    monkeypatch.setattr(autoupdate, "_restart", lambda: restarted.append(True))

    autoupdate.check_once_and_restart_if_updated()

    assert restarted == []


def test_run_background_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(autoupdate, "is_enabled", lambda: False)
    created = []
    monkeypatch.setattr(autoupdate.threading, "Thread", lambda *a, **k: created.append(1))

    autoupdate.run_background()

    assert created == []


def test_run_background_starts_a_daemon_thread(monkeypatch):
    monkeypatch.setattr(autoupdate, "is_enabled", lambda: True)
    captured = {}

    class FakeThread:
        def __init__(self, target=None, daemon=None):
            captured["target"] = target
            captured["daemon"] = daemon

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(autoupdate.threading, "Thread", FakeThread)

    autoupdate.run_background(interval_seconds=1)

    assert captured["daemon"] is True
    assert captured["started"] is True


def test_interval_seconds_env_var(monkeypatch):
    monkeypatch.setenv("DELPHI_AUTOUPDATE_INTERVAL", "120")
    assert autoupdate._interval_seconds() == 120


def test_interval_seconds_clamped_to_minimum(monkeypatch):
    monkeypatch.setenv("DELPHI_AUTOUPDATE_INTERVAL", "5")
    assert autoupdate._interval_seconds() == 60


def test_interval_seconds_falls_back_on_garbage(monkeypatch):
    monkeypatch.setenv("DELPHI_AUTOUPDATE_INTERVAL", "not-a-number")
    assert autoupdate._interval_seconds() == autoupdate._DEFAULT_INTERVAL_SECONDS


def test_restart_reexecs_via_module_not_argv0(monkeypatch):
    # Regression: on Windows, pip's console-script wrapper leaves sys.argv[0]
    # as something like "...\Scripts\delphi" with no extension - python.exe
    # can't open that as a script (WinError 2). Restart must go through
    # `-m delphi.cli` with the real args, never replay sys.argv[0] directly.
    monkeypatch.setattr(autoupdate.sys, "argv", ["C:\\weird\\path\\delphi", "tray", "--port", "9000"])
    calls = []
    monkeypatch.setattr(autoupdate.os, "execv", lambda *a: calls.append(a))

    autoupdate._restart()

    assert calls == [
        (autoupdate.sys.executable, [autoupdate.sys.executable, "-m", "delphi.cli", "tray", "--port", "9000"])
    ]
