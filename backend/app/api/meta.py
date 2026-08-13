"""Study-area, dataset-provenance and map-style endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, get_optional_user
from app.services.basemaps import basemaps_payload, overlays_payload
from app.services.layers import PROJECTS

router = APIRouter(prefix="/meta", tags=["meta"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/study-area")
async def study_area(db: Db) -> dict:
    """Bounding box + centroid the frontend uses to fit the initial view."""
    row = (
        await db.execute(
            text(
                """
                SELECT code, name, country,
                       ST_XMin(bbox) AS minx, ST_YMin(bbox) AS miny,
                       ST_XMax(bbox) AS maxx, ST_YMax(bbox) AS maxy,
                       ST_X(centre) AS lon, ST_Y(centre) AS lat
                FROM (
                    SELECT code, name, country,
                           ST_Envelope(geom) AS bbox,
                           ST_Centroid(geom) AS centre
                    FROM meta.study_area ORDER BY id LIMIT 1
                ) s
                """
            )
        )
    ).mappings().one_or_none()

    if row is None:
        # Fall back to a world view rather than 404 -- the frontend should still
        # render a usable map before the ETL has run.
        return {
            "code": None,
            "name": "No study area loaded",
            "bbox": [-180, -85, 180, 85],
            "center": [0, 20],
            "zoom": 2,
        }

    d = dict(row)
    return {
        "code": d["code"],
        "name": d["name"],
        "country": d["country"],
        "bbox": [d["minx"], d["miny"], d["maxx"], d["maxy"]],
        "center": [d["lon"], d["lat"]],
        "zoom": 11,
    }


@router.get("/sources")
async def dataset_sources(db: Db, project: str | None = None) -> list[dict]:
    rows = (
        await db.execute(
            text(
                """
                SELECT project, layer, dataset_name, provider, license, source_url,
                       fetched_at, feature_count, notes
                FROM meta.dataset_source
                WHERE (CAST(:project AS text) IS NULL OR project = :project)
                ORDER BY project, layer
                """
            ),
            {"project": project},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/projects")
async def project_catalogue(
    current: Annotated[CurrentUser | None, Depends(get_optional_user)],
) -> list[dict]:
    """Public project list. `accessible` reflects the caller's permissions,
    so the landing page can show all five while greying out the locked ones."""
    return [
        {
            "key": key,
            "title": meta["title"],
            "tagline": meta["tagline"],
            "accent": meta["accent"],
            "icon": meta["icon"],
            "accessible": bool(current and current.has(meta["permission"])),
        }
        for key, meta in PROJECTS.items()
    ]


@router.get("/basemaps")
async def basemaps() -> list[dict]:
    """Key-free raster basemaps the frontend can switch between.

    Deliberately not a hosted vector style or Google's tile API -- every vector
    basemap provider (Mapbox, MapTiler, Stadia) and Google Maps Platform both
    require an API key, which would break the "clone and run" promise. See
    app/services/basemaps.py for why each of these was picked instead.
    """
    return basemaps_payload()


@router.get("/overlays")
async def overlays() -> list[dict]:
    """Raster reference overlays (currently: ESA WorldCover land cover),
    drawn above the basemap and below the project's own vector layers."""
    return overlays_payload()
