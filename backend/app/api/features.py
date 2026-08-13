"""Generic, layer-driven feature access.

One set of endpoints serves all sixteen layers because every layer declares its
own columns, filters and required permission in the LayerSpec registry.
"""

import csv
import io
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.services import features as feat
from app.services.layers import LayerSpec, get_layer
from app.services.mvt import parse_filters

router = APIRouter(prefix="/layers", tags=["features"])

Db = Annotated[AsyncSession, Depends(get_db)]
Current = Annotated[CurrentUser, Depends(get_current_user)]


def _authorised_layer(layer_name: str, current: CurrentUser, action: str = "read") -> LayerSpec:
    layer = get_layer(layer_name)
    if layer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown layer {layer_name!r}")
    required = layer.permission if action == "read" else f"{layer.project}:{action}"
    if not current.has(required):
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Requires permission: {required}")
    return layer


@router.get("/{layer_name}/features")
async def list_features(
    layer_name: str,
    request: Request,
    current: Current,
    db: Db,
    bbox: Annotated[str | None, Query(description="minx,miny,maxx,maxy in EPSG:4326")] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
    order_by: str | None = None,
    descending: bool = True,
    geometry: bool = True,
    simplify_m: Annotated[float | None, Query(ge=0, le=10000)] = None,
) -> dict:
    layer = _authorised_layer(layer_name, current)
    filters = parse_filters(layer, dict(request.query_params))
    try:
        return await feat.fetch_features(
            db,
            layer,
            filters=filters,
            bbox=bbox,
            limit=limit,
            offset=offset,
            order_by=order_by,
            descending=descending,
            include_geometry=geometry,
            simplify_m=simplify_m,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/{layer_name}/features/{feature_id}")
async def get_feature(layer_name: str, feature_id: int, current: Current, db: Db) -> dict:
    layer = _authorised_layer(layer_name, current)
    feature = await feat.fetch_feature_by_id(db, layer, feature_id)
    if feature is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Feature not found")
    return feature


@router.get("/{layer_name}/breakdown")
async def breakdown(
    layer_name: str,
    request: Request,
    current: Current,
    db: Db,
    by: Annotated[str, Query(description="Categorical column to group on")],
    measures: Annotated[
        str | None, Query(description="Comma list of alias=agg:column, e.g. avgYield=avg:yield_t_ha")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
) -> dict:
    layer = _authorised_layer(layer_name, current)
    if not current.has("analytics:read"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires permission: analytics:read")

    parsed: dict[str, str] = {}
    if measures:
        for item in measures.split(","):
            alias, _, spec = item.strip().partition("=")
            if alias and spec:
                parsed[alias] = spec

    filters = parse_filters(layer, dict(request.query_params))
    try:
        rows = await feat.categorical_breakdown(
            db, layer, by, measures=parsed, filters=filters, limit=limit
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    return {"layer": layer.name, "groupBy": by, "rows": rows}


@router.get("/{layer_name}/histogram")
async def layer_histogram(
    layer_name: str,
    request: Request,
    current: Current,
    db: Db,
    column: str,
    bins: Annotated[int, Query(ge=2, le=100)] = 20,
) -> dict:
    layer = _authorised_layer(layer_name, current)
    if not current.has("analytics:read"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires permission: analytics:read")
    filters = parse_filters(layer, dict(request.query_params))
    try:
        return await feat.histogram(db, layer, column, bins=bins, filters=filters)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.get("/{layer_name}/export")
async def export_layer(
    layer_name: str,
    request: Request,
    current: Current,
    db: Db,
    fmt: Annotated[str, Query(pattern="^(geojson|csv)$")] = "geojson",
    bbox: str | None = None,
    limit: Annotated[int, Query(ge=1, le=20000)] = 5000,
) -> Response:
    layer = _authorised_layer(layer_name, current)
    if not current.has("data:export"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Requires permission: data:export")

    filters = parse_filters(layer, dict(request.query_params))
    try:
        collection = await feat.fetch_features(
            db, layer, filters=filters, bbox=bbox, limit=limit, include_geometry=fmt == "geojson"
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if fmt == "geojson":
        body = json.dumps(
            {"type": "FeatureCollection", "features": collection["features"]}
        ).encode()
        media, ext = "application/geo+json", "geojson"
    else:
        buf = io.StringIO()
        rows = [f["properties"] for f in collection["features"]]
        writer = csv.DictWriter(buf, fieldnames=list(layer.columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
        body = buf.getvalue().encode()
        media, ext = "text/csv", "csv"

    return Response(
        content=body,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{layer.name}.{ext}"'},
    )
