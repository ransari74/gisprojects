"""Grant the remote-sensing permissions to the built-in roles

0009 seeded the permission catalogue as it stood at the time. Adding a project
therefore needs its own data migration rather than an edit to 0009: that
revision has already run on any deployed database, so amending it would leave
the catalogue silently short of the codes the new route guards reference.

The admin grant is re-run here for the same reason. 0009's CROSS JOIN gave
admin every permission that *existed when it ran* -- it is not a standing rule,
so a permission created afterwards has to be granted explicitly.

Revision ID: 0011
Revises: 0010
Create Date: 2026-01-01 00:11:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, resource, action, description)
PERMISSIONS: list[tuple[str, str, str, str]] = [
    (
        "remote_sensing:read",
        "remote_sensing",
        "read",
        "View satellite scenes, spectral indices, change detection and subsidence",
    ),
    (
        "remote_sensing:write",
        "remote_sensing",
        "write",
        "Create/update scene catalogue and analysis-grid records",
    ),
]

# Which existing roles gain the read permission, and why:
#   admin      -- holds everything by definition
#   analyst    -- reads every project
#   agronomist -- NDVI/land-cover change is the crop-monitoring half of the job
#   planner    -- urban heat and subsidence both bear directly on planning
#   viewer     -- read-only map access, same as the other five projects
READ_ROLES = ["admin", "analyst", "agronomist", "planner", "viewer"]

#: Only admin writes. Nothing else in the chain grants a `*:write` beyond the
#: role's own project, and remote sensing is nobody's owned project.
WRITE_ROLES = ["admin"]

INSERT_PERMISSION = sa.text(
    """
    INSERT INTO auth.permissions (code, resource, action, description)
    VALUES (:code, :resource, :action, :description)
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
    """
)

GRANT = sa.text(
    """
    INSERT INTO auth.role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM auth.roles r JOIN auth.permissions p ON p.code = :code
    WHERE r.name = ANY(:roles)
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

    conn.execute(GRANT, {"code": "remote_sensing:read", "roles": READ_ROLES})
    conn.execute(GRANT, {"code": "remote_sensing:write", "roles": WRITE_ROLES})


def downgrade() -> None:
    conn = op.get_bind()
    # role_permissions cascades from the permission delete.
    conn.execute(
        sa.text("DELETE FROM auth.permissions WHERE code = ANY(:codes)"),
        {"codes": [code for code, _, _, _ in PERMISSIONS]},
    )
