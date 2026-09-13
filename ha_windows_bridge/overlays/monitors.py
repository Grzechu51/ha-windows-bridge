"""Stable monitor identities shared by presentation and HA projection."""

from __future__ import annotations


def screen_id(screen) -> str:
    serial = str(getattr(screen, "serialNumber", lambda: "")()).strip()
    if serial:
        values = [
            str(getattr(screen, attribute, lambda: "")()).strip()
            for attribute in ("manufacturer", "model")
        ]
        return ":".join((*filter(None, values), serial))[:128]
    return str(screen.name()).strip()[:128]


def monitor_label(identifier: str, index: int) -> str:
    return f"{index + 1}: {identifier}"


def monitor_id_from_label(label: str) -> str:
    return str(label).partition(": ")[2] or str(label)


def selected_monitor_label(monitors, preferred_id: str, fallback_index: int) -> str:
    if not monitors:
        return ""
    selected = next(
        (item for item in monitors if monitor_id_from_label(item) == preferred_id),
        None,
    )
    if selected is not None:
        return selected
    return monitors[max(0, min(len(monitors) - 1, fallback_index))]


def resolve_screen(screens, preferred_id: str, fallback_index: int, primary=None):
    if not screens:
        return None
    selected = next(
        (screen for screen in screens if screen_id(screen) == preferred_id),
        None,
    )
    if selected is not None:
        return selected
    if preferred_id and primary in screens:
        return primary
    index = max(0, min(len(screens) - 1, fallback_index))
    return screens[index] if screens else primary
