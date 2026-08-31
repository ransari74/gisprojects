"""Vector tile endpoints.

    GET /api/tiles/{layer}/{z}/{x}/{y}.mvt   -- protobuf tile
    GET /api/tiles/{layer}/tilejson.json     -- TileJSON 3.0 descriptor
    GET /api/tiles/capabilities              -- every layer the caller may see
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_tile_user
from app.services import mvt
from app.services.layers import ALL_LAYERS, PROJECTS, get_layer

router = APIRouter(prefix="/tiles", tags=["tiles"])

MVT_MEDIA_TYPE = "application/vnd.mapbox-vector-tile"


@router.get("/capabilities")
async def capabilities(current: Annotated[CurrentUser, Depends(get_current_user)]) -> dict:
    """Layer catalogue filtered to what this caller is allowed to request.

    The frontend builds its entire layer panel from this, so a user without
    e.g. parcel:read never even sees the parcel layers listed.
    """
    visible = [layer for layer in ALL_LAYERS if current.has(layer.permission)]
    projects = []
    for key, meta in PROJECTS.items():
        project_layers = [layer for layer in visible if layer.project == key]
        if not project_layers:
            continue
        projects.append(
            {
                "key": key,
                **{k: v for k, v in meta.items() if k != "permission"},
                "layers": [
                    {
                        "name": layer.name,
                        "title": layer.title,
                        "geomKind": layer.geom_kind,
                        "minZoom": layer.min_zoom,
                        "maxZoom": layer.max_zoom,
                        "columns": list(layer.columns),
                        "filterable": list(layer.filterable),
                        "rangeFilterable": list(layer.range_filterable),
                        "styleHint": layer.style_hint,
                        "description": layer.description,
                        "tileUrl": f"{settings.api_prefix}/tiles/{layer.name}/{{z}}/{{x}}/{{y}}.mvt",
                    }
                    for layer in project_layers
                ],
            }
        )
    return {"projects": projects, "tileExtent": settings.tile_extent}


@router.get("/{layer_name}/tilejson.json")
async def tilejson(
    layer_name: str,
    request: Request,
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    layer = get_layer(layer_name)
    if layer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown layer {layer_name!r}")
    if not current.has(layer.permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires permission: {layer.permission}")

    base = str(request.base_url).rstrip("/")
    return {
        "tilejson": "3.0.0",
        "name": layer.name,
        "description": layer.description,
        "scheme": "xyz",
        "minzoom": layer.min_zoom,
        "maxzoom": layer.max_zoom,
        "tiles": [f"{base}{settings.api_prefix}/tiles/{layer.name}/{{z}}/{{x}}/{{y}}.mvt"],
        "vector_layers": [
            {
                "id": layer.name,
                "description": layer.description,
                "minzoom": layer.min_zoom,
                "maxzoom": layer.max_zoom,
                "fields": {c: "String" for c in layer.columns},
            }
        ],
    }


@router.get(
    "/{layer_name}/{z}/{x}/{y}.mvt",
    response_class=Response,
    responses={200: {"content": {MVT_MEDIA_TYPE: {}}}},
)
async def get_tile(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[CurrentUser, Depends(get_tile_user)],
    layer_name: str = Path(...),
    z: int = Path(..., ge=0, le=22),
    x: int = Path(..., ge=0),
    y: int = Path(..., ge=0),
) -> Response:
    layer = get_layer(layer_name)
    if layer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown layer {layer_name!r}")
    if not current.has(layer.permission):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires permission: {layer.permission}")

    # A z/x/y outside the pyramid would make ST_TileEnvelope raise; answer with
    # an empty tile instead so a mis-behaving client does not produce 500s.
    max_index = (1 << z) - 1
    if x > max_index or y > max_index:
        return _tile_response(b"", cached=False)

    if z < layer.min_zoom or z > layer.max_zoom:
        return _tile_response(b"", cached=False)

    filters = mvt.parse_filters(layer, dict(request.query_params))
    key = mvt.cache_key(layer.name, z, x, y, filters)

    cached = mvt.tile_cache.get(key)
    if cached is not None:
        return _tile_response(cached, cached=True)

    payload = await mvt.render_tile(db, layer, z, x, y, filters)
    mvt.tile_cache.set(key, payload)
    return _tile_response(payload, cached=False)


def _tile_response(payload: bytes, *, cached: bool) -> Response:
    if not payload:
        # 204 is the conventional "this tile is legitimately empty" answer;
        # MapLibre treats it as a blank tile and does not retry.
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return Response(
        content=payload,
        media_type=MVT_MEDIA_TYPE,
        headers={
            "Cache-Control": f"public, max-age={settings.tile_cache_seconds}",
            "X-Tile-Cache": "HIT" if cached else "MISS",
            "Content-Length": str(len(payload)),
        },
    )


@router.get("/_cache/stats")
async def cache_stats(current: Annotated[CurrentUser, Depends(get_current_user)]) -> dict:
    return mvt.tile_cache.stats()


@router.delete("/_cache", status_code=status.HTTP_204_NO_CONTENT)
async def flush_cache(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    if not current.has("admin:users"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires permission: admin:users")
    if settings.demo_read_only:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This is a public demo deployment -- flushing the tile cache is disabled here.",
        )
    mvt.tile_cache.clear()
