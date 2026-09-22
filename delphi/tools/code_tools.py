"""General-purpose code execution and file tools - lets Delphi write and run
code, and read/list/edit files, scoped to a working directory (DELPHI_CODE_DIR,
or the directory `delphi` was launched from if that's unset).

Disabled by default - this gives the model real, unconfirmed power to run
arbitrary code and read/write arbitrary files under the scoped root. Enable
deliberately with DELPHI_ENABLE_CODE=1 (see README.md "Writing & running
code").

Safety:
  - Every file/shell/python operation is confined to the scoped root: a path
    that resolves outside it is rejected before anything touches disk.
  - run_python/run_shell run with a timeout and their output is truncated, so
    a runaway command or huge output can't hang the agent loop or blow out
    the context window.
  - Every command run is logged to stderr as it happens, the same as
    computer-use, so whoever is watching the terminal sees it in real time.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from delphi.models import Tool

_ENABLE_ENV_VAR = "DELPHI_ENABLE_CODE"
_TIMEOUT_SECONDS = 60
_MAX_OUTPUT_CHARS = 4000


def _log(action: str) -> None:
    print(f"[code] {action}", file=sys.stderr, flush=True)


def _code_root() -> Path:
    return Path(os.environ.get("DELPHI_CODE_DIR", os.getcwd())).resolve()


def _resolve_scoped(root: Path, rel_path: str) -> Path:
    candidate = (root / rel_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"path {rel_path!r} is outside the working directory ({root})")
    return candidate


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    hidden = len(text) - _MAX_OUTPUT_CHARS
    return text[:_MAX_OUTPUT_CHARS] + f"\n... (truncated, {hidden} more chars)"


def _run(args: list[str], cwd: Path) -> str:
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return f"Timed out after {_TIMEOUT_SECONDS}s."
    except OSError as e:
        return f"Failed to run: {e}"
    output = result.stdout
    if result.stderr:
        output += ("\n" if output else "") + "[stderr]\n" + result.stderr
    output += f"\n[exit code {result.returncode}]"
    return _truncate(output)


def build_tools() -> list[Tool]:
    if os.environ.get(_ENABLE_ENV_VAR) != "1":
        return []

    root = _code_root()

    def run_python(args: dict) -> str:
        code = args.get("code")
        if not code:
            raise ValueError("missing required field: code")
        _log(f"run_python ({len(code)} chars) in {root}")
        return _run([sys.executable, "-c", code], cwd=root)

    def run_shell(args: dict) -> str:
        command = args.get("command")
        if not command:
            raise ValueError("missing required field: command")
        _log(f"run_shell: {command}")
        return _run(["/bin/sh", "-c", command], cwd=root)

    def read_file(args: dict) -> str:
        path = args.get("path")
        if not path:
            raise ValueError("missing required field: path")
        target = _resolve_scoped(root, path)
        if not target.is_file():
            return f"No file found at {path}"
        _log(f"read_file {path}")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_file(args: dict) -> str:
        path = args.get("path")
        content = args.get("content")
        if not path or content is None:
            raise ValueError("missing required field: path/content")
        target = _resolve_scoped(root, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        _log(f"write_file {path} ({len(content)} chars)")
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} chars to {path}"

    def list_dir(args: dict) -> str:
        path = args.get("path") or "."
        target = _resolve_scoped(root, path)
        if not target.is_dir():
            return f"No directory found at {path}"
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        if not entries:
            return "(empty)"
        return "\n".join(f"{'file' if e.is_file() else 'dir '} {e.relative_to(root)}" for e in entries)

    return [
        Tool(
            name="run_python",
            description=(
                f"Run a Python snippet in the working directory ({root}). Returns stdout/stderr "
                f"and the exit code. Times out after {_TIMEOUT_SECONDS}s; output is truncated if huge."
            ),
            input_schema={
                "type": "object",
                "properties": {"code": {"type": "string", "description": "Python source to execute"}},
                "required": ["code"],
            },
            handler=run_python,
        ),
        Tool(
            name="run_shell",
            description=(
                f"Run a shell command in the working directory ({root}). Returns stdout/stderr "
                f"and the exit code. Times out after {_TIMEOUT_SECONDS}s; output is truncated if huge."
            ),
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Shell command to execute"}},
                "required": ["command"],
            },
            handler=run_shell,
        ),
        Tool(
            name="read_file",
            description="Read a text file's full contents by path, relative to the working directory.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to the working directory"}},
                "required": ["path"],
            },
            handler=read_file,
        ),
        Tool(
            name="write_file",
            description="Create or overwrite a text file by path, relative to the working directory.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the working directory"},
                    "content": {"type": "string", "description": "Full new contents of the file"},
                },
                "required": ["path", "content"],
            },
            handler=write_file,
        ),
        Tool(
            name="list_dir",
            description="List files and subdirectories at a path relative to the working directory (default: its root).",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to the working directory (default: '.')"}},
                "required": [],
            },
            handler=list_dir,
        ),
    ]
