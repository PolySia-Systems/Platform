"""Bounded in-memory telemetry buffer. Overflow drops measurements."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import TypeVar

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BufferSnapshot:
    capacity: int
    usage: int
    dropped: int


class BoundedTelemetryBuffer[T]:
    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("buffer capacity must be at least 1")
        self._capacity = capacity
        self._items: deque[T] = deque()
        self._dropped = 0
        self._lock = Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    def push(self, item: T) -> bool:
        """Return False when the item was dropped because the buffer was full."""

        with self._lock:
            if len(self._items) >= self._capacity:
                self._dropped += 1
                return False
            self._items.append(item)
            return True

    def pop_batch(self, limit: int) -> tuple[T, ...]:
        if limit < 1:
            return ()
        with self._lock:
            batch: list[T] = []
            while self._items and len(batch) < limit:
                batch.append(self._items.popleft())
            return tuple(batch)

    def snapshot(self) -> BufferSnapshot:
        with self._lock:
            return BufferSnapshot(
                capacity=self._capacity,
                usage=len(self._items),
                dropped=self._dropped,
            )

    def increment_dropped(self, count: int = 1) -> None:
        if count < 1:
            return
        with self._lock:
            self._dropped += count
