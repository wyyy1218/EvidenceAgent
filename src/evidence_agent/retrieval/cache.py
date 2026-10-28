"""Retrieval cache keyed by project version_set_hash + query."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CacheEntry:
    key: str
    payload: dict[str, Any]
    created_at: float
    hit_count: int = 0


@dataclass
class RetrievalCache:
    ttl_seconds: float = 3600.0
    max_entries: int = 256
    _store: dict[str, CacheEntry] = field(default_factory=dict)
    cold_hits: int = 0
    hot_hits: int = 0

    @staticmethod
    def make_key(version_set_hash: str, query: str, config_hash: str = "") -> str:
        raw = f"{version_set_hash}|{config_hash}|{query.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, key: str) -> dict[str, Any] | None:
        ent = self._store.get(key)
        if ent is None:
            self.cold_hits += 1
            return None
        if time.time() - ent.created_at > self.ttl_seconds:
            del self._store[key]
            self.cold_hits += 1
            return None
        ent.hit_count += 1
        self.hot_hits += 1
        return json.loads(json.dumps(ent.payload))  # deep copy

    def put(self, key: str, payload: dict[str, Any]) -> None:
        if len(self._store) >= self.max_entries:
            # drop oldest
            oldest = min(self._store.values(), key=lambda e: e.created_at)
            self._store.pop(oldest.key, None)
        self._store[key] = CacheEntry(key=key, payload=payload, created_at=time.time())

    def stats(self) -> dict[str, int]:
        return {"cold_hits": self.cold_hits, "hot_hits": self.hot_hits, "size": len(self._store)}
