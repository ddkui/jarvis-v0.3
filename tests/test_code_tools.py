from pathlib import Path

import pytest

from delphi.tools import code_tools


def _tools_by_name(tools):
    return {t.name: t for t in tools}


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_CODE", raising=False)
    assert code_tools.build_tools() == []


def test_disabled_when_env_var_not_exactly_one(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "true")
    assert code_tools.build_tools() == []


def test_enabled_exposes_all_tools(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    tools = _tools_by_name(code_tools.build_tools())
    assert set(tools) == {"run_python", "run_shell", "read_file", "write_file", "list_dir"}


def test_run_python_returns_stdout_and_exit_code(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    tools = _tools_by_name(code_tools.build_tools())

    result = tools["run_python"].handler({"code": "print('hi there')"})

    assert "hi there" in result
    assert "[exit code 0]" in result


def test_run_python_missing_code_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    tools = _tools_by_name(code_tools.build_tools())

    with pytest.raises(ValueError):
        tools["run_python"].handler({})


def test_run_shell_returns_output(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    tools = _tools_by_name(code_tools.build_tools())

    result = tools["run_shell"].handler({"command": "echo hello-shell"})

    assert "hello-shell" in result
    assert "[exit code 0]" in result


def test_run_shell_captures_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    tools = _tools_by_name(code_tools.build_tools())

    result = tools["run_shell"].handler({"command": "exit 3"})

    assert "[exit code 3]" in result


def test_run_python_times_out(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    monkeypatch.setattr(code_tools, "_TIMEOUT_SECONDS", 1)
    tools = _tools_by_name(code_tools.build_tools())

    result = tools["run_python"].handler({"code": "import time; time.sleep(5)"})

    assert "Timed out" in result


def test_write_then_read_file_round_trip(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    tools = _tools_by_name(code_tools.build_tools())

    write_result = tools["write_file"].handler({"path": "hello.txt", "content": "hi"})
    assert "Wrote 2 chars" in write_result

    read_result = tools["read_file"].handler({"path": "hello.txt"})
    assert read_result == "hi"
    assert (tmp_path / "hello.txt").read_text() == "hi"


def test_write_file_creates_parent_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    tools = _tools_by_name(code_tools.build_tools())

    tools["write_file"].handler({"path": "sub/dir/file.txt", "content": "nested"})

    assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"


def test_read_file_missing_returns_message_not_error(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    tools = _tools_by_name(code_tools.build_tools())

    result = tools["read_file"].handler({"path": "does-not-exist.txt"})

    assert "No file found" in result


def test_list_dir_lists_files_and_dirs(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    (tmp_path / "a.txt").write_text("x")
    (tmp_path / "subdir").mkdir()
    tools = _tools_by_name(code_tools.build_tools())

    result = tools["list_dir"].handler({})

    assert "a.txt" in result
    assert "subdir" in result


def test_list_dir_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    tools = _tools_by_name(code_tools.build_tools())

    assert tools["list_dir"].handler({}) == "(empty)"


def test_path_traversal_outside_root_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    scoped_dir = tmp_path / "scoped"
    scoped_dir.mkdir()
    monkeypatch.setenv("DELPHI_CODE_DIR", str(scoped_dir))
    (tmp_path / "secret.txt").write_text("outside")
    tools = _tools_by_name(code_tools.build_tools())

    with pytest.raises(ValueError, match="outside the working directory"):
        tools["read_file"].handler({"path": "../secret.txt"})


def test_output_is_truncated(monkeypatch, tmp_path):
    monkeypatch.setenv("DELPHI_ENABLE_CODE", "1")
    monkeypatch.setenv("DELPHI_CODE_DIR", str(tmp_path))
    monkeypatch.setattr(code_tools, "_MAX_OUTPUT_CHARS", 50)
    tools = _tools_by_name(code_tools.build_tools())

    result = tools["run_python"].handler({"code": "print('x' * 500)"})

    assert "truncated" in result
    assert len(result) < 500
