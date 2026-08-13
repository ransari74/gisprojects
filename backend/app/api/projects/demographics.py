"""Demographic analytics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, require_permission

router = APIRouter(prefix="/demographics", tags=["demographics"])

Db = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[CurrentUser, Depends(require_permission("demographics:read"))]


@router.get("/summary")
async def summary(_: Read, db: Db) -> dict:
    row = (
        await db.execute(
            text(
                """
                SELECT count(*)::int                                 AS tract_count,
                       sum(population)::int                          AS total_population,
                       sum(households)::int                          AS total_households,
                       round(sum(area_km2)::numeric, 1)::float8      AS total_area_km2,
                       round((sum(population) / NULLIF(sum(area_km2), 0))::numeric, 1)::float8 AS overall_density,
                       round(avg(median_age)::numeric, 1)::float8    AS mean_median_age,
                       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY median_income)::numeric, 0)::float8 AS median_income,
                       round(avg(unemployment_rate)::numeric, 2)::float8 AS mean_unemployment,
                       round(avg(pct_65_plus)::numeric, 1)::float8   AS mean_pct_65_plus,
                       round(avg(pct_under_15)::numeric, 1)::float8  AS mean_pct_under_15,
                       round(avg(deprivation_index)::numeric, 1)::float8 AS mean_deprivation
                FROM demog.census_tracts
                """
            )
        )
    ).mappings().one()
    return dict(row)


@router.get("/population-pyramid")
async def population_pyramid(_: Read, db: Db, tract_id: int | None = None) -> list[dict]:
    """Classic back-to-back bar chart, whole study area or one tract."""
    rows = (
        await db.execute(
            text(
                """
                SELECT a.age_band, a.band_order,
                       sum(a.male)::int   AS male,
                       sum(a.female)::int AS female,
                       sum(a.male + a.female)::int AS total
                FROM demog.age_structure a
                WHERE (CAST(:tract_id AS int) IS NULL OR a.tract_id = :tract_id)
                GROUP BY a.age_band, a.band_order
                ORDER BY a.band_order
                """
            ),
            {"tract_id": tract_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/income-vs-education")
async def income_vs_education(
    _: Read,
    db: Db,
    x: Annotated[str, Query(pattern="^(pct_tertiary_educated|unemployment_rate|pct_owner_occupied|density_km2|pct_65_plus|median_age)$")] = "pct_tertiary_educated",
) -> dict:
    """Scatter + regression for the socio-economic correlation panel."""
    rows = (
        await db.execute(
            text(
                f"""
                SELECT id, tract_code, tract_name, district,
                       {x}::float8            AS x,
                       median_income::float8  AS y,
                       population::int        AS size,
                       deprivation_index::float8 AS deprivation
                FROM demog.census_tracts
                WHERE {x} IS NOT NULL AND median_income IS NOT NULL
                """
            )
        )
    ).mappings().all()

    stats = (
        await db.execute(
            text(
                f"""
                SELECT round(corr({x}, median_income)::numeric, 4)::float8 AS pearson_r,
                       round(regr_slope(median_income, {x})::numeric, 3)::float8 AS slope,
                       round(regr_intercept(median_income, {x})::numeric, 2)::float8 AS intercept,
                       round(regr_r2(median_income, {x})::numeric, 4)::float8 AS r_squared,
                       count(*)::int AS n
                FROM demog.census_tracts
                WHERE {x} IS NOT NULL AND median_income IS NOT NULL
                """
            )
        )
    ).mappings().one()

    return {"xColumn": x, "points": [dict(r) for r in rows], **dict(stats)}


@router.get("/density-ranking")
async def density_ranking(
    _: Read,
    db: Db,
    metric: Annotated[str, Query(pattern="^(density_km2|median_income|deprivation_index|unemployment_rate|median_rent|pct_65_plus)$")] = "density_km2",
    limit: Annotated[int, Query(ge=5, le=60)] = 20,
    ascending: bool = False,
) -> list[dict]:
    """Ranked horizontal bar chart."""
    direction = "ASC" if ascending else "DESC"
    rows = (
        await db.execute(
            text(
                f"""
                SELECT id, tract_code, tract_name, district,
                       population::int AS population,
                       {metric}::float8 AS value
                FROM demog.census_tracts
                WHERE {metric} IS NOT NULL
                ORDER BY {metric} {direction}
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/commute-matrix")
async def commute_matrix(_: Read, db: Db, top_n: Annotated[int, Query(ge=5, le=40)] = 15) -> dict:
    """Chord/matrix source: strongest OD pairs plus a modal split."""
    flows = (
        await db.execute(
            text(
                """
                SELECT origin_code, dest_code, mode,
                       trips::int AS trips,
                       round(avg_duration_min::numeric, 1)::float8 AS duration_min,
                       round(distance_km::numeric, 2)::float8 AS distance_km
                FROM demog.commute_flows
                ORDER BY trips DESC
                LIMIT :top_n
                """
            ),
            {"top_n": top_n},
        )
    ).mappings().all()

    modal = (
        await db.execute(
            text(
                """
                SELECT mode,
                       sum(trips)::int AS trips,
                       round(avg(avg_duration_min)::numeric, 1)::float8 AS mean_duration_min,
                       round(avg(distance_km)::numeric, 2)::float8 AS mean_distance_km
                FROM demog.commute_flows
                GROUP BY mode
                ORDER BY trips DESC
                """
            )
        )
    ).mappings().all()

    modal_rows = [dict(m) for m in modal]
    total = sum(m["trips"] for m in modal_rows) or 1
    for m in modal_rows:
        m["share_pct"] = round(100 * m["trips"] / total, 1)

    return {"topFlows": [dict(f) for f in flows], "modalSplit": modal_rows, "totalTrips": total}


@router.get("/age-composition")
async def age_composition(_: Read, db: Db, limit: Annotated[int, Query(ge=5, le=60)] = 25) -> list[dict]:
    """Stacked bar: age-band shares for the most populous tracts."""
    rows = (
        await db.execute(
            text(
                """
                SELECT tract_code, tract_name, population::int AS population,
                       pct_under_15::float8 AS under_15,
                       pct_15_29::float8    AS age_15_29,
                       pct_30_44::float8    AS age_30_44,
                       pct_45_64::float8    AS age_45_64,
                       pct_65_plus::float8  AS age_65_plus
                FROM demog.census_tracts
                ORDER BY population DESC
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]
