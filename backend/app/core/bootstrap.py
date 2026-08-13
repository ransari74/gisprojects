"""Startup tasks: verify the schema is present and seed demo accounts.

Kept separate from the migrations on purpose. Alembic owns the schema and the
permission catalogue; this module owns only the rows that need application-side
work -- demo users, whose passwords must be bcrypt-hashed by the app.
"""

import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.models.auth import Role, User

log = logging.getLogger("bootstrap")

DEMO_USERS: list[tuple[str, str, list[str], bool]] = [
    # (email, full name, roles, is_superuser)
    ("admin@geo.dev", "Ada Admin", ["admin"], True),
    ("analyst@geo.dev", "Nils Analyst", ["analyst"], False),
    ("agronomist@geo.dev", "Rita Agronomist", ["agronomist"], False),
    ("planner@geo.dev", "Pia Planner", ["planner"], False),
    ("viewer@geo.dev", "Vic Viewer", ["viewer"], False),
]


async def schema_ready(db: AsyncSession) -> bool:
    result = await db.execute(
        text(
            "SELECT to_regclass('auth.users') IS NOT NULL"
            " AND to_regclass('agri.fields') IS NOT NULL"
        )
    )
    return bool(result.scalar_one())


async def seed_demo_users(db: AsyncSession) -> int:
    """Create the five demo accounts if they are missing. Returns count created."""
    if not settings.seed_demo_users:
        return 0

    roles = {r.name: r for r in (await db.execute(select(Role))).scalars()}
    if not roles:
        log.warning("No roles found -- run `alembic upgrade head` before seeding users")
        return 0

    created = 0
    for email, full_name, role_names, is_superuser in DEMO_USERS:
        exists = (await db.execute(select(User.id).where(User.email == email))).first()
        if exists:
            continue
        user = User(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(settings.demo_password),
            is_active=True,
            is_superuser=is_superuser,
        )
        user.roles = [roles[n] for n in role_names if n in roles]
        db.add(user)
        created += 1

    if created:
        await db.commit()
        log.info("Seeded %d demo users (password: %s)", created, settings.demo_password)
    return created
