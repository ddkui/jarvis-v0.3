"""Provider API keys via the OS keychain (macOS Keychain, Windows Credential
Locker, Linux Secret Service), with a silent fallback to plain env vars/.env
wherever no OS keychain is available (headless servers, containers, CI) — jarvis
still has to run there, just without the extra protection.
"""

from __future__ import annotations

import os

import keyring
import keyring.errors

_SERVICE_NAME = "jarvis"


def get_secret(name: str) -> str | None:
    try:
        return keyring.get_password(_SERVICE_NAME, name)
    except keyring.errors.KeyringError:
        return None


def set_secret(name: str, value: str) -> None:
    keyring.set_password(_SERVICE_NAME, name, value)


def delete_secret(name: str) -> bool:
    try:
        keyring.delete_password(_SERVICE_NAME, name)
        return True
    except keyring.errors.KeyringError:
        # Covers both "nothing stored under this name" (PasswordDeleteError) and
        # "no keychain backend available at all" (NoKeyringError, a sibling class,
        # not a PasswordDeleteError subclass) - both degrade to "nothing to remove".
        return False


def apply_to_environ(names: list[str]) -> None:
    """For each name not already set in the environment, fill it in from the
    keychain if present. Shell env and .env (already loaded by this point) both
    take priority — this only fills gaps, matching how .env itself defers to the
    real shell environment."""
    for name in names:
        if name in os.environ:
            continue
        value = get_secret(name)
        if value:
            os.environ[name] = value


KNOWN_KEYS = [
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GROQ_API_KEY",
]
