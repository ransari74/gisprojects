"""Seed the permission catalogue and the built-in roles

A data migration rather than a fixture script: the permission codes are part of
the schema contract (the API's route guards reference them by name), so they
belong in the migration chain where they are versioned and reviewable.

Demo *users* are not seeded here -- they need bcrypt hashes, which is
application logic. See app/core/bootstrap.py.

Revision ID: 0009
Revises: 0008
Create Date: 2026-01-01 00:09:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, resource, action, description)
PERMISSIONS: list[tuple[str, str, str, str]] = [
    # per-project read
    ("agriculture:read", "agriculture", "read", "View agriculture layers, tiles and analytics"),
    ("parcel:read", "parcel", "read", "View cadastral parcels and zoning"),
    ("demographics:read", "demographics", "read", "View census tracts and population data"),
    ("transport:read", "transport", "read", "View road network, transit and isochrones"),
    ("terrain:read", "terrain", "read", "View 3D buildings, contours and terrain"),
    # per-project write
    ("agriculture:write", "agriculture", "write", "Create/update field records"),
    ("parcel:write", "parcel", "write", "Create/update parcel records"),
    ("demographics:write", "demographics", "write", "Create/update census records"),
    ("transport:write", "transport", "write", "Create/update network records"),
    ("terrain:write", "terrain", "write", "Create/update building records"),
    # cross-cutting
    ("data:export", "data", "export", "Export query results as GeoJSON/CSV"),
    ("analytics:read", "analytics", "read", "Access aggregate analytics endpoints"),
    ("admin:users", "admin", "users", "Create, edit and deactivate users"),
    ("admin:roles", "admin", "roles", "Assign roles and edit role permissions"),
    ("admin:audit", "admin", "audit", "Read the audit log"),
]

# (name, description, permission codes | None = every permission)
ROLES: list[tuple[str, str, list[str] | None]] = [
    ("admin", "Full access to every project plus user and role administration", None),
    (
        "analyst",
        "Read access to all five projects, analytics and data export",
        [
            "agriculture:read", "parcel:read", "demographics:read", "transport:read",
            "terrain:read", "analytics:read", "data:export",
        ],
    ),
    (
        "agronomist",
        "Agriculture read/write; read-only elsewhere for context",
        [
            "agriculture:read", "agriculture:write", "terrain:read",
            "demographics:read", "analytics:read", "data:export",
        ],
    ),
    (
        "planner",
        "Parcel and transport read/write; reads demographics + terrain",
        [
            "parcel:read", "parcel:write", "transport:read", "transport:write",
            "demographics:read", "terrain:read", "analytics:read", "data:export",
        ],
    ),
    (
        "viewer",
        "Read-only access to map layers, no export, no analytics detail",
        ["agriculture:read", "parcel:read", "demographics:read", "transport:read", "terrain:read"],
    ),
]


# Statements use SQLAlchemy named parameters rather than the driver's own
# paramstyle: this chain runs over asyncpg, which uses $1 placeholders, and
# letting SQLAlchemy do the translation keeps the migration driver-agnostic.
INSERT_PERMISSION = sa.text(
    """
    INSERT INTO auth.permissions (code, resource, action, description)
    VALUES (:code, :resource, :action, :description)
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
    """
)

INSERT_ROLE = sa.text(
    """
    INSERT INTO auth.roles (name, description, is_system)
    VALUES (:name, :description, TRUE)
    ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description
    """
)

GRANT_ALL_PERMISSIONS = sa.text(
    """
    INSERT INTO auth.role_permissions (role_id, permission_id)
    SELECT r.id, p.id FROM auth.roles r CROSS JOIN auth.permissions p
    WHERE r.name = :name
    ON CONFLICT DO NOTHING
    """
)

GRANT_LISTED_PERMISSIONS = sa.text(
    """
    INSERT INTO auth.role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM auth.roles r JOIN auth.permissions p ON p.code = ANY(:codes)
    WHERE r.name = :name
    ON CONFLICT DO NOTHING
    """
)


def upgrade() -> None:
    conn = op.get_bind()

    for code, resource, action, description in PERMISSIONS:
        conn.execute(
            INSERT_PERMISSION,
            {"code": code, "resource": resource, "action": action, "description": description},
        )

    for name, description, codes in ROLES:
        conn.execute(INSERT_ROLE, {"name": name, "description": description})

        if codes is None:
            # admin holds every permission, including any a later migration
            # adds -- hence the CROSS JOIN rather than an enumerated list.
            conn.execute(GRANT_ALL_PERMISSIONS, {"name": name})
        else:
            conn.execute(GRANT_LISTED_PERMISSIONS, {"name": name, "codes": codes})


def downgrade() -> None:
    conn = op.get_bind()
    # role_permissions and user_roles cascade from these deletes.
    conn.execute(
        sa.text("DELETE FROM auth.roles WHERE name = ANY(:names)"),
        {"names": [name for name, _, _ in ROLES]},
    )
    conn.execute(
        sa.text("DELETE FROM auth.permissions WHERE code = ANY(:codes)"),
        {"codes": [code for code, _, _, _ in PERMISSIONS]},
    )
