"""Self-improvement tools - lets Delphi read, edit, test, and (on your explicit
approval) commit-and-restart itself into changes to its OWN source code (this
repository, at delphi.config.REPO_ROOT).

Disabled by default - this is Delphi modifying and redeploying the code it
runs as. Enable deliberately with DELPHI_ENABLE_SELF_UPDATE=1 (see README.md
"Self-improvement").

The apply step is a hard gate, not a formality: apply_pending_changes
independently re-runs the full test suite and refuses to commit or restart on
a single failing test, whatever the model believes about its own change. The
system prompt separately instructs the model to always show the diff and test
results and wait for the user to explicitly say to proceed - in a later turn,
never the same one the edits were made in - before calling
apply_pending_changes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from delphi.config import REPO_ROOT
from delphi.models import Tool

_ENABLE_ENV_VAR = "DELPHI_ENABLE_SELF_UPDATE"
_TEST_TIMEOUT_SECONDS = 300
_MAX_OUTPUT_CHARS = 4000


def _log(action: str) -> None:
    print(f"[self-update] {action}", file=sys.stderr, flush=True)


def _resolve_scoped(rel_path: str) -> Path:
    candidate = (REPO_ROOT / rel_path).resolve()
    if candidate != REPO_ROOT and REPO_ROOT not in candidate.parents:
        raise ValueError(f"path {rel_path!r} is outside the Delphi repository ({REPO_ROOT})")
    return candidate


def _truncate(text: str) -> str:
    if len(text) <= _MAX_OUTPUT_CHARS:
        return text
    hidden = len(text) - _MAX_OUTPUT_CHARS
    return text[:_MAX_OUTPUT_CHARS] + f"\n... (truncated, {hidden} more chars)"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, text=True)


def _run_tests() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=_TEST_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return False, f"Test suite timed out after {_TEST_TIMEOUT_SECONDS}s."
    except OSError as e:
        return False, f"Couldn't run the test suite: {e}"
    output = (result.stdout + "\n" + result.stderr).strip()
    return result.returncode == 0, output


def _restart() -> None:
    _log("restarting into the new code...")
    os.execv(sys.executable, [sys.executable] + sys.argv)


def build_tools() -> list[Tool]:
    if os.environ.get(_ENABLE_ENV_VAR) != "1":
        return []

    def read_own_file(args: dict) -> str:
        path = args.get("path")
        if not path:
            raise ValueError("missing required field: path")
        target = _resolve_scoped(path)
        if not target.is_file():
            return f"No file found at {path}"
        _log(f"read {path}")
        return target.read_text(encoding="utf-8", errors="replace")

    def write_own_file(args: dict) -> str:
        path = args.get("path")
        content = args.get("content")
        if not path or content is None:
            raise ValueError("missing required field: path/content")
        target = _resolve_scoped(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        _log(f"write {path} ({len(content)} chars)")
        target.write_text(content, encoding="utf-8")
        return (
            f"Wrote {len(content)} chars to {path}. Not committed - call view_pending_changes to "
            "review the diff, then run_own_tests, then tell the user what changed and wait for "
            "them to explicitly say to apply it before calling apply_pending_changes."
        )

    def list_own_dir(args: dict) -> str:
        path = args.get("path") or "."
        target = _resolve_scoped(path)
        if not target.is_dir():
            return f"No directory found at {path}"
        entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))
        if not entries:
            return "(empty)"
        return "\n".join(f"{'file' if e.is_file() else 'dir '} {e.relative_to(REPO_ROOT)}" for e in entries)

    def view_pending_changes(_args: dict) -> str:
        status = _git("status", "--short").stdout
        if not status.strip():
            return "No pending changes."
        diff = _git("diff").stdout
        return _truncate(f"Status:\n{status}\nDiff:\n{diff}")

    def run_own_tests(_args: dict) -> str:
        _log("running the test suite")
        ok, output = _run_tests()
        return f"{'PASSED' if ok else 'FAILED'}\n{_truncate(output)}"

    def discard_pending_changes(_args: dict) -> str:
        _log("discarding pending changes")
        _git("checkout", "--", ".")
        _git("clean", "-fd")
        return "Discarded all uncommitted changes."

    def apply_pending_changes(args: dict) -> str:
        commit_message = args.get("commit_message")
        if not commit_message:
            raise ValueError("missing required field: commit_message")
        status = _git("status", "--short")
        if not status.stdout.strip():
            return "Nothing to apply - no pending changes."

        _log("re-running the test suite before applying")
        ok, output = _run_tests()
        if not ok:
            return f"Refusing to apply: the test suite failed.\n{_truncate(output)}"

        _git("add", "-A")
        commit = _git("commit", "-m", commit_message)
        if commit.returncode != 0:
            return f"Commit failed:\n{_truncate(commit.stdout + commit.stderr)}"
        _log(f"committed: {commit_message}")

        _restart()
        return "Applied and restarting."  # pragma: no cover - execv replaces the process

    return [
        Tool(
            name="read_own_file",
            description="Read a file from Delphi's own source repository by path (relative to the repo root).",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to the repo root"}},
                "required": ["path"],
            },
            handler=read_own_file,
        ),
        Tool(
            name="write_own_file",
            description=(
                "Create or overwrite a file in Delphi's own source repository. This only edits the "
                "working tree - it is never committed or applied automatically. Always follow with "
                "view_pending_changes and run_own_tests, then wait for the user's go-ahead."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path relative to the repo root"},
                    "content": {"type": "string", "description": "Full new contents of the file"},
                },
                "required": ["path", "content"],
            },
            handler=write_own_file,
        ),
        Tool(
            name="list_own_dir",
            description="List files and subdirectories in Delphi's own repository at a path relative to the repo root (default: repo root).",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Path relative to the repo root (default: '.')"}},
                "required": [],
            },
            handler=list_own_dir,
        ),
        Tool(
            name="view_pending_changes",
            description="Show the current uncommitted diff against Delphi's own repository (git status + git diff).",
            input_schema={"type": "object", "properties": {}},
            handler=view_pending_changes,
        ),
        Tool(
            name="run_own_tests",
            description="Run Delphi's own test suite against the current working tree (including any pending edits) and report pass/fail.",
            input_schema={"type": "object", "properties": {}},
            handler=run_own_tests,
        ),
        Tool(
            name="discard_pending_changes",
            description="Throw away all uncommitted edits to Delphi's own repository, restoring it to the last commit.",
            input_schema={"type": "object", "properties": {}},
            handler=discard_pending_changes,
        ),
        Tool(
            name="apply_pending_changes",
            description=(
                "Commit the current pending changes to Delphi's own repository and restart into them. "
                "Independently re-runs the test suite first and refuses if it fails. Only call this "
                "after the user has seen the diff and test results and explicitly told you to apply it "
                "- never in the same turn you made the edits."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "commit_message": {"type": "string", "description": "Git commit message describing the change"}
                },
                "required": ["commit_message"],
            },
            handler=apply_pending_changes,
        ),
    ]
