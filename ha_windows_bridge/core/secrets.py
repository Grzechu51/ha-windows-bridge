"""Central secret boundary, independent of the encryption platform."""
from __future__ import annotations

import base64
import json
from typing import Protocol

SECRET_KEYS = frozenset({"mqtt_password", "ha_token"})


class Cipher(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...


class SecretStore:
    def __init__(self, cipher: Cipher):
        self._cipher = cipher

    def seal(self, values: dict[str, str]) -> str:
        if set(values) - SECRET_KEYS or any(not isinstance(value, str) for value in values.values()):
            raise ValueError("Invalid secret record")
        encoded = json.dumps(values, ensure_ascii=False).encode()
        if len(encoded) > 32 * 1024:
            raise ValueError("Secrets exceed size limit")
        return base64.b64encode(self._cipher.encrypt(encoded)).decode("ascii")

    def unseal(self, value: str) -> dict[str, str]:
        if not isinstance(value, str) or len(value) > 64 * 1024:
            raise ValueError("Invalid encrypted secret record")
        try:
            plaintext = self._cipher.decrypt(base64.b64decode(value, validate=True))
            if len(plaintext) > 32 * 1024:
                raise ValueError("Decrypted record exceeds size limit")
            decoded = json.loads(plaintext)
            if not isinstance(decoded, dict) or set(decoded) - SECRET_KEYS or any(not isinstance(item, str) for item in decoded.values()):
                raise ValueError()
        except Exception:
            raise ValueError("Nie można odszyfrować danych logowania dla tego użytkownika Windows.") from None
        return decoded
