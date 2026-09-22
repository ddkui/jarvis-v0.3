import subprocess
from pathlib import Path

import pytest

from delphi.tools import self_update_tools


def _tools_by_name(tools):
    return {t.name: t for t in tools}


def _init_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    (root / "README.md").write_text("hello\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=root, check=True)
    return root


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = _init_repo(tmp_path)
    monkeypatch.setattr(self_update_tools, "REPO_ROOT", root)
    return root


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_SELF_UPDATE", raising=False)
    assert self_update_tools.build_tools() == []


def test_disabled_when_env_var_not_exactly_one(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "true")
    assert self_update_tools.build_tools() == []


def test_enabled_exposes_all_tools(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())
    assert set(tools) == {
        "read_own_file",
        "write_own_file",
        "list_own_dir",
        "view_pending_changes",
        "run_own_tests",
        "discard_pending_changes",
        "apply_pending_changes",
    }


def test_read_own_file(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())
    assert tools["read_own_file"].handler({"path": "README.md"}) == "hello\n"


def test_read_own_file_missing_returns_message_not_error(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())
    assert "No file found" in tools["read_own_file"].handler({"path": "nope.txt"})


def test_write_own_file_edits_working_tree_without_committing(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())

    result = tools["write_own_file"].handler({"path": "new.py", "content": "print(1)\n"})

    assert "Not committed" in result
    assert (repo / "new.py").read_text() == "print(1)\n"
    status = subprocess.run(["git", "status", "--short"], cwd=repo, capture_output=True, text=True).stdout
    assert "new.py" in status


def test_write_own_file_creates_parent_dirs(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())

    tools["write_own_file"].handler({"path": "sub/dir/new.py", "content": "x"})

    assert (repo / "sub" / "dir" / "new.py").read_text() == "x"


def test_path_traversal_outside_repo_is_rejected(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())
    with pytest.raises(ValueError, match="outside the Delphi repository"):
        tools["read_own_file"].handler({"path": "../outside.txt"})


def test_list_own_dir(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())
    assert "README.md" in tools["list_own_dir"].handler({})


def test_view_pending_changes_none(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())
    assert tools["view_pending_changes"].handler({}) == "No pending changes."


def test_view_pending_changes_shows_diff(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    (repo / "README.md").write_text("changed\n")
    tools = _tools_by_name(self_update_tools.build_tools())
    result = tools["view_pending_changes"].handler({})
    assert "README.md" in result
    assert "changed" in result


def test_discard_pending_changes(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    (repo / "README.md").write_text("changed\n")
    (repo / "untracked.txt").write_text("junk")
    tools = _tools_by_name(self_update_tools.build_tools())

    result = tools["discard_pending_changes"].handler({})

    assert "Discarded" in result
    assert (repo / "README.md").read_text() == "hello\n"
    assert not (repo / "untracked.txt").exists()


def test_run_own_tests_reports_pass(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    monkeypatch.setattr(self_update_tools, "_run_tests", lambda: (True, "2 passed"))
    tools = _tools_by_name(self_update_tools.build_tools())
    result = tools["run_own_tests"].handler({})
    assert result.startswith("PASSED")
    assert "2 passed" in result


def test_run_own_tests_reports_failure(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    monkeypatch.setattr(self_update_tools, "_run_tests", lambda: (False, "1 failed"))
    tools = _tools_by_name(self_update_tools.build_tools())
    assert tools["run_own_tests"].handler({}).startswith("FAILED")


def test_apply_pending_changes_nothing_to_apply(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    tools = _tools_by_name(self_update_tools.build_tools())
    assert "Nothing to apply" in tools["apply_pending_changes"].handler({"commit_message": "x"})


def test_apply_pending_changes_missing_commit_message_raises(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    (repo / "README.md").write_text("changed\n")
    tools = _tools_by_name(self_update_tools.build_tools())
    with pytest.raises(ValueError):
        tools["apply_pending_changes"].handler({})


def test_apply_pending_changes_refuses_when_tests_fail(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    (repo / "README.md").write_text("changed\n")
    monkeypatch.setattr(self_update_tools, "_run_tests", lambda: (False, "1 failed"))
    restarted = []
    monkeypatch.setattr(self_update_tools, "_restart", lambda: restarted.append(True))
    tools = _tools_by_name(self_update_tools.build_tools())

    result = tools["apply_pending_changes"].handler({"commit_message": "should not land"})

    assert "Refusing to apply" in result
    assert restarted == []
    log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True).stdout
    assert "should not land" not in log
    # the failing edit is left in place, uncommitted, for the model/user to keep iterating on
    assert (repo / "README.md").read_text() == "changed\n"


def test_apply_pending_changes_commits_and_restarts_when_tests_pass(monkeypatch, repo):
    monkeypatch.setenv("DELPHI_ENABLE_SELF_UPDATE", "1")
    (repo / "README.md").write_text("changed\n")
    monkeypatch.setattr(self_update_tools, "_run_tests", lambda: (True, "ok"))
    restarted = []
    monkeypatch.setattr(self_update_tools, "_restart", lambda: restarted.append(True))
    tools = _tools_by_name(self_update_tools.build_tools())

    tools["apply_pending_changes"].handler({"commit_message": "improve readme"})

    assert restarted == [True]
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=repo, capture_output=True, text=True).stdout
    assert "improve readme" in log
    status = subprocess.run(["git", "status", "--short"], cwd=repo, capture_output=True, text=True).stdout
    assert status.strip() == ""


def test_run_tests_integration_reports_pass(repo):
    (repo / "test_trivial.py").write_text("def test_ok():\n    assert 1 == 1\n")
    ok, output = self_update_tools._run_tests()
    assert ok is True
    assert "1 passed" in output


def test_run_tests_integration_reports_failure(repo):
    (repo / "test_trivial.py").write_text("def test_bad():\n    assert False\n")
    ok, _output = self_update_tools._run_tests()
    assert ok is False
