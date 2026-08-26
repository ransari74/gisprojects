"""In-process TTL cache for expensive, deterministic analytics results.

Same reasoning as `TileCache` in mvt.py, for a different shape of payload: the
free-tier deployment target runs one API instance, so a process-local cache
captures nearly all of the benefit of Redis for none of the operational cost.

What belongs here is a result that is *derived entirely from loaded data* and
therefore cannot change between ETL runs. The few-shot crop classification is
the motivating case: it scores every parcel against every class centroid at ten
different label budgets, which is about 112,000 dot products and roughly five
seconds of Postgres. The answer is identical on every request until the data is
reloaded, so computing it once is not an optimisation so much as declining to
do the same arithmetic repeatedly.

What does not belong here is anything parameterised by the request in a way
that makes the key space large, or anything a user could change and expect to
see reflected.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any


class AnalysisCache:
    def __init__(self, max_entries: int = 64, ttl_seconds: int = 3600) -> None:
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            self.misses += 1
            return None
        stored_at, payload = entry
        if time.monotonic() - stored_at > self._ttl:
            del self._store[key]
            self.misses += 1
            return None
        self._store.move_to_end(key)
        self.hits += 1
        return payload

    def set(self, key: str, payload: Any) -> None:
        self._store[key] = (time.monotonic(), payload)
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def clear(self) -> None:
        self._store.clear()

    def stats(self) -> dict:
        total = self.hits + self.misses
        return {
            "entries": len(self._store),
            "max_entries": self._max,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": round(self.hits / total, 3) if total else 0.0,
        }


analysis_cache = AnalysisCache()
