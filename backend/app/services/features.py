"""Generic GeoJSON feature access + aggregation helpers shared by the five
project routers.

Every SQL fragment built here interpolates only identifiers that were validated
by LayerSpec; all user-supplied values travel as bound parameters.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.layers import LayerSpec
from app.services.mvt import TileFilters, _build_where

# Measure aliases become SQL column aliases and then JSON keys, so camelCase is
# legitimate here even though table/column identifiers are strictly snake_case.
ALIAS_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _bbox_clause(bbox: str | None, layer: LayerSpec, params: dict) -> str:
    """Adds a `&&` bbox predicate. bbox is 'minx,miny,maxx,maxy' in EPSG:4326."""
    if not bbox:
        return ""
    try:
        minx, miny, maxx, maxy = (float(v) for v in bbox.split(","))
    except (ValueError, TypeError) as exc:
        raise ValueError("bbox must be 'minx,miny,maxx,maxy' in EPSG:4326") from exc
    if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and -90 <= miny <= 90 and -90 <= maxy <= 90):
        raise ValueError("bbox coordinates are outside the valid EPSG:4326 range")
    params.update({"minx": minx, "miny": miny, "maxx": maxx, "maxy": maxy})
    return f" AND t.{layer.geom_column} && ST_MakeEnvelope(:minx, :miny, :maxx, :maxy, 4326)"


async def fetch_features(
    db: AsyncSession,
    layer: LayerSpec,
    *,
    filters: TileFilters,
    bbox: str | None = None,
    limit: int = 200,
    offset: int = 0,
    order_by: str | None = None,
    descending: bool = True,
    include_geometry: bool = True,
    simplify_m: float | None = None,
) -> dict[str, Any]:
    """Returns a GeoJSON FeatureCollection (or an attribute-only collection)."""
    where_sql, params = _build_where(layer, filters)
    where_sql += _bbox_clause(bbox, layer, params)

    order_sql = f"t.{layer.id_column}"
    if order_by and order_by in layer.columns:
        order_sql = f"t.{order_by} {'DESC' if descending else 'ASC'} NULLS LAST"

    attr_cols = ", ".join(f"t.{c}" for c in layer.columns)

    if include_geometry:
        geom_src = f"t.{layer.geom_column}"
        if simplify_m:
            # Simplify in web-mercator metres, then return to 4326 for GeoJSON.
            geom_src = (
                f"ST_Transform(ST_SimplifyPreserveTopology("
                f"ST_Transform(t.{layer.geom_column}, 3857), :simplify_m), 4326)"
            )
            params["simplify_m"] = simplify_m
        geom_expr = f"ST_AsGeoJSON({geom_src})::jsonb"
    else:
        geom_expr = "NULL::jsonb"

    sql = f"""
        WITH page AS (
            SELECT t.{layer.id_column} AS __id, {attr_cols}, {geom_expr} AS __geom
            FROM {layer.qualified_table} t
            WHERE TRUE {where_sql}
            ORDER BY {order_sql}
            LIMIT :limit OFFSET :offset
        )
        SELECT
            jsonb_build_object(
                'type', 'FeatureCollection',
                'features', COALESCE(jsonb_agg(
                    jsonb_build_object(
                        'type', 'Feature',
                        'id', page.__id,
                        'geometry', page.__geom,
                        'properties', to_jsonb(page) - '__geom' - '__id'
                    )
                ), '[]'::jsonb)
            )
        FROM page
    """
    params.update({"limit": limit, "offset": offset})
    collection = (await db.execute(text(sql), params)).scalar_one()

    count_sql = f"""
        SELECT count(*) FROM {layer.qualified_table} t WHERE TRUE {where_sql}
    """
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset", "simplify_m")}
    total = (await db.execute(text(count_sql), count_params)).scalar_one()

    collection["totalCount"] = total
    collection["limit"] = limit
    collection["offset"] = offset
    collection["layer"] = layer.name
    return collection


async def fetch_feature_by_id(
    db: AsyncSession, layer: LayerSpec, feature_id: int
) -> dict[str, Any] | None:
    attr_cols = ", ".join(f"t.{c}" for c in layer.columns)
    sql = f"""
        WITH one AS (
            SELECT t.{layer.id_column} AS __id, {attr_cols},
                   ST_AsGeoJSON(t.{layer.geom_column})::jsonb AS __geom
            FROM {layer.qualified_table} t
            WHERE t.{layer.id_column} = :fid
        )
        SELECT jsonb_build_object(
            'type', 'Feature',
            'id', one.__id,
            'geometry', one.__geom,
            'properties', to_jsonb(one) - '__geom' - '__id'
        )
        FROM one
    """
    return (await db.execute(text(sql), {"fid": feature_id})).scalar_one_or_none()


async def categorical_breakdown(
    db: AsyncSession,
    layer: LayerSpec,
    group_column: str,
    *,
    measures: dict[str, str] | None = None,
    filters: TileFilters | None = None,
    limit: int = 30,
) -> list[dict]:
    """GROUP BY a categorical column, returning count plus optional aggregates.

    `measures` maps an output key to `"<agg>:<column>"`, e.g.
    {"avgYield": "avg:yield_t_ha", "totalArea": "sum:area_ha"}.
    """
    if group_column not in layer.columns:
        raise ValueError(f"{group_column!r} is not a column of layer {layer.name!r}")

    select_parts = [f"t.{group_column}::text AS category", "count(*)::bigint AS count"]
    for out_key, spec in (measures or {}).items():
        agg, _, col = spec.partition(":")
        if agg not in {"avg", "sum", "min", "max"} or col not in layer.columns:
            raise ValueError(f"Invalid measure {spec!r} for layer {layer.name!r}")
        if not ALIAS_RE.match(out_key):
            raise ValueError(f"Invalid measure alias {out_key!r}")
        # Quote the alias so PostgreSQL preserves camelCase instead of folding
        # it to lowercase -- the alias is the JSON key the chart reads.
        # ALIAS_RE has already rejected anything containing a quote.
        select_parts.append(f'round({agg}(t.{col})::numeric, 3)::float8 AS "{out_key}"')

    where_sql, params = _build_where(layer, filters or TileFilters())
    sql = f"""
        SELECT {', '.join(select_parts)}
        FROM {layer.qualified_table} t
        WHERE t.{group_column} IS NOT NULL {where_sql}
        GROUP BY t.{group_column}
        ORDER BY count DESC
        LIMIT :limit
    """
    params["limit"] = limit
    rows = (await db.execute(text(sql), params)).mappings().all()
    return [dict(r) for r in rows]


async def histogram(
    db: AsyncSession,
    layer: LayerSpec,
    column: str,
    *,
    bins: int = 20,
    filters: TileFilters | None = None,
) -> dict[str, Any]:
    """Equal-width histogram, ready for a D3 bar chart."""
    if column not in layer.columns:
        raise ValueError(f"{column!r} is not a column of layer {layer.name!r}")
    bins = max(2, min(bins, 100))

    where_sql, params = _build_where(layer, filters or TileFilters())
    params["bins"] = bins

    sql = f"""
        WITH stats AS (
            SELECT min(t.{column})::float8 AS lo, max(t.{column})::float8 AS hi,
                   count(*)::bigint AS n,
                   avg(t.{column})::float8 AS mean,
                   stddev_pop(t.{column})::float8 AS stddev,
                   percentile_cont(0.5) WITHIN GROUP (ORDER BY t.{column})::float8 AS median
            FROM {layer.qualified_table} t
            WHERE t.{column} IS NOT NULL {where_sql}
        ),
        binned AS (
            SELECT width_bucket(t.{column}::float8, stats.lo, stats.hi + 1e-9, :bins) AS bin,
                   count(*)::bigint AS count
            FROM {layer.qualified_table} t, stats
            WHERE t.{column} IS NOT NULL {where_sql}
            GROUP BY bin
        )
        SELECT jsonb_build_object(
            'column', '{column}',
            'min', stats.lo,
            'max', stats.hi,
            'count', stats.n,
            'mean', round(stats.mean::numeric, 3)::float8,
            'median', round(stats.median::numeric, 3)::float8,
            'stddev', round(stats.stddev::numeric, 3)::float8,
            'bins', COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'bin', binned.bin,
                    'x0', stats.lo + (stats.hi - stats.lo) * (binned.bin - 1) / CAST(:bins AS float8),
                    'x1', stats.lo + (stats.hi - stats.lo) * binned.bin / CAST(:bins AS float8),
                    'count', binned.count
                ) ORDER BY binned.bin)
                FROM binned WHERE binned.bin IS NOT NULL
            ), '[]'::jsonb)
        )
        FROM stats
    """
    result = (await db.execute(text(sql), params)).scalar_one_or_none()
    return result or {"column": column, "bins": [], "count": 0}


async def numeric_summary(
    db: AsyncSession, layer: LayerSpec, columns: list[str], filters: TileFilters | None = None
) -> dict[str, Any]:
    """min/max/avg/median for several columns in one round-trip."""
    valid = [c for c in columns if c in layer.columns]
    if not valid:
        return {}
    where_sql, params = _build_where(layer, filters or TileFilters())

    parts = []
    for col in valid:
        parts.append(
            f"""'{col}', jsonb_build_object(
                'min', min(t.{col})::float8,
                'max', max(t.{col})::float8,
                'mean', round(avg(t.{col})::numeric, 3)::float8,
                'median', round(percentile_cont(0.5) WITHIN GROUP (ORDER BY t.{col})::numeric, 3)::float8,
                'nonNull', count(t.{col})::bigint
            )"""
        )
    sql = f"SELECT jsonb_build_object({', '.join(parts)}) FROM {layer.qualified_table} t WHERE TRUE {where_sql}"
    return (await db.execute(text(sql), params)).scalar_one() or {}
