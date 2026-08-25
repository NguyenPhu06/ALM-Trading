from __future__ import annotations

from dataclasses import dataclass
from time import monotonic
from typing import Any

@dataclass(slots=True)
class _Entry:
    value: Any
    expires_at: float

class MarketDataCache:
    def __init__(self, ttl_seconds: float = 5.):
        if ttl_seconds <= 0: raise ValueError("cache TTL must be positive")
        self.ttl_seconds = ttl_seconds; self._items: dict[str, _Entry] = {}
    def get(self, key: str):
        item = self._items.get(key)
        if not item or item.expires_at <= monotonic(): self._items.pop(key, None); return None
        return item.value
    def set(self, key: str, value: Any, ttl_seconds: float | None = None):
        self._items[key] = _Entry(value, monotonic() + (ttl_seconds or self.ttl_seconds))
    def clear(self): self._items.clear()

