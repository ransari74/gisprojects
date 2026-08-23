"""Integration tests against a live PostGIS database.

These are deliberately integration tests rather than unit tests with mocks:
almost everything worth breaking in this project lives in SQL -- the MVT query,
the permission filter, the aggregation -- and a mocked session would verify
none of it.

    make test          # docker compose
    pytest backend/tests -q   # against a local Postgres

Set TEST_DATABASE_URL to point at a database loaded via `python -m etl.load
--generate`. Tests skip (not fail) when no database is reachable.
"""

from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://gis:gis@localhost:5432/gisportfolio"),
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services.layers import ALL_LAYERS, LAYER_INDEX, PROJECTS  # noqa: E402

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo1234")

# The SQLAlchemy async engine is module-level, so it binds to the first event
# loop that touches it. Pinning every test and fixture in this module to one
# session-scoped loop keeps asyncpg connections on the loop that created them.
pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac


@pytest_asyncio.fixture(loop_scope="session", scope="session", autouse=True)
async def require_database():
    """Skip the suite unless a migrated, loaded database is reachable.

    Also seeds the demo accounts. The app normally does that in its lifespan
    hook, which ASGITransport does not run -- without this the suite would only
    pass on a database some other process had already started the app against.
    """
    from sqlalchemy import text

    from app.core.bootstrap import schema_ready, seed_demo_users

    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
            if not await schema_ready(db):
                pytest.skip(
                    "Schema not migrated -- run: alembic upgrade head",
                    allow_module_level=True,
                )
            count = (await db.execute(text("SELECT count(*) FROM agri.fields"))).scalar_one()
            await seed_demo_users(db)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"No database available: {type(exc).__name__}: {exc}", allow_module_level=True)
    if not count:
        pytest.skip("Database is empty -- run: python -m etl.load --generate")


async def login(client: AsyncClient, email: str) -> str:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": DEMO_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def admin_token(client):
    return await login(client, "admin@geo.dev")


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def agronomist_token(client):
    return await login(client, "agronomist@geo.dev")


@pytest_asyncio.fixture(loop_scope="session", scope="session")
async def viewer_token(client):
    return await login(client, "viewer@geo.dev")


# ---------------------------------------------------------------------------
# Health and auth
# ---------------------------------------------------------------------------
async def test_health(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["database"] == "connected"


async def test_login_rejects_wrong_password(client):
    resp = await client.post(
        "/api/auth/login", json={"email": "admin@geo.dev", "password": "wrong-password"}
    )
    assert resp.status_code == 401


async def test_login_does_not_leak_account_existence(client):
    """Unknown user and wrong password must be indistinguishable."""
    unknown = await client.post(
        "/api/auth/login", json={"email": "nobody@geo.dev", "password": "whatever1"}
    )
    wrong = await client.post(
        "/api/auth/login", json={"email": "admin@geo.dev", "password": "whatever1"}
    )
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json()["detail"] == wrong.json()["detail"]


async def test_me_returns_permissions_and_projects(client, admin_token):
    resp = await client.get("/api/auth/me", headers=auth(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_superuser"] is True
    # Every project in the registry, since a superuser bypasses the filter.
    assert len(body["projects"]) == len(PROJECTS)


async def test_refresh_rotates_and_burns_the_old_token(client):
    first = await client.post(
        "/api/auth/login", json={"email": "viewer@geo.dev", "password": DEMO_PASSWORD}
    )
    refresh = first.json()["refresh_token"]

    second = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert second.status_code == 200
    assert second.json()["refresh_token"] != refresh

    # Replaying the burned token must fail.
    replay = await client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert replay.status_code == 401


async def test_unauthenticated_requests_are_rejected(client):
    for path in ("/api/auth/me", "/api/agriculture/summary", "/api/tiles/capabilities"):
        assert (await client.get(path)).status_code == 401


async def test_malformed_token_is_rejected(client):
    resp = await client.get("/api/auth/me", headers=auth("not.a.real.jwt"))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
async def test_agronomist_cannot_read_parcels(client, agronomist_token):
    resp = await client.get("/api/parcel/summary", headers=auth(agronomist_token))
    assert resp.status_code == 403


async def test_agronomist_can_read_agriculture(client, agronomist_token):
    resp = await client.get("/api/agriculture/summary", headers=auth(agronomist_token))
    assert resp.status_code == 200


async def test_viewer_cannot_export(client, viewer_token):
    resp = await client.get(
        "/api/layers/agri_fields/export?fmt=csv", headers=auth(viewer_token)
    )
    assert resp.status_code == 403


async def test_viewer_cannot_reach_admin(client, viewer_token):
    assert (await client.get("/api/admin/users", headers=auth(viewer_token))).status_code == 403


async def test_capabilities_are_filtered_by_permission(client, agronomist_token, admin_token):
    agro = (await client.get("/api/tiles/capabilities", headers=auth(agronomist_token))).json()
    admin = (await client.get("/api/tiles/capabilities", headers=auth(admin_token))).json()

    agro_projects = {p["key"] for p in agro["projects"]}
    admin_projects = {p["key"] for p in admin["projects"]}

    assert "agriculture" in agro_projects
    assert "parcel" not in agro_projects       # agronomist has no parcel:read
    assert admin_projects == set(PROJECTS)


async def test_tile_permission_is_enforced(client, agronomist_token):
    resp = await client.get(
        "/api/tiles/parcel_parcels/13/4212/2702.mvt", headers=auth(agronomist_token)
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Vector tiles
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("layer", "z", "x", "y"),
    [
        ("agri_fields", 11, 1053, 675),
        ("transport_roads", 11, 1053, 675),
        ("demog_tracts", 11, 1053, 675),
        ("parcel_parcels", 13, 4212, 2702),
        ("terrain_buildings", 15, 16848, 10808),
        ("rs_index_cells", 11, 1053, 675),
        ("rs_subsidence", 12, 2106, 1352),
    ],
)
async def test_tiles_return_decodable_mvt(client, admin_token, layer, z, x, y):
    resp = await client.get(f"/api/tiles/{layer}/{z}/{x}/{y}.mvt", headers=auth(admin_token))
    assert resp.status_code == 200, f"{layer} returned {resp.status_code}"
    assert resp.headers["content-type"].startswith("application/vnd.mapbox-vector-tile")
    assert len(resp.content) > 0

    mvt = pytest.importorskip("mapbox_vector_tile")
    decoded = mvt.decode(resp.content)
    assert layer in decoded
    assert len(decoded[layer]["features"]) > 0


async def test_tile_outside_pyramid_returns_empty_not_error(client, admin_token):
    """x/y beyond 2^z - 1 would make ST_TileEnvelope raise."""
    resp = await client.get("/api/tiles/agri_fields/2/99/99.mvt", headers=auth(admin_token))
    assert resp.status_code == 204


async def test_tile_below_min_zoom_is_empty(client, admin_token):
    layer = LAYER_INDEX["terrain_buildings"]
    assert layer.min_zoom > 2
    resp = await client.get("/api/tiles/terrain_buildings/2/2/1.mvt", headers=auth(admin_token))
    assert resp.status_code == 204


async def test_unknown_layer_is_404(client, admin_token):
    resp = await client.get("/api/tiles/no_such_layer/10/1/1.mvt", headers=auth(admin_token))
    assert resp.status_code == 404


async def test_tile_cache_reports_a_hit_on_the_second_request(client, admin_token):
    url = "/api/tiles/demog_tracts/11/1053/675.mvt"
    first = await client.get(url, headers=auth(admin_token))
    second = await client.get(url, headers=auth(admin_token))
    assert first.status_code == second.status_code == 200
    assert second.headers["X-Tile-Cache"] == "HIT"
    assert first.content == second.content


async def test_tile_filters_reduce_the_feature_count(client, admin_token):
    mvt = pytest.importorskip("mapbox_vector_tile")
    url = "/api/tiles/transport_roads/11/1053/675.mvt"

    unfiltered = await client.get(url, headers=auth(admin_token))
    filtered = await client.get(f"{url}?filter_highway_class=motorway", headers=auth(admin_token))
    assert filtered.status_code == 200

    n_all = len(mvt.decode(unfiltered.content)["transport_roads"]["features"])
    n_mot = len(mvt.decode(filtered.content)["transport_roads"]["features"])
    assert 0 < n_mot < n_all
    # Every surviving feature must actually match the filter.
    for feature in mvt.decode(filtered.content)["transport_roads"]["features"]:
        assert feature["properties"]["highway_class"] == "motorway"


async def test_tilejson_is_wellformed(client, admin_token):
    resp = await client.get("/api/tiles/agri_fields/tilejson.json", headers=auth(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["tilejson"] == "3.0.0"
    assert body["tiles"] and "{z}" in body["tiles"][0]


# ---------------------------------------------------------------------------
# Feature + analytics endpoints
# ---------------------------------------------------------------------------
async def test_features_returns_valid_geojson(client, admin_token):
    resp = await client.get("/api/layers/demog_tracts/features?limit=3", headers=auth(admin_token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) == 3
    feature = body["features"][0]
    assert feature["geometry"]["type"] in ("Polygon", "MultiPolygon")
    assert "population" in feature["properties"]
    assert body["totalCount"] >= 3


async def test_features_bbox_filter_narrows_results(client, admin_token):
    everything = await client.get(
        "/api/layers/agri_fields/features?limit=1&geometry=false", headers=auth(admin_token)
    )
    narrow = await client.get(
        "/api/layers/agri_fields/features?limit=1&geometry=false&bbox=4.95,51.98,5.00,52.02",
        headers=auth(admin_token),
    )
    assert narrow.status_code == 200
    assert narrow.json()["totalCount"] < everything.json()["totalCount"]


async def test_bad_bbox_is_a_400_not_a_500(client, admin_token):
    resp = await client.get(
        "/api/layers/agri_fields/features?bbox=not,a,bbox,at-all", headers=auth(admin_token)
    )
    assert resp.status_code == 400


async def test_unknown_filter_column_is_ignored_not_fatal(client, admin_token):
    """A stale bookmark with a dropped filter should still render."""
    resp = await client.get(
        "/api/layers/agri_fields/features?limit=1&filter_no_such_column=x",
        headers=auth(admin_token),
    )
    assert resp.status_code == 200


async def test_histogram_bins_sum_to_the_row_count(client, admin_token):
    resp = await client.get(
        "/api/layers/agri_fields/histogram?column=yield_t_ha&bins=10", headers=auth(admin_token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["bins"]) > 0
    assert sum(b["count"] for b in body["bins"]) == body["count"]
    assert body["min"] <= body["median"] <= body["max"]


async def test_breakdown_with_measures(client, admin_token):
    resp = await client.get(
        "/api/layers/parcel_parcels/breakdown?by=land_use&measures=meanValue=avg:value_per_m2",
        headers=auth(admin_token),
    )
    assert resp.status_code == 200
    rows = resp.json()["rows"]
    assert rows and "meanValue" in rows[0] and "count" in rows[0]


async def test_breakdown_rejects_an_injected_measure(client, admin_token):
    resp = await client.get(
        "/api/layers/parcel_parcels/breakdown?by=land_use"
        "&measures=x=avg:value_per_m2) FROM parcel.parcels; DROP TABLE auth.users --",
        headers=auth(admin_token),
    )
    assert resp.status_code == 400


async def test_export_csv_has_a_header_row(client, admin_token):
    resp = await client.get(
        "/api/layers/agri_fields/export?fmt=csv&limit=5", headers=auth(admin_token)
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert "crop_type" in lines[0]
    assert len(lines) == 6  # header + 5 rows


@pytest.mark.parametrize(
    "path",
    [
        "/api/agriculture/summary",
        "/api/agriculture/yield-by-crop",
        "/api/agriculture/soil-yield-correlation",
        "/api/agriculture/ndvi-timeseries",
        "/api/agriculture/irrigation-coverage",
        "/api/parcel/summary",
        "/api/parcel/land-use-breakdown",
        "/api/parcel/value-distribution",
        "/api/parcel/price-trend",
        "/api/parcel/zoning-compliance",
        "/api/demographics/summary",
        "/api/demographics/population-pyramid",
        "/api/demographics/income-vs-education",
        "/api/demographics/commute-matrix",
        "/api/demographics/age-composition",
        "/api/transport/summary",
        "/api/transport/network-by-class",
        "/api/transport/hourly-profile",
        "/api/transport/congestion-ranking",
        "/api/transport/transit-ridership",
        "/api/transport/accessibility",
        "/api/terrain/summary",
        "/api/terrain/height-distribution",
        "/api/terrain/by-type",
        "/api/terrain/hypsometry",
        "/api/terrain/profile",
        "/api/terrain/solar-ranking",
        "/api/remote-sensing/summary",
        "/api/remote-sensing/scene-inventory",
        "/api/remote-sensing/index-timeseries",
        "/api/remote-sensing/change-matrix",
        "/api/remote-sensing/heat-island",
        "/api/remote-sensing/subsidence",
        "/api/remote-sensing/index-distribution",
        "/api/remote-sensing/water-extent",
    ],
)
async def test_analytics_endpoints_return_data(client, admin_token, path):
    resp = await client.get(path, headers=auth(admin_token))
    assert resp.status_code == 200, f"{path}: {resp.text[:200]}"
    body = resp.json()
    assert body not in (None, [], {}), f"{path} returned an empty payload"


async def test_population_pyramid_bands_are_ordered(client, admin_token):
    rows = (await client.get("/api/demographics/population-pyramid", headers=auth(admin_token))).json()
    orders = [r["band_order"] for r in rows]
    assert orders == sorted(orders)
    assert all(r["male"] >= 0 and r["female"] >= 0 for r in rows)


async def test_hourly_profile_has_a_morning_and_evening_peak(client, admin_token):
    rows = (await client.get("/api/transport/hourly-profile", headers=auth(admin_token))).json()
    assert len(rows) == 24
    by_hour = {r["hour"]: r["vehicles"] for r in rows}
    night = max(by_hour[h] for h in (1, 2, 3, 4))
    assert by_hour[8] > night * 3
    assert by_hour[17] > night * 3


async def test_crop_indexing_exposes_the_soil_signal(client, admin_token):
    """The raw correlation is confounded by crop mix; the indexed one is not."""
    body = (
        await client.get(
            "/api/agriculture/soil-yield-correlation?x=soil_organic_c", headers=auth(admin_token)
        )
    ).json()
    assert abs(body["pearson_r_indexed"]) > abs(body["pearson_r"])
    assert body["n"] > 100


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------
async def test_admin_cannot_delete_themselves(client, admin_token):
    me = (await client.get("/api/auth/me", headers=auth(admin_token))).json()
    resp = await client.delete(f"/api/admin/users/{me['id']}", headers=auth(admin_token))
    assert resp.status_code == 400


async def test_admin_role_permissions_cannot_be_narrowed(client, admin_token):
    roles = (await client.get("/api/admin/roles", headers=auth(admin_token))).json()
    admin_role = next(r for r in roles if r["name"] == "admin")
    resp = await client.put(
        f"/api/admin/roles/{admin_role['id']}/permissions",
        json={"permission_codes": []},
        headers=auth(admin_token),
    )
    assert resp.status_code == 400


async def test_user_lifecycle(client, admin_token):
    created = await client.post(
        "/api/admin/users",
        json={
            "email": "lifecycle-test@geo.dev",
            "password": "temp-password-123",
            "full_name": "Lifecycle Test",
            "role_names": ["viewer"],
        },
        headers=auth(admin_token),
    )
    if created.status_code == 409:  # left over from a previous run
        listing = (await client.get("/api/admin/users?limit=200", headers=auth(admin_token))).json()
        user_id = next(u["id"] for u in listing if u["email"] == "lifecycle-test@geo.dev")
    else:
        assert created.status_code == 201, created.text
        user_id = created.json()["id"]
        assert [r["name"] for r in created.json()["roles"]] == ["viewer"]

    promoted = await client.put(
        f"/api/admin/users/{user_id}/roles",
        json={"role_names": ["analyst"]},
        headers=auth(admin_token),
    )
    assert promoted.status_code == 200
    assert [r["name"] for r in promoted.json()["roles"]] == ["analyst"]

    # The new role must actually take effect on a fresh login: an analyst can
    # read parcels, which the viewer role the user started with cannot.
    logged_in = await client.post(
        "/api/auth/login",
        json={"email": "lifecycle-test@geo.dev", "password": "temp-password-123"},
    )
    assert logged_in.status_code == 200, logged_in.text
    new_token = logged_in.json()["access_token"]
    assert (await client.get("/api/parcel/summary", headers=auth(new_token))).status_code == 200
    assert (await client.get("/api/admin/users", headers=auth(new_token))).status_code == 403

    deleted = await client.delete(f"/api/admin/users/{user_id}", headers=auth(admin_token))
    assert deleted.status_code == 204
    assert (await client.get(f"/api/admin/users/{user_id}", headers=auth(admin_token))).status_code == 404


# ---------------------------------------------------------------------------
# Remote sensing
#
# These assert the *relationships* the project claims, not just that the
# endpoints answer. A change-detection matrix that does not balance, or a heat
# island that comes out the wrong sign, is a broken analysis returning 200.
# ---------------------------------------------------------------------------
async def test_heat_island_runs_the_right_way_round(client, admin_token):
    """LST falls as NDVI rises, and rises with impervious cover."""
    veg = (await client.get(
        "/api/remote-sensing/heat-island?x=ndvi&limit=200", headers=auth(admin_token)
    )).json()
    sealed = (await client.get(
        "/api/remote-sensing/heat-island?x=imperviousness_pct&limit=200", headers=auth(admin_token)
    )).json()

    assert veg["pearson_r"] < 0, "vegetation should cool the surface, not warm it"
    assert sealed["pearson_r"] > 0, "sealed ground should warm the surface"
    # Strong enough to be a finding, loose enough not to pin the generator's
    # exact noise level.
    assert veg["r_squared"] > 0.2


async def test_built_up_is_the_hottest_class(client, admin_token):
    resp = await client.get("/api/remote-sensing/heat-island", headers=auth(admin_token))
    by_class = {r["landcover_class"]: r for r in resp.json()["byClass"]}
    assert by_class["built_up"]["mean_lst_c"] > by_class["tree_cover"]["mean_lst_c"]
    # The anomaly is a departure from the mean, so the classes must straddle zero.
    assert by_class["built_up"]["mean_anomaly_c"] > 0
    assert by_class["tree_cover"]["mean_anomaly_c"] < 0


async def test_summary_uhi_delta_is_plausible(client, admin_token):
    """A daytime surface UHI outside roughly 1-10 C means the model drifted."""
    body = (await client.get("/api/remote-sensing/summary", headers=auth(admin_token))).json()
    assert 1.0 < body["uhi_delta_c"] < 10.0


async def test_water_summary_does_not_double_count_across_passes(client, admin_token):
    """Permanent water is reported per observation, not summed over all of them.

    Summing the raw rows counts the same lake once per acquisition, which is
    how this silently reported several times the study area's actual water.
    """
    body = (await client.get("/api/remote-sensing/summary", headers=auth(admin_token))).json()
    assert body["water_observations"] > 1, "test is meaningless with a single pass"
    assert body["permanent_water_ha"] < body["total_area_ha"] * 0.15


async def test_change_matrix_balances_against_the_grid(client, admin_token):
    """Every cell appears exactly once in the transition table."""
    summary = (await client.get("/api/remote-sensing/summary", headers=auth(admin_token))).json()
    matrix = (await client.get("/api/remote-sensing/change-matrix", headers=auth(admin_token))).json()

    assert sum(t["cells"] for t in matrix["transitions"]) == summary["cell_count"]
    changed = sum(t["cells"] for t in matrix["transitions"] if t["from_class"] != t["to_class"])
    assert changed == summary["changed_cells"]
    # Gains and losses are the same land seen from either end, so the net
    # column has to cancel out across all classes.
    assert abs(sum(n["net_ha"] for n in matrix["net"])) < 1.0


async def test_peat_subsides_faster_than_sand(client, admin_token):
    """The finding the project exists to show, in the direction it actually goes."""
    by_soil = {r["soil_type"]: r for r in (
        await client.get("/api/remote-sensing/subsidence", headers=auth(admin_token))
    ).json()["bySoil"]}

    assert by_soil["peat"]["mean_velocity_mm_yr"] < by_soil["clay"]["mean_velocity_mm_yr"]
    assert by_soil["clay"]["mean_velocity_mm_yr"] < by_soil["sand"]["mean_velocity_mm_yr"]
    # Negative is downward -- a sign flip here would invert the whole layer.
    assert by_soil["peat"]["mean_velocity_mm_yr"] < 0


async def test_cloud_makes_most_optical_scenes_unusable(client, admin_token):
    """The premise of the SAR layers: optical coverage over the Netherlands is
    mostly lost to cloud, while radar is unaffected."""
    by_platform = (await client.get(
        "/api/remote-sensing/scene-inventory", headers=auth(admin_token)
    )).json()["byPlatform"]

    sar = [p for p in by_platform if p["sensor"] == "C-SAR"]
    optical = [p for p in by_platform if p["sensor"] != "C-SAR"]
    assert sar and optical

    assert all(p["usable"] == p["scenes"] for p in sar), "radar does not lose scenes to cloud"
    optical_usable = sum(p["usable"] for p in optical) / sum(p["scenes"] for p in optical)
    assert 0.05 < optical_usable < 0.45, f"optical usable rate {optical_usable:.2f} is not realistic"


async def test_seasonal_index_separates_crops_from_built_up(client, admin_token):
    """Cropland's NDVI swings through the season; built-up land does not.

    This is the argument for using a time series rather than one date, so a
    generator change that flattened it would quietly remove the point.
    """
    rows = (await client.get(
        "/api/remote-sensing/index-timeseries?index=ndvi", headers=auth(admin_token)
    )).json()

    def amplitude(series: str) -> float:
        values = [r["value"] for r in rows if r["series"] == series]
        assert values, f"no {series} series"
        return max(values) - min(values)

    assert amplitude("cropland") > 3 * amplitude("built_up")


async def test_index_distribution_rejects_an_injected_column(client, admin_token):
    resp = await client.get(
        "/api/remote-sensing/index-distribution?index=ndvi;DROP TABLE rs.scenes",
        headers=auth(admin_token),
    )
    assert resp.status_code == 400


async def test_index_distribution_bins_sum_to_the_grid(client, admin_token):
    summary = (await client.get("/api/remote-sensing/summary", headers=auth(admin_token))).json()
    dist = (await client.get(
        "/api/remote-sensing/index-distribution?index=ndvi&bins=20", headers=auth(admin_token)
    )).json()
    assert dist["column"] == "ndvi"
    assert sum(b["count"] for b in dist["bins"]) == summary["cell_count"]


async def test_viewer_can_read_remote_sensing(client, viewer_token):
    """0011 grants the read permission to every role that already reads the
    other five projects -- a role left out would find the project missing from
    its catalogue with no error to explain why."""
    resp = await client.get("/api/remote-sensing/summary", headers=auth(viewer_token))
    assert resp.status_code == 200

    caps = (await client.get("/api/tiles/capabilities", headers=auth(viewer_token))).json()
    assert "remote_sensing" in {p["key"] for p in caps["projects"]}
