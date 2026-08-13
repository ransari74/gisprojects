"""Agriculture analytics -- the numbers behind the D3 panels."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, require_permission

router = APIRouter(prefix="/agriculture", tags=["agriculture"])

Db = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[CurrentUser, Depends(require_permission("agriculture:read"))]


@router.get("/summary")
async def summary(_: Read, db: Db, crop_year: int | None = None) -> dict:
    row = (
        await db.execute(
            text(
                """
                SELECT
                    count(*)::int                                AS field_count,
                    round(sum(area_ha)::numeric, 1)::float8      AS total_area_ha,
                    round(avg(area_ha)::numeric, 2)::float8      AS mean_field_ha,
                    round(avg(yield_t_ha)::numeric, 2)::float8   AS mean_yield,
                    round(avg(soil_ph)::numeric, 2)::float8      AS mean_ph,
                    round(avg(soil_organic_c)::numeric, 1)::float8 AS mean_soc,
                    round(avg(ndvi_mean)::numeric, 3)::float8    AS mean_ndvi,
                    count(*) FILTER (WHERE irrigated)::int       AS irrigated_fields,
                    count(*) FILTER (WHERE organic)::int         AS organic_fields,
                    count(DISTINCT crop_type)::int               AS crop_types
                FROM agri.fields
                WHERE (CAST(:crop_year AS int) IS NULL OR crop_year = :crop_year)
                """
            ),
            {"crop_year": crop_year},
        )
    ).mappings().one()
    return dict(row)


@router.get("/yield-by-crop")
async def yield_by_crop(_: Read, db: Db, crop_year: int | None = None) -> list[dict]:
    """Grouped bar chart: mean yield and area per crop, with a spread band."""
    rows = (
        await db.execute(
            text(
                """
                SELECT crop_type,
                       count(*)::int                              AS fields,
                       round(sum(area_ha)::numeric, 1)::float8    AS area_ha,
                       round(avg(yield_t_ha)::numeric, 2)::float8 AS mean_yield,
                       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY yield_t_ha)::numeric, 2)::float8 AS p25,
                       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY yield_t_ha)::numeric, 2)::float8 AS median,
                       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY yield_t_ha)::numeric, 2)::float8 AS p75,
                       round(min(yield_t_ha)::numeric, 2)::float8 AS min_yield,
                       round(max(yield_t_ha)::numeric, 2)::float8 AS max_yield
                FROM agri.fields
                WHERE yield_t_ha IS NOT NULL
                  AND (CAST(:crop_year AS int) IS NULL OR crop_year = :crop_year)
                GROUP BY crop_type
                ORDER BY area_ha DESC
                """
            ),
            {"crop_year": crop_year},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/soil-yield-correlation")
async def soil_yield_correlation(
    _: Read,
    db: Db,
    x: Annotated[str, Query(pattern="^(soil_ph|soil_organic_c|soil_clay_pct|soil_sand_pct|ndvi_mean|elevation_m|slope_deg)$")] = "soil_organic_c",
    crop_type: str | None = None,
    limit: Annotated[int, Query(ge=50, le=5000)] = 1500,
) -> dict:
    """Scatter data plus correlation statistics for the soil-vs-yield panel.

    Absolute yield is not comparable across crops -- sugarbeet runs at ~80 t/ha
    and barley at ~7 -- so a raw correlation over the whole table is dominated
    by the crop mix and reads as no relationship at all. The query therefore
    also returns a *yield index*: each field's yield divided by the mean for its
    own crop. The index removes the between-crop variance and exposes the soil
    effect, which is the relationship the panel is actually about.

    Both coefficients are returned so the chart can show the naive number next
    to the controlled one. Note that soil pH is deliberately *not* the default
    x column: pH acts through an optimum near 6.5, so a linear coefficient
    reads near zero even though the effect is real -- selecting it in the UI
    is a good illustration of exactly that trap.

    The x column is constrained by the route's regex, so interpolating it is
    safe -- only the seven listed names can ever reach the query.
    """
    params: dict = {"limit": limit, "crop_type": crop_type}
    crop_filter = "AND (CAST(:crop_type AS text) IS NULL OR crop_type = :crop_type)"

    rows = (
        await db.execute(
            text(
                f"""
                WITH crop_mean AS (
                    SELECT crop_type, avg(yield_t_ha) AS mean_yield
                    FROM agri.fields
                    WHERE yield_t_ha IS NOT NULL
                    GROUP BY crop_type
                )
                SELECT f.id, f.field_code, f.crop_type, f.soil_texture,
                       f.{x}::float8         AS x,
                       f.yield_t_ha::float8  AS y,
                       round((f.yield_t_ha / NULLIF(m.mean_yield, 0))::numeric, 4)::float8 AS y_index,
                       f.area_ha::float8     AS size
                FROM agri.fields f
                JOIN crop_mean m ON m.crop_type = f.crop_type
                WHERE f.{x} IS NOT NULL AND f.yield_t_ha IS NOT NULL
                  {crop_filter.replace('crop_type =', 'f.crop_type =')}
                ORDER BY random()
                LIMIT :limit
                """
            ),
            params,
        )
    ).mappings().all()

    stats = (
        await db.execute(
            text(
                f"""
                WITH crop_mean AS (
                    SELECT crop_type, avg(yield_t_ha) AS mean_yield
                    FROM agri.fields
                    WHERE yield_t_ha IS NOT NULL
                    GROUP BY crop_type
                ),
                indexed AS (
                    SELECT f.{x}::float8 AS x,
                           f.yield_t_ha::float8 AS y,
                           (f.yield_t_ha / NULLIF(m.mean_yield, 0))::float8 AS y_index
                    FROM agri.fields f
                    JOIN crop_mean m ON m.crop_type = f.crop_type
                    WHERE f.{x} IS NOT NULL AND f.yield_t_ha IS NOT NULL
                      {crop_filter.replace('crop_type =', 'f.crop_type =')}
                )
                SELECT round(corr(x, y)::numeric, 4)::float8              AS pearson_r,
                       round(corr(x, y_index)::numeric, 4)::float8        AS pearson_r_indexed,
                       round(regr_r2(y_index, x)::numeric, 4)::float8     AS r_squared_indexed,
                       round(regr_slope(y_index, x)::numeric, 5)::float8  AS slope,
                       round(regr_intercept(y_index, x)::numeric, 5)::float8 AS intercept,
                       count(*)::int AS n
                FROM indexed
                """
            ),
            {"crop_type": crop_type},
        )
    ).mappings().one()

    return {
        "xColumn": x,
        "cropType": crop_type,
        "yUnit": "t/ha",
        "yIndexNote": "yield / mean yield for the same crop (1.0 = crop average)",
        "points": [dict(r) for r in rows],
        **dict(stats),
    }


@router.get("/ndvi-timeseries")
async def ndvi_timeseries(
    _: Read,
    db: Db,
    crop_type: str | None = None,
    field_id: int | None = None,
) -> list[dict]:
    """Multi-line chart: mean NDVI per date, split by crop (or one field)."""
    rows = (
        await db.execute(
            text(
                """
                SELECT ts.obs_date::text                       AS date,
                       f.crop_type                             AS series,
                       round(avg(ts.ndvi)::numeric, 4)::float8 AS ndvi,
                       round(percentile_cont(0.1) WITHIN GROUP (ORDER BY ts.ndvi)::numeric, 4)::float8 AS lower,
                       round(percentile_cont(0.9) WITHIN GROUP (ORDER BY ts.ndvi)::numeric, 4)::float8 AS upper,
                       count(*)::int                           AS samples
                FROM agri.field_ndvi_timeseries ts
                JOIN agri.fields f ON f.id = ts.field_id
                WHERE (CAST(:crop_type AS text) IS NULL OR f.crop_type = :crop_type)
                  AND (CAST(:field_id AS int) IS NULL OR f.id = :field_id)
                GROUP BY ts.obs_date, f.crop_type
                ORDER BY ts.obs_date, f.crop_type
                """
            ),
            {"crop_type": crop_type, "field_id": field_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/soil-texture-triangle")
async def soil_texture_triangle(_: Read, db: Db, limit: int = 800) -> list[dict]:
    """Sand/silt/clay fractions for the USDA texture-triangle scatter."""
    rows = (
        await db.execute(
            text(
                """
                SELECT id, field_code, soil_texture,
                       soil_sand_pct::float8 AS sand,
                       soil_silt_pct::float8 AS silt,
                       soil_clay_pct::float8 AS clay,
                       yield_t_ha::float8    AS yield_t_ha
                FROM agri.fields
                WHERE soil_sand_pct IS NOT NULL AND soil_clay_pct IS NOT NULL
                ORDER BY random()
                LIMIT :limit
                """
            ),
            {"limit": min(max(limit, 10), 3000)},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/irrigation-coverage")
async def irrigation_coverage(_: Read, db: Db, buffer_m: int = 250) -> dict:
    """Share of field area within `buffer_m` of a canal.

    Geography casts give a metre buffer that is correct at any latitude without
    picking a local projected SRID per study area.
    """
    row = (
        await db.execute(
            text(
                """
                WITH served AS (
                    SELECT DISTINCT f.id, f.area_ha
                    FROM agri.fields f
                    JOIN agri.irrigation_canals c
                      ON ST_DWithin(f.geom::geography, c.geom::geography, :buffer_m)
                )
                SELECT
                    (SELECT count(*) FROM agri.fields)::int                       AS total_fields,
                    (SELECT count(*) FROM served)::int                            AS served_fields,
                    round((SELECT sum(area_ha) FROM agri.fields)::numeric, 1)::float8  AS total_area_ha,
                    round((SELECT COALESCE(sum(area_ha), 0) FROM served)::numeric, 1)::float8 AS served_area_ha,
                    round((SELECT COALESCE(sum(length_m), 0) / 1000 FROM agri.irrigation_canals)::numeric, 1)::float8 AS canal_km
                """
            ),
            {"buffer_m": buffer_m},
        )
    ).mappings().one()
    data = dict(row)
    data["buffer_m"] = buffer_m
    data["served_area_pct"] = (
        round(100 * data["served_area_ha"] / data["total_area_ha"], 1)
        if data["total_area_ha"]
        else 0.0
    )
    return data
