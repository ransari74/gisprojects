"""Extensions and schemas

Creates the PostGIS/pgcrypto extensions and the seven schemas the rest of the
chain populates. Split out from the table migrations because extensions need
elevated privileges: on a managed Postgres where the app role cannot create
extensions, this is the one revision a DBA has to run by hand.

Revision ID: 0001
Revises:
Create Date: 2026-01-01 00:00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("auth", "agri", "parcel", "demog", "transport", "terrain", "meta")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")   # gen_random_uuid()
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def downgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")

    # PostGIS is deliberately left installed. Dropping it would take
    # spatial_ref_sys and any other database object that depends on it, which
    # is well outside what "roll back this migration" should mean.
    op.execute("DROP EXTENSION IF EXISTS btree_gist")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
