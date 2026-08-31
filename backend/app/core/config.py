"""Application settings, loaded from environment / .env."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- app -----------------------------------------------------------------
    app_name: str = "Geospatial Portfolio API"
    api_prefix: str = "/api"
    environment: str = "development"
    debug: bool = True

    # --- database ------------------------------------------------------------
    # Accepts the plain postgres:// URL that Neon/Supabase/Render hand out; the
    # validator rewrites it to the asyncpg driver form SQLAlchemy needs.
    database_url: str = "postgresql+asyncpg://gis:gis@localhost:5432/gisportfolio"
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_recycle: int = 300  # serverless Postgres drops idle connections
    db_echo: bool = False

    # --- auth ----------------------------------------------------------------
    secret_key: str = Field(default="dev-only-insecure-change-me-in-production")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 14

    # Demo accounts are created on startup. Turn OFF in any real deployment.
    seed_demo_users: bool = True
    demo_password: str = "demo1234"
    # A public shared deployment can't let anonymous visitors actually create/
    # delete/reassign real accounts and permissions -- but hiding the admin
    # role entirely would defeat the point of a demo that exists to show off
    # RBAC. This blocks only the five mutating admin endpoints; every read
    # (list users, roles, permissions, audit log, stats) stays live so the
    # model is still fully explorable. Off by default (local dev, docker-
    # compose); the Lambda deploy turns it on.
    demo_read_only: bool = False

    # --- cors ----------------------------------------------------------------
    cors_origins: str = "http://localhost:5173,http://localhost:3000,http://localhost:4173"

    # --- tiles ---------------------------------------------------------------
    tile_cache_seconds: int = 3600
    tile_buffer: int = 64          # MVT buffer in tile-extent units
    tile_extent: int = 4096
    max_tile_features: int = 20000
    tile_cache_max_entries: int = 512

    @field_validator("database_url")
    @classmethod
    def _normalise_driver(cls, v: str) -> str:
        if v.startswith("postgres://"):
            v = v.replace("postgres://", "postgresql://", 1)
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        # asyncpg configures TLS through connect_args, not the query string;
        # libpq-style sslmode in the URL raises TypeError on connect.
        if "sslmode=" in v:
            from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

            parts = urlsplit(v)
            kept = [(k, val) for k, val in parse_qsl(parts.query) if k != "sslmode"]
            v = urlunsplit(parts._replace(query=urlencode(kept)))
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
