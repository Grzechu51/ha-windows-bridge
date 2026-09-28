"""Actionable Home Assistant Repairs for incomplete identity consolidation."""
from __future__ import annotations

from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def _issue_id(entry, kind: str) -> str:
    return f"{kind}_{entry.entry_id}"


def migration_conflict(hass, entry) -> None:
    ir.async_create_issue(
        hass, DOMAIN, _issue_id(entry, "migration_conflict"),
        is_fixable=False, is_persistent=True, severity=ir.IssueSeverity.ERROR,
        translation_key="migration_conflict",
        translation_placeholders={"name": entry.title},
    )


def migration_cleanup_pending(hass, entry) -> None:
    ir.async_create_issue(
        hass, DOMAIN, _issue_id(entry, "migration_cleanup_pending"),
        is_fixable=False, is_persistent=True, severity=ir.IssueSeverity.WARNING,
        translation_key="migration_cleanup_pending",
        translation_placeholders={"name": entry.title},
    )


def clear_migration_issues(hass, entry) -> None:
    for kind in ("migration_conflict", "migration_cleanup_pending"):
        ir.async_delete_issue(hass, DOMAIN, _issue_id(entry, kind))


def clear_migration_conflict(hass, entry) -> None:
    ir.async_delete_issue(hass, DOMAIN, _issue_id(entry, "migration_conflict"))
