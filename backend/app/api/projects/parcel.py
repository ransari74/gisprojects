"""Cadastral parcel analytics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, require_permission

router = APIRouter(prefix="/parcel", tags=["parcel"])

Db = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[CurrentUser, Depends(require_permission("parcel:read"))]


@router.get("/summary")
async def summary(_: Read, db: Db) -> dict:
    row = (
        await db.execute(
            text(
                """
                SELECT count(*)::int                                    AS parcel_count,
                       round(sum(lot_area_m2)::numeric / 1e6, 3)::float8 AS total_area_km2,
                       round(avg(lot_area_m2)::numeric, 1)::float8      AS mean_lot_m2,
                       round(sum(assessed_value)::numeric / 1e6, 2)::float8 AS total_value_m,
                       round(avg(value_per_m2)::numeric, 2)::float8     AS mean_value_per_m2,
                       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY value_per_m2)::numeric, 2)::float8 AS median_value_per_m2,
                       round(avg(floor_area_ratio)::numeric, 3)::float8 AS mean_far,
                       sum(num_units)::int                              AS total_units,
                       count(*) FILTER (WHERE tax_exempt)::int          AS tax_exempt_count,
                       count(*) FILTER (WHERE land_use = 'vacant')::int AS vacant_count
                FROM parcel.parcels
                """
            )
        )
    ).mappings().one()
    return dict(row)


@router.get("/land-use-breakdown")
async def land_use_breakdown(_: Read, db: Db) -> list[dict]:
    """Treemap / donut source: area and value share per land use."""
    rows = (
        await db.execute(
            text(
                """
                SELECT land_use,
                       count(*)::int                                     AS parcels,
                       round(sum(lot_area_m2)::numeric / 1e4, 1)::float8 AS area_ha,
                       round(sum(assessed_value)::numeric / 1e6, 2)::float8 AS value_m,
                       round(avg(value_per_m2)::numeric, 2)::float8      AS mean_value_per_m2,
                       round(avg(floor_area_ratio)::numeric, 3)::float8  AS mean_far,
                       sum(num_units)::int                               AS units
                FROM parcel.parcels
                GROUP BY land_use
                ORDER BY area_ha DESC
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/value-distribution")
async def value_distribution(
    _: Read,
    db: Db,
    by: Annotated[str, Query(pattern="^(land_use|zone_code|owner_type|district)$")] = "land_use",
) -> list[dict]:
    """Box-plot data: value per m2 quartiles per category."""
    rows = (
        await db.execute(
            text(
                f"""
                SELECT {by}::text AS category,
                       count(*)::int AS n,
                       round(min(value_per_m2)::numeric, 1)::float8 AS min,
                       round(percentile_cont(0.25) WITHIN GROUP (ORDER BY value_per_m2)::numeric, 1)::float8 AS q1,
                       round(percentile_cont(0.50) WITHIN GROUP (ORDER BY value_per_m2)::numeric, 1)::float8 AS median,
                       round(percentile_cont(0.75) WITHIN GROUP (ORDER BY value_per_m2)::numeric, 1)::float8 AS q3,
                       round(max(value_per_m2)::numeric, 1)::float8 AS max
                FROM parcel.parcels
                WHERE value_per_m2 IS NOT NULL AND {by} IS NOT NULL
                GROUP BY {by}
                HAVING count(*) >= 3
                ORDER BY median DESC
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/price-trend")
async def price_trend(_: Read, db: Db) -> list[dict]:
    """Monthly median sale price per m2 -- the D3 time-series line."""
    rows = (
        await db.execute(
            text(
                """
                SELECT to_char(date_trunc('month', s.sale_date), 'YYYY-MM') AS month,
                       count(*)::int AS sales,
                       round(percentile_cont(0.5) WITHIN GROUP (ORDER BY s.price_per_m2)::numeric, 1)::float8 AS median_price_m2,
                       round(avg(s.price_per_m2)::numeric, 1)::float8 AS mean_price_m2,
                       round(sum(s.sale_price)::numeric / 1e6, 2)::float8 AS volume_m
                FROM parcel.sales_history s
                GROUP BY date_trunc('month', s.sale_date)
                ORDER BY 1
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/building-age-profile")
async def building_age_profile(_: Read, db: Db) -> list[dict]:
    """Stacked area chart: parcels by construction decade and land use."""
    rows = (
        await db.execute(
            text(
                """
                SELECT (year_built / 10 * 10)::int AS decade,
                       land_use,
                       count(*)::int AS parcels,
                       round(avg(floors)::numeric, 1)::float8 AS mean_floors,
                       round(avg(value_per_m2)::numeric, 1)::float8 AS mean_value_per_m2
                FROM parcel.parcels
                WHERE year_built IS NOT NULL AND year_built > 1800
                GROUP BY 1, 2
                ORDER BY 1, 2
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/zoning-compliance")
async def zoning_compliance(_: Read, db: Db) -> dict:
    """Parcels whose realised FAR exceeds the zoning cap.

    A real over-build check would need permit history; this compares the
    recorded floor area ratio against the district maximum, which is the
    screening step a planner actually runs first.
    """
    rows = (
        await db.execute(
            text(
                """
                SELECT z.zone_category,
                       count(*)::int AS parcels,
                       count(*) FILTER (WHERE p.floor_area_ratio > z.max_far)::int AS over_far,
                       round(avg(p.floor_area_ratio)::numeric, 3)::float8 AS mean_far,
                       round(avg(z.max_far)::numeric, 3)::float8 AS mean_max_far,
                       round(avg(GREATEST(z.max_far - p.floor_area_ratio, 0))::numeric, 3)::float8 AS mean_unused_far
                FROM parcel.parcels p
                JOIN parcel.zoning_districts z ON z.id = p.zoning_district_id
                WHERE p.floor_area_ratio IS NOT NULL AND z.max_far IS NOT NULL
                GROUP BY z.zone_category
                ORDER BY parcels DESC
                """
            )
        )
    ).mappings().all()
    data = [dict(r) for r in rows]
    return {
        "byCategory": data,
        "totalParcels": sum(r["parcels"] for r in data),
        "totalOverFar": sum(r["over_far"] for r in data),
    }
