"""Geospatial Portfolio API -- application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, ORJSONResponse
from sqlalchemy import text

from app.api import admin, auth, billing, features, meta, tiles
from app.api.projects import (
    agriculture,
    demographics,
    parcel,
    remote_sensing,
    terrain,
    transport,
)
from app.core.bootstrap import schema_ready, seed_demo_users
from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.services import billing as billing_service

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s -- %(message)s",
)
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with SessionLocal() as db:
            if await schema_ready(db):
                await seed_demo_users(db)
            else:
                log.warning(
                    "Database schema is not initialised. Run `alembic upgrade head` "
                    "(the api container's entrypoint does this automatically)."
                )
    except Exception as exc:  # noqa: BLE001 - never let startup diagnostics kill the app
        # A cold serverless Postgres can refuse the first connection; the app
        # should still come up and serve /health so the platform's health check
        # does not flap the container.
        log.warning("Startup database check failed (%s: %s)", type(exc).__name__, exc)
    yield

    # Metered usage buffers in memory; draining it on the way out is the
    # difference between a clean shutdown losing nothing and losing whatever
    # the last flush interval collected.
    try:
        async with SessionLocal() as db:
            drained = await billing_service.usage.flush(db)
            if drained:
                log.info("Flushed %d buffered usage rows on shutdown", drained)
    except Exception as exc:  # noqa: BLE001
        log.warning("Final usage flush failed (%s: %s)", type(exc).__name__, exc)

    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description=(
        "Six geospatial portfolio projects -- agriculture, cadastre, demographics, "
        "transport, 3D terrain and remote sensing -- served as MVT vector tiles from "
        "PostGIS with role-based access control.\n\n"
        "**Programmatic access.** Mint an API key under /api/billing/keys and send it "
        "as `X-API-Key`, as a bearer token, or as `?api_key=` where headers are "
        "impossible. A key authorises against the permissions its plan grants, is "
        "rate-limited per minute and metered per month; see /api/billing/plans for "
        "the price list."
    ),
    version="1.0.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Tile-Cache", "Content-Length"],
)
# Vector tiles are protobuf and compress well; GeoJSON responses even more so.
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.get("/health", tags=["meta"])
async def health() -> dict:
    """Liveness + database reachability, used by the platform health check."""
    db_ok, db_error = False, None
    try:
        async with SessionLocal() as db:
            await db.execute(text("SELECT 1"))
            db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_error = f"{type(exc).__name__}: {exc}"

    return {
        "status": "ok" if db_ok else "degraded",
        "environment": settings.environment,
        "database": "connected" if db_ok else "unavailable",
        "databaseError": db_error,
    }


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    # Service-layer validation (bad bbox, unknown measure) raises ValueError;
    # surfacing it as 400 keeps those checks out of every route body.
    return JSONResponse(status_code=400, content={"detail": str(exc)})


for router in (
    auth.router,
    admin.router,
    billing.router,
    meta.router,
    tiles.router,
    features.router,
    agriculture.router,
    parcel.router,
    demographics.router,
    transport.router,
    terrain.router,
    remote_sensing.router,
):
    app.include_router(router, prefix=settings.api_prefix)
