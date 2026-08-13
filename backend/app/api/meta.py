"""Study-area, dataset-provenance and map-style endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, get_optional_user
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


@router.get("/basemap-style")
async def basemap_style() -> dict:
    """A key-free raster basemap style.

    Deliberately not a hosted vector style: every vector basemap provider
    (Mapbox, MapTiler, Stadia) requires an API key, which would break the
    "clone and run" promise. The project's own data is served as MVT on top.
    """
    return {
        "version": 8,
        "name": "OSM Carto (raster)",
        "sources": {
            "osm": {
                "type": "raster",
                "tiles": ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
                "tileSize": 256,
                "maxzoom": 19,
                "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            }
        },
        "layers": [
            {"id": "background", "type": "background", "paint": {"background-color": "#eef1f4"}},
            {"id": "osm", "type": "raster", "source": "osm", "paint": {"raster-opacity": 0.85}},
        ],
    }
