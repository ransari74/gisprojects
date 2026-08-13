"""Checks against the migrated database.

Complements test_migration_files.py, which checks the revision files
themselves. These assert that what Alembic actually built matches what the
application expects -- indexes, SRIDs, seeded RBAC rows and the layer registry.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

os.environ.setdefault(
    "DATABASE_URL",
    os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://gis:gis@localhost:5432/gisportfolio"),
)
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.core.db import SessionLocal  # noqa: E402

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

pytestmark = pytest.mark.asyncio(loop_scope="session")


# Applied-schema checks
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture(loop_scope="session", scope="session", autouse=True)
async def require_database():
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"No database available: {type(exc).__name__}: {exc}", allow_module_level=True)


async def test_database_is_at_head():
    """The running database must be at the latest revision."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(VERSIONS_DIR.parent))
    expected = ScriptDirectory.from_config(config).get_current_head()

    async with SessionLocal() as db:
        applied = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
    assert applied == expected, f"database is at {applied}, head is {expected}"


async def test_every_geometry_column_has_a_gist_index():
    """The tile query is only fast because of these; a missing one is a silent
    performance cliff rather than an error, so assert them explicitly."""
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT c.table_schema, c.table_name
                    FROM information_schema.columns c
                    WHERE c.column_name = 'geom'
                      AND c.table_schema IN
                          ('agri', 'parcel', 'demog', 'transport', 'terrain', 'meta')
                      AND NOT EXISTS (
                          SELECT 1
                          FROM pg_index i
                          JOIN pg_class ic  ON ic.oid = i.indexrelid
                          JOIN pg_class tc  ON tc.oid = i.indrelid
                          JOIN pg_namespace n ON n.oid = tc.relnamespace
                          JOIN pg_am am     ON am.oid = ic.relam
                          WHERE n.nspname = c.table_schema
                            AND tc.relname = c.table_name
                            AND am.amname = 'gist'
                      )
                    """
                )
            )
        ).all()
    assert not rows, f"geometry columns without a GiST index: {rows}"


async def test_all_geometries_are_srid_4326():
    """Mixed SRIDs would make ST_AsMVTGeom silently mis-project a layer."""
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT f_table_schema, f_table_name, srid
                    FROM geometry_columns
                    WHERE f_table_schema IN
                          ('agri', 'parcel', 'demog', 'transport', 'terrain', 'meta')
                      AND srid <> 4326
                    """
                )
            )
        ).all()
    assert not rows, f"geometry columns not in EPSG:4326: {rows}"


async def test_seeded_roles_and_permissions_are_present():
    async with SessionLocal() as db:
        roles = {
            r[0]
            for r in (await db.execute(text("SELECT name FROM auth.roles"))).all()
        }
        perm_count = (
            await db.execute(text("SELECT count(*) FROM auth.permissions"))
        ).scalar_one()
        admin_perms = (
            await db.execute(
                text(
                    """
                    SELECT count(*) FROM auth.role_permissions rp
                    JOIN auth.roles r ON r.id = rp.role_id
                    WHERE r.name = 'admin'
                    """
                )
            )
        ).scalar_one()

    assert {"admin", "analyst", "agronomist", "planner", "viewer"} <= roles
    assert perm_count == 15
    # The admin role's grant is a CROSS JOIN, so it must cover every permission.
    assert admin_perms == perm_count


async def test_every_registered_layer_maps_to_a_real_table():
    """The layer registry interpolates schema/table names into SQL. If one
    stopped matching the migrated schema, tiles would 500 at request time."""
    from app.services.layers import ALL_LAYERS

    async with SessionLocal() as db:
        for layer in ALL_LAYERS:
            exists = (
                await db.execute(
                    text("SELECT to_regclass(:qualified) IS NOT NULL"),
                    {"qualified": layer.qualified_table},
                )
            ).scalar_one()
            assert exists, f"layer {layer.name} points at missing table {layer.qualified_table}"

            columns = {
                r[0]
                for r in (
                    await db.execute(
                        text(
                            """
                            SELECT column_name FROM information_schema.columns
                            WHERE table_schema = :schema AND table_name = :table
                            """
                        ),
                        {"schema": layer.schema, "table": layer.table},
                    )
                ).all()
            }
            missing = set(layer.columns) - columns
            assert not missing, f"layer {layer.name} selects missing columns: {sorted(missing)}"
            assert layer.geom_column in columns
            assert layer.id_column in columns
