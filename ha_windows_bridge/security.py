"""Secret redaction shared by diagnostics and application log formatters."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any
from urllib.parse import quote

REDACTED = "<redacted>"
_SECRET_KEYS = frozenset({"password", "token", "access_token", "authorization", "secret", "api_key"})
_ASSIGNMENT = re.compile(
    r'''(?ix)(["']?(?:password|access_token|token|authorization|secret|api_key)["']?\s*[:=]\s*)
    (?:"[^"\r\n]*"|'[^'\r\n]*'|(?:Bearer\s+)?[^\s,;}]+)'''
)
_BEARER = re.compile(r"(?i)\bBearer\s+[^\s\"',;}]+")
_URL_CREDENTIALS = re.compile(r"(?i)(https?|wss?|mqtts?)://[^\s/@]+:[^\s/@]+@")


def redact_text(text: str, secrets: Iterable[str] = ()) -> str:
    values = {variant for value in secrets if value for variant in (value, quote(value, safe=""))}
    if values:
        pattern = "|".join(re.escape(value) for value in sorted(values, key=len, reverse=True))
        text = re.sub(pattern, lambda _match: REDACTED, text)
    text = _URL_CREDENTIALS.sub(lambda match: f"{match[1]}://{REDACTED}@", text)
    text = _ASSIGNMENT.sub(lambda match: f"{match[1]}{REDACTED}", text)
    return _BEARER.sub(f"Bearer {REDACTED}", text)


def redact_data(value: Any, secrets: Iterable[str] = ()) -> Any:
    """Return a redacted copy, never mutate runtime/configuration objects."""
    secrets = tuple(secrets)
    if isinstance(value, Mapping):
        return {
            redact_text(str(key), secrets): (
                REDACTED if str(key).lower() in _SECRET_KEYS else redact_data(item, secrets)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_data(item, secrets) for item in value]
    return redact_text(value, secrets) if isinstance(value, str) else value
