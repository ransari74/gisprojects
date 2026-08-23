"""Remote-sensing and change-detection analytics.

Six analyses, each one a workflow that shows up repeatedly in the earth
observation literature:

  * acquisition inventory      -- what usable imagery exists, and when
  * spectral index phenology   -- NDVI/NDWI/NDBI curves through the year
  * land-cover change matrix   -- the from/to transition table
  * urban heat island          -- LST against NDVI and imperviousness
  * InSAR subsidence           -- ground velocity by soil type
  * index distribution         -- the histogram behind the map's colour ramp
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, require_permission

router = APIRouter(prefix="/remote-sensing", tags=["remote-sensing"])

Db = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[CurrentUser, Depends(require_permission("remote_sensing:read"))]

#: Columns the index endpoints will interpolate. Same rule as the layer
#: registry: the value is checked against this set, never taken from the
#: request, because it is spliced into SQL by name.
INDEX_COLUMNS = {"ndvi", "ndwi", "ndbi", "nbr", "lst_c", "lst_anomaly_c", "albedo"}


def _index_column(name: str) -> str:
    if name not in INDEX_COLUMNS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unknown index {name!r}; expected one of {sorted(INDEX_COLUMNS)}",
        )
    return name


@router.get("/summary")
async def summary(_: Read, db: Db) -> dict:
    scenes = (
        await db.execute(
            text(
                """
                SELECT count(*)::int                                       AS scene_count,
                       count(*) FILTER (WHERE usable)::int                 AS usable_scenes,
                       count(DISTINCT platform)::int                       AS platform_count,
                       round(avg(cloud_pct)::numeric, 1)::float8           AS mean_cloud_pct,
                       min(acquired_at)                                    AS first_acquired,
                       max(acquired_at)                                    AS last_acquired
                FROM rs.scenes
                """
            )
        )
    ).mappings().one()

    grid = (
        await db.execute(
            text(
                """
                SELECT count(*)::int                                       AS cell_count,
                       round(avg(ndvi)::numeric, 3)::float8                AS mean_ndvi,
                       round(avg(lst_c)::numeric, 1)::float8               AS mean_lst_c,
                       round(max(lst_c)::numeric, 1)::float8               AS max_lst_c,
                       round(avg(imperviousness_pct)::numeric, 1)::float8  AS mean_impervious_pct,
                       count(*) FILTER (WHERE changed)::int                AS changed_cells,
                       round(sum(area_ha) FILTER (WHERE changed)::numeric, 0)::float8 AS changed_area_ha,
                       round(sum(area_ha)::numeric, 0)::float8             AS total_area_ha
                FROM rs.index_cells
                """
            )
        )
    ).mappings().one()

    # The heat-island signal itself: built-up cells against everything else.
    # Reported as one number because that difference is the finding, not the
    # two absolute temperatures it is derived from.
    uhi = (
        await db.execute(
            text(
                """
                SELECT round((
                    avg(lst_c) FILTER (WHERE landcover_class = 'built_up')
                    - avg(lst_c) FILTER (WHERE landcover_class <> 'built_up')
                )::numeric, 2)::float8 AS uhi_delta_c
                FROM rs.index_cells
                """
            )
        )
    ).mappings().one()

    subsidence = (
        await db.execute(
            text(
                """
                SELECT count(*)::int                                        AS ps_count,
                       round(avg(velocity_mm_yr)::numeric, 2)::float8       AS mean_velocity_mm_yr,
                       round(min(velocity_mm_yr)::numeric, 2)::float8       AS fastest_subsidence_mm_yr,
                       count(*) FILTER (WHERE velocity_mm_yr <= -5)::int    AS points_over_5mm,
                       round(avg(coherence)::numeric, 2)::float8            AS mean_coherence
                FROM rs.subsidence_points
                """
            )
        )
    ).mappings().one()

    # Per-date first, then aggregate across dates. Summing the raw rows would
    # count the same permanent lake once per acquisition -- eight passes over
    # the same water reads as eight times the water.
    water = (
        await db.execute(
            text(
                """
                WITH per_date AS (
                    SELECT observed_on,
                           sum(area_ha) FILTER (WHERE water_type = 'permanent') AS permanent_ha,
                           sum(area_ha) FILTER (WHERE water_type = 'flood')     AS flood_ha
                    FROM rs.water_extent
                    GROUP BY observed_on
                )
                SELECT round(avg(permanent_ha)::numeric, 0)::float8       AS permanent_water_ha,
                       -- The peak, not the total: what matters about a flood
                       -- is its largest extent, not the sum of every pass.
                       round(max(COALESCE(flood_ha, 0))::numeric, 0)::float8 AS peak_flood_ha,
                       count(*)::int                                      AS water_observations
                FROM per_date
                """
            )
        )
    ).mappings().one()

    return {**dict(scenes), **dict(grid), **dict(uhi), **dict(subsidence), **dict(water)}


@router.get("/scene-inventory")
async def scene_inventory(_: Read, db: Db) -> dict:
    """Acquisitions per month per platform, plus the cloud-cover distribution.

    The first question of any optical study is how much usable imagery the
    period actually yields; over the Netherlands that answer is dominated by
    cloud, which is the argument for the SAR layers alongside.
    """
    by_month = (
        await db.execute(
            text(
                """
                SELECT to_char(date_trunc('month', acquired_at), 'YYYY-MM') AS month,
                       platform,
                       count(*)::int                                        AS scenes,
                       count(*) FILTER (WHERE usable)::int                  AS usable,
                       round(avg(cloud_pct)::numeric, 1)::float8            AS mean_cloud_pct
                FROM rs.scenes
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            )
        )
    ).mappings().all()

    by_platform = (
        await db.execute(
            text(
                """
                SELECT platform,
                       sensor,
                       count(*)::int                                       AS scenes,
                       count(*) FILTER (WHERE usable)::int                 AS usable,
                       round(avg(cloud_pct)::numeric, 1)::float8           AS mean_cloud_pct,
                       round(avg(resolution_m)::numeric, 1)::float8        AS resolution_m
                FROM rs.scenes
                GROUP BY 1, 2
                ORDER BY scenes DESC
                """
            )
        )
    ).mappings().all()

    return {"byMonth": [dict(r) for r in by_month], "byPlatform": [dict(r) for r in by_platform]}


@router.get("/index-timeseries")
async def index_timeseries(
    _: Read,
    db: Db,
    index: Annotated[str, Query(pattern="^(ndvi|ndwi|ndbi|nbr)$")] = "ndvi",
) -> list[dict]:
    """Seasonal curve for one index, one series per land-cover class."""
    rows = (
        await db.execute(
            text(
                """
                SELECT observed_on::text     AS date,
                       landcover_class       AS series,
                       value,
                       p10                   AS lower,
                       p90                   AS upper,
                       sample_n,
                       cloud_pct
                FROM rs.index_timeseries
                WHERE index_name = :index
                ORDER BY landcover_class, observed_on
                """
            ),
            {"index": index},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/change-matrix")
async def change_matrix(_: Read, db: Db) -> dict:
    """The from/to transition table, the standard output of a change study.

    Read off the grid rather than the change polygons: every cell has a
    classification in both epochs, so the matrix balances. The polygon layer
    reports the dissolved regions, which is a different question.
    """
    transitions = (
        await db.execute(
            text(
                """
                SELECT landcover_prev                                  AS from_class,
                       landcover_class                                 AS to_class,
                       count(*)::int                                   AS cells,
                       round(sum(area_ha)::numeric, 1)::float8         AS area_ha,
                       round(avg(ndvi_delta)::numeric, 3)::float8      AS mean_ndvi_delta
                FROM rs.index_cells
                GROUP BY 1, 2
                ORDER BY area_ha DESC
                """
            )
        )
    ).mappings().all()

    # Gains and losses per class, which is what the matrix is usually read for.
    net = (
        await db.execute(
            text(
                """
                WITH gained AS (
                    SELECT landcover_class AS cls, sum(area_ha) AS area
                    FROM rs.index_cells WHERE changed GROUP BY 1
                ),
                lost AS (
                    SELECT landcover_prev AS cls, sum(area_ha) AS area
                    FROM rs.index_cells WHERE changed GROUP BY 1
                )
                SELECT COALESCE(g.cls, l.cls)                                   AS landcover_class,
                       round(COALESCE(g.area, 0)::numeric, 1)::float8           AS gained_ha,
                       round(COALESCE(l.area, 0)::numeric, 1)::float8           AS lost_ha,
                       round((COALESCE(g.area, 0) - COALESCE(l.area, 0))::numeric, 1)::float8
                                                                               AS net_ha
                FROM gained g FULL OUTER JOIN lost l ON l.cls = g.cls
                ORDER BY net_ha DESC
                """
            )
        )
    ).mappings().all()

    by_type = (
        await db.execute(
            text(
                """
                SELECT change_type,
                       count(*)::int                              AS polygons,
                       round(sum(area_ha)::numeric, 1)::float8    AS area_ha,
                       round(avg(confidence)::numeric, 2)::float8 AS mean_confidence,
                       round(avg(ndvi_delta)::numeric, 3)::float8 AS mean_ndvi_delta
                FROM rs.change_polygons
                GROUP BY 1
                ORDER BY area_ha DESC
                """
            )
        )
    ).mappings().all()

    return {
        "transitions": [dict(r) for r in transitions],
        "net": [dict(r) for r in net],
        "byType": [dict(r) for r in by_type],
    }


@router.get("/heat-island")
async def heat_island(
    _: Read,
    db: Db,
    x: Annotated[str, Query(pattern="^(ndvi|ndbi|imperviousness_pct|tree_cover_pct|albedo)$")] = "ndvi",
    limit: Annotated[int, Query(ge=100, le=4000)] = 1500,
) -> dict:
    """Land surface temperature against a surface-cover driver.

    The NDVI/NDBI-versus-LST regression is the workhorse of urban heat island
    studies: vegetation cools through evapotranspiration, impervious cover
    stores heat, and the slope puts a number on both.
    """
    points = (
        await db.execute(
            text(
                f"""
                SELECT id,
                       {x}::float8              AS x,
                       lst_c::float8            AS y,
                       lst_anomaly_c::float8    AS anomaly,
                       landcover_class          AS group_name,
                       cell_code                AS label
                FROM rs.index_cells
                WHERE {x} IS NOT NULL AND lst_c IS NOT NULL
                ORDER BY random()
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()

    fit = (
        await db.execute(
            text(
                f"""
                SELECT round(corr(lst_c, {x})::numeric, 3)::float8       AS pearson_r,
                       round(regr_r2(lst_c, {x})::numeric, 3)::float8    AS r_squared,
                       round(regr_slope(lst_c, {x})::numeric, 3)::float8 AS slope,
                       round(regr_intercept(lst_c, {x})::numeric, 3)::float8 AS intercept,
                       count(*)::int                                     AS n
                FROM rs.index_cells
                WHERE {x} IS NOT NULL AND lst_c IS NOT NULL
                """
            )
        )
    ).mappings().one()

    by_class = (
        await db.execute(
            text(
                """
                SELECT landcover_class,
                       count(*)::int                                  AS cells,
                       round(avg(lst_c)::numeric, 2)::float8          AS mean_lst_c,
                       round(avg(lst_anomaly_c)::numeric, 2)::float8  AS mean_anomaly_c,
                       round(avg(ndvi)::numeric, 3)::float8           AS mean_ndvi,
                       round(avg(imperviousness_pct)::numeric, 1)::float8 AS mean_impervious_pct
                FROM rs.index_cells
                GROUP BY 1
                ORDER BY mean_lst_c DESC
                """
            )
        )
    ).mappings().all()

    return {
        "xColumn": x,
        "points": [dict(r) for r in points],
        **dict(fit),
        "byClass": [dict(r) for r in by_class],
    }


@router.get("/subsidence")
async def subsidence(_: Read, db: Db) -> dict:
    """Ground velocity grouped by soil type and by risk band.

    Peat is the story: it oxidises and compacts once drained, so a peat polder
    subsides an order of magnitude faster than the sand ridge beside it, and
    the soil-type breakdown is where that shows up.
    """
    by_soil = (
        await db.execute(
            text(
                """
                SELECT soil_type,
                       count(*)::int                                     AS points,
                       round(avg(velocity_mm_yr)::numeric, 2)::float8    AS mean_velocity_mm_yr,
                       round(min(velocity_mm_yr)::numeric, 2)::float8    AS fastest_mm_yr,
                       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY velocity_mm_yr)::numeric, 2)::float8
                                                                         AS median_mm_yr,
                       round(avg(cumulative_mm)::numeric, 1)::float8     AS mean_cumulative_mm,
                       round(avg(coherence)::numeric, 2)::float8         AS mean_coherence
                FROM rs.subsidence_points
                GROUP BY 1
                ORDER BY mean_velocity_mm_yr
                """
            )
        )
    ).mappings().all()

    by_risk = (
        await db.execute(
            text(
                """
                SELECT risk_class,
                       count(*)::int                                  AS points,
                       round(avg(velocity_mm_yr)::numeric, 2)::float8 AS mean_velocity_mm_yr
                FROM rs.subsidence_points
                GROUP BY 1
                ORDER BY mean_velocity_mm_yr
                """
            )
        )
    ).mappings().all()

    by_land_use = (
        await db.execute(
            text(
                """
                SELECT land_use,
                       count(*)::int                                  AS points,
                       round(avg(velocity_mm_yr)::numeric, 2)::float8 AS mean_velocity_mm_yr,
                       round(avg(cumulative_mm)::numeric, 1)::float8  AS mean_cumulative_mm
                FROM rs.subsidence_points
                WHERE land_use IS NOT NULL
                GROUP BY 1
                ORDER BY mean_velocity_mm_yr
                """
            )
        )
    ).mappings().all()

    # Ordered by differential rather than by mean rate: uniform settlement is
    # tolerable, and it is the spread along a structure that damages it, so
    # that is the column an asset owner triages on.
    profiles = (
        await db.execute(
            text(
                """
                SELECT profile_code, name, asset_type, risk_class, dominant_soil,
                       round((length_m / 1000)::numeric, 1)::float8       AS length_km,
                       round(mean_velocity_mm_yr::numeric, 2)::float8     AS mean_velocity_mm_yr,
                       round(min_velocity_mm_yr::numeric, 2)::float8      AS min_velocity_mm_yr,
                       round(differential_mm_yr::numeric, 2)::float8      AS differential_mm_yr,
                       ps_count
                FROM rs.deformation_profiles
                ORDER BY differential_mm_yr DESC
                """
            )
        )
    ).mappings().all()

    return {
        "bySoil": [dict(r) for r in by_soil],
        "byRisk": [dict(r) for r in by_risk],
        "byLandUse": [dict(r) for r in by_land_use],
        "profiles": [dict(r) for r in profiles],
    }


@router.get("/index-distribution")
async def index_distribution(
    _: Read,
    db: Db,
    index: Annotated[str, Query()] = "ndvi",
    bins: Annotated[int, Query(ge=5, le=60)] = 24,
) -> dict:
    """Histogram of one index across the grid -- the distribution the map's
    colour ramp is stretched over."""
    column = _index_column(index)
    row = (
        await db.execute(
            text(
                f"""
                WITH stats AS (
                    SELECT min({column})::float8 AS lo, max({column})::float8 AS hi
                    FROM rs.index_cells WHERE {column} IS NOT NULL
                ),
                binned AS (
                    SELECT width_bucket(c.{column}, s.lo, s.hi + 1e-9, :bins) AS bin,
                           count(*)::bigint AS count,
                           round(avg(c.lst_c)::numeric, 2)::float8 AS mean_lst_c
                    FROM rs.index_cells c, stats s
                    WHERE c.{column} IS NOT NULL
                    GROUP BY bin
                )
                SELECT jsonb_build_object(
                    'min', s.lo, 'max', s.hi,
                    'bins', COALESCE((SELECT jsonb_agg(jsonb_build_object(
                        'x0', s.lo + (s.hi - s.lo) * (b.bin - 1) / CAST(:bins AS float8),
                        'x1', s.lo + (s.hi - s.lo) * b.bin / CAST(:bins AS float8),
                        'count', b.count,
                        'meanLstC', b.mean_lst_c
                    ) ORDER BY b.bin) FROM binned b), '[]'::jsonb)
                ) FROM stats s
                """
            ),
            {"bins": bins},
        )
    ).scalar_one_or_none()
    # `column` is echoed back from Python rather than bound into the SQL:
    # Postgres cannot infer a type for a bare text parameter inside
    # jsonb_build_object, and it is already a validated value here anyway.
    return {"column": column, **(row or {"bins": []})}


@router.get("/water-extent")
async def water_extent(_: Read, db: Db) -> list[dict]:
    """Delineated water area per acquisition, split by type.

    The seasonal and flood classes rising above the permanent baseline is the
    inundation signal; the permanent class is there as the reference level.
    """
    rows = (
        await db.execute(
            text(
                """
                SELECT observed_on::text                            AS date,
                       water_type,
                       source,
                       round(sum(area_ha)::numeric, 1)::float8       AS area_ha,
                       round(avg(confidence)::numeric, 2)::float8    AS mean_confidence,
                       round(avg(backscatter_db)::numeric, 1)::float8 AS mean_backscatter_db
                FROM rs.water_extent
                GROUP BY 1, 2, 3
                ORDER BY 1, 2
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]
