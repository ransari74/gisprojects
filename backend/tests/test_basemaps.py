"""Basemap and overlay registry endpoints.

These are pure Python config (app/services/basemaps.py) with no database
dependency, but they are still exercised through the ASGI transport like every
other endpoint, since what matters is the HTTP contract the frontend actually
consumes.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://gis:gis@localhost:5432/gisportfolio")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.main import app  # noqa: E402
from app.services.basemaps import BASEMAPS, OVERLAYS, WORLDCOVER_LEGEND  # noqa: E402

# Applied per-test rather than as a module-wide pytestmark: two tests below are
# plain synchronous checks against the registry module, and marking those with
# asyncio as well just produces a pytest warning for no benefit.
async_test = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@async_test
async def test_basemaps_endpoint_requires_no_auth(client):
    """Basemap/overlay descriptors are style metadata, not application data --
    same trust level as /meta/study-area, so no token should be required."""
    resp = await client.get("/api/meta/basemaps")
    assert resp.status_code == 200


@async_test
async def test_basemaps_include_a_roads_default_and_key_free_imagery(client):
    resp = await client.get("/api/meta/basemaps")
    body = resp.json()
    ids = {b["id"] for b in body}

    # osm must exist and be a "roads" kind so MapView has a safe, always-known
    # default to fall back to.
    assert "osm" in ids
    osm = next(b for b in body if b["id"] == "osm")
    assert osm["kind"] == "roads"

    # At least one satellite/imagery option, and it must not require a key --
    # nothing in any tile URL should look like an API key placeholder.
    imagery = [b for b in body if b["kind"] == "imagery"]
    assert imagery, "expected at least one imagery basemap"
    for basemap in body:
        for layer in basemap["layers"]:
            for url in layer["tiles"]:
                assert "key=" not in url.lower()
                assert "token=" not in url.lower()
                assert "google" not in url.lower(), "Google tiles are deliberately not used -- see basemaps.py"


@async_test
async def test_hybrid_basemap_stacks_imagery_and_labels(client):
    resp = await client.get("/api/meta/basemaps")
    hybrid = next(b for b in resp.json() if b["id"] == "esri_hybrid")
    assert len(hybrid["layers"]) == 2, "hybrid should be imagery + a separate labels/boundaries layer"


@async_test
async def test_every_basemap_layer_has_a_zxy_tile_template(client):
    resp = await client.get("/api/meta/basemaps")
    for basemap in resp.json():
        for layer in basemap["layers"]:
            for url in layer["tiles"]:
                assert "{z}" in url and "{x}" in url and "{y}" in url, url


@async_test
async def test_overlays_endpoint(client):
    resp = await client.get("/api/meta/overlays")
    assert resp.status_code == 200
    body = resp.json()
    ids = {o["id"] for o in body}
    assert "esa_worldcover" in ids


@async_test
async def test_worldcover_overlay_is_a_wms_bbox_template_with_full_legend(client):
    resp = await client.get("/api/meta/overlays")
    worldcover = next(o for o in resp.json() if o["id"] == "esa_worldcover")

    # MapLibre substitutes this token itself; there is no WMTS proxy behind it.
    assert all("{bbox-epsg-3857}" in url for url in worldcover["tiles"])
    assert worldcover["project"] == "agriculture"
    assert 0 < worldcover["defaultOpacity"] <= 1

    # The legend is what keeps colour from being the only signal on the map --
    # every class ESA actually ships needs a label and a colour here.
    assert len(worldcover["legend"]) == 11
    for entry in worldcover["legend"]:
        assert entry["colorHex"].startswith("#")
        assert entry["label"]


def test_worldcover_legend_matches_the_official_esa_class_count():
    """Static check against the source module, independent of the HTTP layer."""
    assert len(WORLDCOVER_LEGEND) == 11
    assert {c.code for c in WORLDCOVER_LEGEND} == {10, 20, 30, 40, 50, 60, 70, 80, 90, 95, 100}


def test_basemap_registry_has_no_duplicate_ids():
    ids = [b.id for b in BASEMAPS]
    assert len(ids) == len(set(ids))
    ids = [o.id for o in OVERLAYS]
    assert len(ids) == len(set(ids))


@async_test
async def test_old_basemap_style_endpoint_is_retired(client):
    """Superseded by /meta/basemaps + /meta/overlays; must not silently exist
    as an unmaintained duplicate."""
    resp = await client.get("/api/meta/basemap-style")
    assert resp.status_code == 404
