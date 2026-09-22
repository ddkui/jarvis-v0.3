"""Persisted voice settings (active voice, intonation, speaking rate) - edited via
`delphi dashboard` or by hand. Stored as JSON at <vault_dir>/.delphi/voice_settings.json,
separate from .env: .env is secrets/environment config, this is user preference state
that a local web UI reads and writes.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

EXAGGERATION_RANGE = (0.0, 2.0)
CFG_WEIGHT_RANGE = (0.0, 1.0)
SPEAKING_RATE_RANGE = (0.5, 2.0)


def clamp(value: float, bounds: tuple[float, float]) -> float:
    lo, hi = bounds
    return max(lo, min(hi, value))


@dataclass
class VoiceSettings:
    active_voice: str | None = None
    exaggeration: float = 0.5
    cfg_weight: float = 0.5
    speaking_rate: float = 1.0
    voices: dict[str, str] = field(default_factory=dict)


def _settings_path(vault_dir: Path) -> Path:
    return vault_dir / ".delphi" / "voice_settings.json"


def load_settings(vault_dir: Path) -> VoiceSettings:
    path = _settings_path(vault_dir)
    if not path.is_file():
        return VoiceSettings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return VoiceSettings()
    return VoiceSettings(
        active_voice=data.get("active_voice"),
        exaggeration=clamp(float(data.get("exaggeration", 0.5)), EXAGGERATION_RANGE),
        cfg_weight=clamp(float(data.get("cfg_weight", 0.5)), CFG_WEIGHT_RANGE),
        speaking_rate=clamp(float(data.get("speaking_rate", 1.0)), SPEAKING_RATE_RANGE),
        voices=dict(data.get("voices", {})),
    )


def save_settings(vault_dir: Path, settings: VoiceSettings) -> None:
    path = _settings_path(vault_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")


def add_voice(vault_dir: Path, name: str, source_path: Path) -> Path:
    """Copy a reference audio file into the vault's voices dir and register it by name."""
    if not name.strip():
        raise ValueError("voice name must not be empty")
    voices_dir = vault_dir / ".delphi" / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    dest = voices_dir / f"{name}{source_path.suffix or '.wav'}"
    dest.write_bytes(source_path.read_bytes())

    settings = load_settings(vault_dir)
    settings.voices[name] = str(dest)
    save_settings(vault_dir, settings)
    return dest


def remove_voice(vault_dir: Path, name: str) -> bool:
    settings = load_settings(vault_dir)
    if name not in settings.voices:
        return False
    path = Path(settings.voices.pop(name))
    if settings.active_voice == name:
        settings.active_voice = None
    save_settings(vault_dir, settings)
    path.unlink(missing_ok=True)
    return True
