"""Alembic environment.

Runs migrations over the same async engine configuration the application uses,
so there is exactly one connection string and one place that knows how to talk
to a managed/serverless Postgres.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.core.db import Base

# Importing the models registers them on Base.metadata, which is what
# `alembic revision --autogenerate` diffs against.
import app.models.auth  # noqa: F401
import app.models.spatial  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Schemas this project owns. Without version_table_schema + include_schemas,
# autogenerate would either miss our tables or try to drop everything it finds
# in schemas it does not manage.
MANAGED_SCHEMAS = {"auth", "agri", "parcel", "demog", "transport", "terrain", "meta"}


# Expression and partial indexes have no declarative equivalent, so
# autogenerate cannot see them in the metadata and would propose dropping them
# on every run. They are created by hand in the migrations and excluded here.
HANDWRITTEN_INDEXES = {
    "users_email_lower_idx",     # UNIQUE on lower(email)
    "refresh_tokens_user_idx",   # partial: WHERE revoked_at IS NULL
    "audit_log_user_time_idx",   # (user_id, created_at DESC)
}


def include_object(object_, name, type_, reflected, compare_to):  # noqa: ARG001
    """Keep autogenerate inside the schemas this project owns.

    PostGIS installs its own tables (spatial_ref_sys) and views into the public
    schema; without this filter every autogenerate run would propose dropping
    them.
    """
    if type_ == "table":
        schema = getattr(object_, "schema", None)
        return schema in MANAGED_SCHEMAS
    if type_ == "index" and name in HANDWRITTEN_INDEXES:
        return False
    return True


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it -- `alembic upgrade head --sql`."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_object=include_object,
        version_table_schema=None,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
