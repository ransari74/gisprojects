"""Mapbox Vector Tile generation via PostGIS ST_AsMVT.

The query is built so the spatial index does the work: the tile envelope is
transformed into the table's storage SRID (4326) and compared with `&&` against
the untransformed geometry column. Transforming the geometry column instead
would make the GiST index unusable and force a sequential scan of the table on
every tile.
"""

from __future__ import annotations

import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.layers import LayerSpec

# Web-mercator world width in metres; a tile at zoom z spans WORLD/2**z metres.
WORLD_METRES = 40075016.686


@dataclass(frozen=True, slots=True)
class TileFilters:
    """Validated filters applied inside the tile query."""

    equals: tuple[tuple[str, str], ...] = ()
    minimums: tuple[tuple[str, float], ...] = ()
    maximums: tuple[tuple[str, float], ...] = ()

    @property
    def cache_key_part(self) -> str:
        if not (self.equals or self.minimums or self.maximums):
            return ""
        raw = repr((self.equals, self.minimums, self.maximums))
        return hashlib.sha1(raw.encode()).hexdigest()[:12]

    def is_empty(self) -> bool:
        return not (self.equals or self.minimums or self.maximums)


def parse_filters(layer: LayerSpec, params: dict[str, str]) -> TileFilters:
    """Translate `filter_x`, `min_x`, `max_x` query params into a TileFilters.

    Only columns declared filterable on the LayerSpec are honoured; anything
    else is ignored rather than erroring, so a stale frontend bookmark keeps
    working instead of returning a 400.
    """
    equals: list[tuple[str, str]] = []
    minimums: list[tuple[str, float]] = []
    maximums: list[tuple[str, float]] = []

    for key, value in params.items():
        if value is None or value == "":
            continue
        if key.startswith("filter_"):
            col = key[len("filter_"):]
            if col in layer.filterable:
                equals.append((col, value))
        elif key.startswith("min_"):
            col = key[len("min_"):]
            if col in layer.range_filterable:
                try:
                    minimums.append((col, float(value)))
                except ValueError:
                    continue
        elif key.startswith("max_"):
            col = key[len("max_"):]
            if col in layer.range_filterable:
                try:
                    maximums.append((col, float(value)))
                except ValueError:
                    continue

    return TileFilters(tuple(sorted(equals)), tuple(sorted(minimums)), tuple(sorted(maximums)))


def _build_where(layer: LayerSpec, filters: TileFilters) -> tuple[str, dict]:
    """Build the filter SQL. Column names are LayerSpec-validated identifiers;
    every value is a bound parameter."""
    clauses: list[str] = []
    params: dict = {}

    for i, (col, value) in enumerate(filters.equals):
        key = f"eq_{i}"
        # Cast both sides to text so one code path covers text, integer and
        # boolean columns without the caller having to know the column type.
        clauses.append(f"t.{col}::text = :{key}")
        params[key] = value

    for i, (col, value) in enumerate(filters.minimums):
        key = f"gte_{i}"
        clauses.append(f"t.{col} >= :{key}")
        params[key] = value

    for i, (col, value) in enumerate(filters.maximums):
        key = f"lte_{i}"
        clauses.append(f"t.{col} <= :{key}")
        params[key] = value

    return ("".join(f" AND {c}" for c in clauses), params)


def build_tile_sql(layer: LayerSpec, z: int, filters: TileFilters) -> tuple[str, dict]:
    where_sql, params = _build_where(layer, filters)

    # Generalise only when the tile is coarse enough that the detail cannot be
    # seen. Tolerance = ~1.5 screen pixels' worth of metres at this zoom.
    if layer.simplify_below_zoom and z < layer.simplify_below_zoom:
        tolerance_m = (WORLD_METRES / (2**z * settings.tile_extent)) * 1.5
        geom_expr = (
            f"ST_SimplifyPreserveTopology(ST_Transform(t.{layer.geom_column}, 3857), {tolerance_m:.4f})"
        )
    else:
        geom_expr = f"ST_Transform(t.{layer.geom_column}, 3857)"

    attr_cols = ", ".join(f"t.{c}" for c in layer.columns)

    sql = f"""
        WITH bounds AS (
            SELECT ST_TileEnvelope(:z, :x, :y) AS tile_3857,
                   ST_Transform(
                       ST_TileEnvelope(:z, :x, :y, margin => :margin),
                       4326
                   ) AS query_4326
        ),
        src AS (
            SELECT
                ST_AsMVTGeom(
                    {geom_expr},
                    bounds.tile_3857,
                    :extent,
                    :buffer,
                    true
                ) AS geom,
                t.{layer.id_column} AS feature_id,
                {attr_cols}
            FROM {layer.qualified_table} t, bounds
            WHERE t.{layer.geom_column} && bounds.query_4326
              AND ST_Intersects(t.{layer.geom_column}, bounds.query_4326)
              {where_sql}
            LIMIT :max_features
        )
        SELECT ST_AsMVT(src, :layer_name, :extent, 'geom', 'feature_id')
        FROM src
        WHERE src.geom IS NOT NULL
    """

    params.update(
        {
            "z": z,
            "x": 0,  # overwritten by caller
            "y": 0,
            "extent": settings.tile_extent,
            "buffer": settings.tile_buffer,
            "margin": settings.tile_buffer / settings.tile_extent,
            "max_features": settings.max_tile_features,
            "layer_name": layer.name,
        }
    )
    return sql, params


class TileCache:
    """Small in-process LRU.

    Deliberately not Redis: the free-tier deployment target has one API
    instance, so a process-local cache captures nearly all of the benefit for
    none of the cost. HTTP Cache-Control does the rest of the work at the CDN
    and browser layers.
    """

    def __init__(self, max_entries: int, ttl_seconds: int) -> None:
        self._store: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> bytes | None:
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

    def set(self, key: str, payload: bytes) -> None:
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


tile_cache = TileCache(settings.tile_cache_max_entries, settings.tile_cache_seconds)


def cache_key(layer_name: str, z: int, x: int, y: int, filters: TileFilters) -> str:
    suffix = filters.cache_key_part
    return f"{layer_name}/{z}/{x}/{y}" + (f"?{suffix}" if suffix else "")


async def render_tile(
    db: AsyncSession, layer: LayerSpec, z: int, x: int, y: int, filters: TileFilters
) -> bytes:
    sql, params = build_tile_sql(layer, z, filters)
    params["x"] = x
    params["y"] = y
    result = await db.execute(text(sql), params)
    row = result.scalar_one_or_none()
    return bytes(row) if row else b""
