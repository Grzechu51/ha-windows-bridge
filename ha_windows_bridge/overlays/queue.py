from __future__ import annotations

from collections.abc import Iterator
from typing import Any

MAX_QUEUED_NOTIFICATIONS = 20


class NotificationQueue:
    """Stable priority queue: updates retain their place, overflow drops lowest priority."""

    def __init__(self, capacity: int = MAX_QUEUED_NOTIFICATIONS):
        self.capacity = max(1, capacity)
        self._items: list[dict[str, Any]] = []

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._items)

    def __getitem__(self, index: int) -> dict[str, Any]:
        return self._items[index]

    def __setitem__(self, index: int, value: dict[str, Any]) -> None:
        self._items[index] = value
        self.sort()

    def append(self, request: dict[str, Any]) -> None:
        for index, item in enumerate(self._items):
            if item["id"] == request["id"]:
                self._items[index] = request
                break
        else:
            self._items.append(request)
        self.sort()

    def sort(self) -> None:
        self._items.sort(key=lambda item: item.get("priority", 1), reverse=True)
        del self._items[self.capacity:]

    def popleft(self) -> dict[str, Any]:
        return self._items.pop(0)

    def remove(self, message_id: str) -> None:
        self._items[:] = [item for item in self._items if item["id"] != message_id]

    def clear(self) -> None:
        self._items.clear()
