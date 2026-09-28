"""Home Assistant translated errors shared by services and runtime."""
from __future__ import annotations

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN


def invalid(key: str, message: str, **placeholders: str) -> ServiceValidationError:
    """Report an invalid service request with a localized explanation."""
    return ServiceValidationError(
        message, translation_domain=DOMAIN, translation_key=key,
        translation_placeholders=placeholders or None)


def failed(key: str, message: str, **placeholders: str) -> HomeAssistantError:
    """Report an unavailable bridge or failed command with localization."""
    return HomeAssistantError(
        message, translation_domain=DOMAIN, translation_key=key,
        translation_placeholders=placeholders or None)
