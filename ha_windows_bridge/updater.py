from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

LATEST_RELEASE_API = "https://api.github.com/repos/Grzechu51/ha-windows-bridge/releases/latest"
MAX_RELEASE_RESPONSE = 256 * 1024
_VERSION = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$")


@dataclass(frozen=True, slots=True)
class UpdateInfo:
    current_version: str
    latest_version: str = ""
    release_url: str = ""
    available: bool = False
    error: str = ""


def _version_tuple(value: str) -> tuple[int, int, int] | None:
    match = _VERSION.fullmatch(value.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def parse_release(payload: Any, current_version: str) -> UpdateInfo:
    if not isinstance(payload, dict):
        return UpdateInfo(current_version, error="GitHub returned an invalid response")
    tag = payload.get("tag_name")
    url = payload.get("html_url")
    current = _version_tuple(current_version)
    latest = _version_tuple(tag) if isinstance(tag, str) else None
    if current is None or latest is None or not isinstance(url, str):
        return UpdateInfo(current_version, error="The release version could not be read")
    return UpdateInfo(
        current_version=current_version,
        latest_version=".".join(str(part) for part in latest),
        release_url=url if url.startswith("https://github.com/") else "",
        available=latest > current,
    )


class GitHubUpdateChecker:
    """Check the official GitHub release feed; installation needs user consent."""

    def check(self, current_version: str, timeout: float = 8.0) -> UpdateInfo:
        request = urllib.request.Request(
            LATEST_RELEASE_API,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "HA-Windows-Bridge",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # nosec B310
                raw = response.read(MAX_RELEASE_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            return UpdateInfo(current_version, error=f"GitHub HTTP {exc.code}")
        except (OSError, urllib.error.URLError):
            return UpdateInfo(current_version, error="GitHub is unavailable")
        if len(raw) > MAX_RELEASE_RESPONSE:
            return UpdateInfo(current_version, error="GitHub response is too large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return UpdateInfo(current_version, error="GitHub returned an invalid response")
        return parse_release(payload, current_version)
