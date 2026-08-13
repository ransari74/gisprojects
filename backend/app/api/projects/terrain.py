"""3D terrain and urban-massing analytics."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, require_permission

router = APIRouter(prefix="/terrain", tags=["terrain"])

Db = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[CurrentUser, Depends(require_permission("terrain:read"))]


@router.get("/summary")
async def summary(_: Read, db: Db) -> dict:
    buildings = (
        await db.execute(
            text(
                """
                SELECT count(*)::int                                        AS building_count,
                       round(avg(height_m)::numeric, 1)::float8             AS mean_height_m,
                       round(max(height_m)::numeric, 1)::float8             AS max_height_m,
                       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY height_m)::numeric, 1)::float8 AS median_height_m,
                       round(avg(levels)::numeric, 1)::float8               AS mean_levels,
                       round((sum(footprint_m2) / 1e4)::numeric, 1)::float8 AS footprint_ha,
                       round((sum(volume_m3) / 1e6)::numeric, 2)::float8    AS built_volume_mm3,
                       round(avg(solar_potential_kwh_m2)::numeric, 0)::float8 AS mean_solar_kwh_m2,
                       round(avg(shadow_index)::numeric, 3)::float8         AS mean_shadow_index
                FROM terrain.buildings
                """
            )
        )
    ).mappings().one()

    relief = (
        await db.execute(
            text(
                """
                SELECT round(min(elevation_m)::numeric, 1)::float8 AS min_elev_m,
                       round(max(elevation_m)::numeric, 1)::float8 AS max_elev_m,
                       count(*)::int                               AS contour_count
                FROM terrain.contours
                """
            )
        )
    ).mappings().one()

    return {**dict(buildings), **dict(relief)}


@router.get("/height-distribution")
async def height_distribution(
    _: Read, db: Db, bins: Annotated[int, Query(ge=5, le=60)] = 24
) -> dict:
    """Histogram of building heights for the massing panel."""
    row = (
        await db.execute(
            text(
                """
                WITH stats AS (
                    SELECT min(height_m)::float8 AS lo, max(height_m)::float8 AS hi
                    FROM terrain.buildings WHERE height_m IS NOT NULL
                ),
                binned AS (
                    SELECT width_bucket(b.height_m, s.lo, s.hi + 1e-9, :bins) AS bin,
                           count(*)::bigint AS count,
                           round(avg(b.levels)::numeric, 1)::float8 AS mean_levels
                    FROM terrain.buildings b, stats s
                    WHERE b.height_m IS NOT NULL
                    GROUP BY bin
                )
                SELECT jsonb_build_object(
                    'min', s.lo, 'max', s.hi,
                    'bins', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                        'x0', s.lo + (s.hi - s.lo) * (b.bin - 1) / CAST(:bins AS float8),
                        'x1', s.lo + (s.hi - s.lo) * b.bin / CAST(:bins AS float8),
                        'count', b.count,
                        'meanLevels', b.mean_levels
                    ) ORDER BY b.bin) FROM binned b), '[]'::jsonb)
                ) FROM stats s
                """
            ),
            {"bins": bins},
        )
    ).scalar_one_or_none()
    return row or {"bins": []}


@router.get("/by-type")
async def by_type(_: Read, db: Db) -> list[dict]:
    """Building stock composition -- height, volume and solar per use class."""
    rows = (
        await db.execute(
            text(
                """
                SELECT building_type,
                       count(*)::int                                      AS buildings,
                       round(avg(height_m)::numeric, 1)::float8           AS mean_height_m,
                       round(max(height_m)::numeric, 1)::float8           AS max_height_m,
                       round((sum(footprint_m2) / 1e4)::numeric, 2)::float8 AS footprint_ha,
                       round((sum(volume_m3) / 1e6)::numeric, 3)::float8  AS volume_mm3,
                       round(avg(solar_potential_kwh_m2)::numeric, 0)::float8 AS mean_solar,
                       round(avg(shadow_index)::numeric, 3)::float8       AS mean_shadow
                FROM terrain.buildings
                GROUP BY building_type
                ORDER BY buildings DESC
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/hypsometry")
async def hypsometry(_: Read, db: Db) -> list[dict]:
    """Area-vs-elevation curve: the classic hypsometric area chart."""
    rows = (
        await db.execute(
            text(
                """
                SELECT label, band_min_m::float8 AS min_m, band_max_m::float8 AS max_m,
                       color_hex,
                       round(area_km2::numeric, 3)::float8 AS area_km2
                FROM terrain.elevation_bands
                ORDER BY band_min_m
                """
            )
        )
    ).mappings().all()
    data = [dict(r) for r in rows]
    total = sum(r["area_km2"] or 0 for r in data) or 1
    cumulative = 0.0
    for r in data:
        cumulative += r["area_km2"] or 0
        r["share_pct"] = round(100 * (r["area_km2"] or 0) / total, 2)
        r["cumulative_pct"] = round(100 * cumulative / total, 2)
    return data


@router.get("/profile")
async def elevation_profile(_: Read, db: Db, transect_id: str | None = None) -> dict:
    """Terrain + skyline transect for the D3 area/line profile chart."""
    if transect_id is None:
        transect_id = (
            await db.execute(
                text("SELECT transect_id FROM terrain.elevation_profile ORDER BY transect_id LIMIT 1")
            )
        ).scalar_one_or_none()
        if transect_id is None:
            return {"transectId": None, "points": []}

    rows = (
        await db.execute(
            text(
                """
                SELECT seq::int AS seq,
                       round(distance_m::numeric, 1)::float8 AS distance_m,
                       round(elevation_m::numeric, 2)::float8 AS terrain_m,
                       round(surface_elev_m::numeric, 2)::float8 AS surface_m,
                       ST_X(geom)::float8 AS lon, ST_Y(geom)::float8 AS lat
                FROM terrain.elevation_profile
                WHERE transect_id = :tid
                ORDER BY seq
                """
            ),
            {"tid": transect_id},
        )
    ).mappings().all()

    available = [
        r[0]
        for r in (
            await db.execute(
                text("SELECT DISTINCT transect_id FROM terrain.elevation_profile ORDER BY 1")
            )
        ).all()
    ]
    return {"transectId": transect_id, "available": available, "points": [dict(r) for r in rows]}


@router.get("/solar-ranking")
async def solar_ranking(_: Read, db: Db, limit: Annotated[int, Query(ge=5, le=50)] = 20) -> list[dict]:
    """Rooftop solar candidates: largest annual yield potential."""
    rows = (
        await db.execute(
            text(
                """
                SELECT id, name, building_type,
                       round(height_m::numeric, 1)::float8 AS height_m,
                       round(footprint_m2::numeric, 0)::float8 AS footprint_m2,
                       round(solar_potential_kwh_m2::numeric, 0)::float8 AS solar_kwh_m2,
                       round((solar_potential_kwh_m2 * footprint_m2 / 1000)::numeric, 0)::float8 AS annual_mwh,
                       round(shadow_index::numeric, 3)::float8 AS shadow_index,
                       energy_class
                FROM terrain.buildings
                WHERE solar_potential_kwh_m2 IS NOT NULL AND footprint_m2 IS NOT NULL
                ORDER BY (solar_potential_kwh_m2 * footprint_m2) DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/terrain-tiles")
async def terrain_tile_config(_: Read) -> dict:
    """Terrain-RGB source config handed to MapLibre.

    The DEM itself is not re-hosted here: AWS Open Data serves Terrarium tiles
    for free with no key, which is exactly what a free-tier deployment wants.
    """
    return {
        "source": {
            "type": "raster-dem",
            "tiles": ["https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"],
            "encoding": "terrarium",
            "tileSize": 256,
            "maxzoom": 15,
            "attribution": "Elevation: Mapzen / AWS Open Data Terrain Tiles (ODbL, public domain sources)",
        },
        "defaultExaggeration": 1.5,
        "skyDefaults": {"sunIntensity": 12, "horizonBlend": 0.2},
    }


@router.get("/viewshed/{building_id}")
async def viewshed(building_id: int, _: Read, db: Db, radius_m: int = 500) -> dict:
    """What a given rooftop can see over: neighbours within `radius_m`,
    split by whether they break its skyline."""
    origin = (
        await db.execute(
            text(
                """
                SELECT id, name, height_m, ground_elev_m,
                       ST_X(ST_Centroid(geom))::float8 AS lon,
                       ST_Y(ST_Centroid(geom))::float8 AS lat
                FROM terrain.buildings WHERE id = :bid
                """
            ),
            {"bid": building_id},
        )
    ).mappings().one_or_none()
    if origin is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Building not found")

    neighbours = (
        await db.execute(
            text(
                """
                SELECT b.id, b.name, b.building_type,
                       round(b.height_m::numeric, 1)::float8 AS height_m,
                       round(ST_Distance(b.geom::geography, o.geom::geography)::numeric, 1)::float8 AS distance_m,
                       round(degrees(ST_Azimuth(ST_Centroid(o.geom), ST_Centroid(b.geom)))::numeric, 1)::float8 AS bearing_deg,
                       (b.height_m + COALESCE(b.ground_elev_m, 0))
                         > (o.height_m + COALESCE(o.ground_elev_m, 0)) AS blocks_view
                FROM terrain.buildings b, terrain.buildings o
                WHERE o.id = :bid AND b.id <> o.id
                  AND ST_DWithin(b.geom::geography, o.geom::geography, :radius)
                ORDER BY distance_m
                LIMIT 300
                """
            ),
            {"bid": building_id, "radius": radius_m},
        )
    ).mappings().all()

    rows = [dict(n) for n in neighbours]
    return {
        "origin": dict(origin),
        "radiusM": radius_m,
        "neighbours": rows,
        "blockedCount": sum(1 for n in rows if n["blocks_view"]),
        "openSkyPct": round(100 * (1 - sum(1 for n in rows if n["blocks_view"]) / len(rows)), 1)
        if rows
        else 100.0,
    }
