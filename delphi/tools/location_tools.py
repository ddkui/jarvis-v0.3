"""Approximate (IP-based) location for the agent - lets it give location-aware
answers (local weather, "things near me", timezone-correct scheduling)
without needing OS-level GPS/location permissions, which Python has no good
cross-platform story for on a desktop app anyway.

City-level accuracy only, not GPS-precise. Off by default - enable with
DELPHI_ENABLE_LOCATION=1 - since every call reveals your IP-derived location
to a third-party API (ipapi.co, no account/key required) rather than staying
fully local like the rest of Delphi's tools.
"""

from __future__ import annotations

import json
import os
import urllib.request

from delphi.models import Tool

_ENABLE_ENV_VAR = "DELPHI_ENABLE_LOCATION"
_API_URL = "https://ipapi.co/json/"
_TIMEOUT_SECONDS = 5


def is_enabled() -> bool:
    return os.environ.get(_ENABLE_ENV_VAR) == "1"


def _fetch_location() -> dict:
    with urllib.request.urlopen(_API_URL, timeout=_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def build_tools() -> list[Tool]:
    if not is_enabled():
        return []

    def get_location(input: dict) -> str:
        try:
            data = _fetch_location()
        except Exception as e:
            return f"Couldn't determine location: {e}"
        if data.get("error"):
            return f"Couldn't determine location: {data.get('reason', 'unknown error')}"

        parts = [p for p in (data.get("city"), data.get("region"), data.get("country_name")) if p]
        location = ", ".join(parts) if parts else "unknown"
        timezone = data.get("timezone", "unknown")
        return f"Approximate location: {location} (timezone: {timezone})"

    return [
        Tool(
            name="get_location",
            description=(
                "Get the user's approximate current location (city-level, via IP "
                "geolocation) and local timezone. Use this for location-aware answers "
                "(weather, nearby places) or to reason about the user's timezone."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=get_location,
        )
    ]
