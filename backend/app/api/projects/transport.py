"""Transport network analytics."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, require_permission

router = APIRouter(prefix="/transport", tags=["transport"])

Db = Annotated[AsyncSession, Depends(get_db)]
Read = Annotated[CurrentUser, Depends(require_permission("transport:read"))]


@router.get("/summary")
async def summary(_: Read, db: Db) -> dict:
    roads = (
        await db.execute(
            text(
                """
                SELECT count(*)::int                                       AS segment_count,
                       round((sum(length_m) / 1000)::numeric, 1)::float8    AS network_km,
                       round(avg(congestion_index)::numeric, 3)::float8     AS mean_congestion,
                       round(avg(maxspeed_kmh)::numeric, 1)::float8         AS mean_speed_limit,
                       sum(aadt)::bigint                                    AS total_aadt,
                       sum(accident_count)::int                             AS total_accidents,
                       round((sum(length_m) FILTER (WHERE has_bike_lane) / NULLIF(sum(length_m), 0) * 100)::numeric, 1)::float8 AS bike_lane_pct
                FROM transport.road_segments
                """
            )
        )
    ).mappings().one()

    transit = (
        await db.execute(
            text(
                """
                SELECT (SELECT count(*) FROM transport.transit_routes)::int AS route_count,
                       (SELECT count(*) FROM transport.transit_stops)::int  AS stop_count,
                       (SELECT sum(daily_ridership) FROM transport.transit_routes)::int AS daily_ridership,
                       (SELECT round(avg(headway_min)::numeric, 1)::float8 FROM transport.transit_routes) AS mean_headway_min,
                       (SELECT round((count(*) FILTER (WHERE wheelchair_accessible)::numeric
                                      / NULLIF(count(*), 0) * 100), 1)::float8
                        FROM transport.transit_stops) AS accessible_stop_pct
                """
            )
        )
    ).mappings().one()

    return {**dict(roads), **dict(transit)}


@router.get("/network-by-class")
async def network_by_class(_: Read, db: Db) -> list[dict]:
    """Bar chart: length, traffic and congestion per road class."""
    rows = (
        await db.execute(
            text(
                """
                SELECT highway_class,
                       count(*)::int                                    AS segments,
                       round((sum(length_m) / 1000)::numeric, 2)::float8 AS length_km,
                       round(avg(aadt)::numeric, 0)::float8             AS mean_aadt,
                       round(avg(congestion_index)::numeric, 3)::float8 AS mean_congestion,
                       round(avg(maxspeed_kmh)::numeric, 1)::float8     AS mean_speed_limit,
                       sum(accident_count)::int                         AS accidents,
                       round((sum(accident_count) / NULLIF(sum(length_m) / 1000, 0))::numeric, 2)::float8 AS accidents_per_km
                FROM transport.road_segments
                GROUP BY highway_class
                ORDER BY length_km DESC
                """
            )
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/hourly-profile")
async def hourly_profile(_: Read, db: Db, highway_class: str | None = None) -> list[dict]:
    """24-hour traffic curve -- the D3 area chart with an AM/PM peak."""
    rows = (
        await db.execute(
            text(
                """
                SELECT tc.hour::int AS hour,
                       sum(tc.vehicles)::int AS vehicles,
                       round(avg(tc.vehicles)::numeric, 1)::float8 AS mean_vehicles,
                       round(avg(tc.avg_speed_kmh)::numeric, 1)::float8 AS mean_speed,
                       count(DISTINCT tc.segment_id)::int AS segments
                FROM transport.traffic_counts tc
                JOIN transport.road_segments r ON r.id = tc.segment_id
                WHERE (CAST(:highway_class AS text) IS NULL OR r.highway_class = :highway_class)
                GROUP BY tc.hour
                ORDER BY tc.hour
                """
            ),
            {"highway_class": highway_class},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/congestion-ranking")
async def congestion_ranking(_: Read, db: Db, limit: Annotated[int, Query(ge=5, le=50)] = 20) -> list[dict]:
    """Worst-performing corridors, ranked."""
    rows = (
        await db.execute(
            text(
                """
                SELECT id, name, highway_class,
                       round(congestion_index::numeric, 3)::float8 AS congestion_index,
                       aadt::int AS aadt,
                       round(length_m::numeric, 0)::float8 AS length_m,
                       round(peak_speed_kmh::numeric, 1)::float8 AS peak_speed_kmh,
                       maxspeed_kmh::int AS maxspeed_kmh,
                       accident_count::int AS accidents,
                       round((100 * (1 - peak_speed_kmh / NULLIF(maxspeed_kmh, 0)))::numeric, 1)::float8 AS speed_loss_pct
                FROM transport.road_segments
                WHERE congestion_index IS NOT NULL AND name IS NOT NULL
                ORDER BY congestion_index DESC, aadt DESC NULLS LAST
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/transit-ridership")
async def transit_ridership(_: Read, db: Db) -> dict:
    by_mode = (
        await db.execute(
            text(
                """
                SELECT mode,
                       count(*)::int AS routes,
                       sum(daily_ridership)::int AS ridership,
                       round(sum(length_km)::numeric, 1)::float8 AS length_km,
                       round(avg(headway_min)::numeric, 1)::float8 AS mean_headway_min,
                       round((sum(daily_ridership) / NULLIF(sum(length_km), 0))::numeric, 0)::float8 AS riders_per_km
                FROM transport.transit_routes
                GROUP BY mode
                ORDER BY ridership DESC NULLS LAST
                """
            )
        )
    ).mappings().all()

    top_routes = (
        await db.execute(
            text(
                """
                SELECT route_code, route_name, mode, operator,
                       daily_ridership::int AS ridership,
                       round(headway_min::numeric, 1)::float8 AS headway_min,
                       round(length_km::numeric, 1)::float8 AS length_km
                FROM transport.transit_routes
                ORDER BY daily_ridership DESC NULLS LAST
                LIMIT 15
                """
            )
        )
    ).mappings().all()

    return {"byMode": [dict(r) for r in by_mode], "topRoutes": [dict(r) for r in top_routes]}


@router.get("/accessibility")
async def accessibility(_: Read, db: Db) -> dict:
    """Isochrone coverage: population and jobs reachable per mode and cut-off."""
    rows = (
        await db.execute(
            text(
                """
                SELECT mode, minutes::int AS minutes,
                       count(*)::int AS catchments,
                       round(avg(area_km2)::numeric, 2)::float8 AS mean_area_km2,
                       round(avg(population_reached)::numeric, 0)::float8 AS mean_population,
                       round(avg(jobs_reached)::numeric, 0)::float8 AS mean_jobs,
                       max(population_reached)::int AS max_population
                FROM transport.isochrones
                GROUP BY mode, minutes
                ORDER BY mode, minutes
                """
            )
        )
    ).mappings().all()

    # Share of tract population within a 15-minute walk of any transit stop.
    coverage = (
        await db.execute(
            text(
                """
                WITH walk15 AS (
                    SELECT ST_Union(geom) AS geom
                    FROM transport.isochrones
                    WHERE mode = 'walk' AND minutes = 15
                )
                SELECT
                    COALESCE(sum(t.population), 0)::int AS total_population,
                    COALESCE(sum(
                        t.population * (
                            ST_Area(ST_Intersection(t.geom, w.geom)::geography)
                            / NULLIF(ST_Area(t.geom::geography), 0)
                        )
                    ), 0)::int AS covered_population
                FROM demog.census_tracts t, walk15 w
                WHERE ST_Intersects(t.geom, w.geom)
                """
            )
        )
    ).mappings().one()

    cov = dict(coverage)
    total_pop = (
        await db.execute(text("SELECT COALESCE(sum(population), 0)::int FROM demog.census_tracts"))
    ).scalar_one()
    cov["total_population"] = total_pop
    cov["covered_pct"] = round(100 * cov["covered_population"] / total_pop, 1) if total_pop else 0.0

    return {"byModeAndTime": [dict(r) for r in rows], "walk15Coverage": cov}
