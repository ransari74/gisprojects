"""Auth + RBAC FastAPI dependencies.

Usage in a router:

    @router.get("/fields", dependencies=[Depends(require_permission("agriculture:read"))])

or, when the handler needs the caller identity:

    async def handler(user: CurrentUser = Depends(require_permission("parcel:write"))):

Two kinds of credential arrive here. A browser session presents a short-lived
JWT and authorises with no database round-trip. A paying integration presents
an API key (``X-API-Key``, or the same value as a bearer token), which resolves
through ``services.billing`` to the permission set its plan entitles it to --
cached in-process, so the tile path still costs at most one query a minute per
key. Downstream of this module the two are indistinguishable: every route asks
the same question, "does this caller hold ``parcel:read``?"
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.security import ACCESS, JWTError, decode_token
from app.models.auth import User
from app.services import billing

log = logging.getLogger("app.deps")

bearer_scheme = HTTPBearer(auto_error=False)
# auto_error=False: a request with neither credential must still reach the JWT
# path and fail there with the usual 401, not be rejected by the scheme.
api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)


@dataclass(slots=True)
class CurrentUser:
    """Identity resolved from the access token -- no DB hit on the hot path."""

    id: uuid.UUID
    permissions: frozenset[str] = field(default_factory=frozenset)
    roles: tuple[str, ...] = ()
    is_superuser: bool = False
    # Set only when the caller authenticated with an API key. Its presence is
    # what makes a request billable: the browser app's own traffic is not
    # metered, because the customer is paying for programmatic access, not for
    # looking at their own dashboard.
    api_key_id: uuid.UUID | None = None
    entitlement: billing.Entitlement | None = None

    @property
    def is_api_client(self) -> bool:
        return self.api_key_id is not None

    def has(self, code: str) -> bool:
        return self.is_superuser or code in self.permissions

    def has_any(self, *codes: str) -> bool:
        return self.is_superuser or any(c in self.permissions for c in codes)


def _credentials_error(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _decode(token: str) -> CurrentUser:
    try:
        payload = decode_token(token)
    except JWTError as exc:
        raise _credentials_error("Invalid or expired token") from exc

    if payload.get("type") != ACCESS:
        raise _credentials_error("Expected an access token")

    sub = payload.get("sub")
    if not sub:
        raise _credentials_error("Token is missing a subject")

    try:
        user_id = uuid.UUID(sub)
    except ValueError as exc:
        raise _credentials_error("Token subject is not a valid user id") from exc

    perms = frozenset(payload.get("perms") or [])
    return CurrentUser(
        id=user_id,
        permissions=perms,
        roles=tuple(payload.get("roles") or []),
        # "*" is minted only for is_superuser accounts at login time
        is_superuser="*" in perms,
    )


def _raw_api_key(request: Request, header_key: str | None) -> str | None:
    """Pull an API key out of whichever slot the client could use.

    Three, in order of preference: the dedicated header, an Authorization
    bearer whose value is a key rather than a JWT (curl users reach for
    `-H "Authorization: Bearer ..."` by reflex), and a query parameter for
    consumers that cannot set headers at all -- a native map SDK, a bare
    <img> raster preview. The query form is the weakest of the three because
    it lands in access logs, which is why it is last and documented as such.
    """
    if header_key and billing.looks_like_api_key(header_key):
        return header_key.strip()

    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()
        if billing.looks_like_api_key(candidate):
            return candidate

    query_key = request.query_params.get("api_key")
    if query_key and billing.looks_like_api_key(query_key):
        return query_key.strip()
    return None


async def _user_from_api_key(db: AsyncSession, raw_key: str) -> CurrentUser:
    try:
        resolved = await billing.resolve_api_key(db, raw_key)
    except Exception as exc:  # noqa: BLE001
        # A database that has not run the billing migration should not turn
        # every request into a 500; it should just have no API keys.
        log.warning("API key lookup failed (%s: %s)", type(exc).__name__, exc)
        resolved = None

    if resolved is None:
        raise _credentials_error("Invalid, revoked or unsubscribed API key")

    return CurrentUser(
        id=resolved.user_id,
        permissions=resolved.entitlement.permissions,
        roles=(f"plan:{resolved.entitlement.plan_code}",),
        is_superuser=False,
        api_key_id=resolved.key_id,
        entitlement=resolved.entitlement,
    )


async def get_current_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    header_key: Annotated[str | None, Depends(api_key_scheme)] = None,
) -> CurrentUser:
    raw_key = _raw_api_key(request, header_key)
    if raw_key is not None:
        return await _user_from_api_key(db, raw_key)
    if creds is None or not creds.credentials:
        raise _credentials_error("Not authenticated")
    return _decode(creds.credentials)


async def get_optional_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    header_key: Annotated[str | None, Depends(api_key_scheme)] = None,
) -> CurrentUser | None:
    raw_key = _raw_api_key(request, header_key)
    if raw_key is not None:
        try:
            return await _user_from_api_key(db, raw_key)
        except HTTPException:
            return None
    if creds is None or not creds.credentials:
        return None
    try:
        return _decode(creds.credentials)
    except HTTPException:
        return None


async def get_tile_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
    header_key: Annotated[str | None, Depends(api_key_scheme)] = None,
    access_token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> CurrentUser:
    """Tile requests are issued by MapLibre's internal fetcher.

    MapLibre can attach an Authorization header via `transformRequest`, and that
    is the path the frontend uses. The `?access_token=` query fallback exists
    because some tile consumers (native SDKs, a bare <img> for a raster preview)
    cannot set headers at all.

    API keys ride the same three slots -- `X-API-Key`, the bearer header, or
    `?api_key=` -- so a customer can point a raw MapLibre source straight at a
    tile URL with their key in the query string and it works.
    """
    raw_key = _raw_api_key(request, header_key)
    if raw_key is not None:
        return await _user_from_api_key(db, raw_key)
    if creds and creds.credentials:
        return _decode(creds.credentials)
    if access_token:
        return _decode(access_token)
    raise _credentials_error("Not authenticated")


async def get_db_user(
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Full ORM user -- use only where fresh DB state matters (admin screens)."""
    user = (await db.execute(select(User).where(User.id == current.id))).scalar_one_or_none()
    if user is None:
        raise _credentials_error("User no longer exists")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account is disabled")
    return user


def require_permission(
    *codes: str, require_all: bool = False, metric: str | None = billing.ANALYTICS
):
    """Dependency factory gating a route on permission codes.

    By default the caller needs ANY of the codes; pass require_all=True to
    demand every one of them.

    The default `metric` is what makes every project analytics endpoint billable
    without editing six routers: they all gate on this factory. Pass
    `metric=None` for routes that are not part of the metered product -- the
    admin screens, which no plan entitles anyone to anyway.
    """

    async def _guard(
        current: Annotated[CurrentUser, Depends(get_current_user)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> CurrentUser:
        ok = (
            current.is_superuser
            or (all(c in current.permissions for c in codes) if require_all
                else any(c in current.permissions for c in codes))
        )
        if not ok:
            joiner = " and " if require_all else " or "
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires permission: {joiner.join(codes)}",
            )
        if metric is not None:
            await enforce_billing(db, current, metric)
        return current

    return _guard


def require_tile_permission(*codes: str):
    """Same as require_permission but accepts the tile token fallback."""

    async def _guard(
        current: Annotated[CurrentUser, Depends(get_tile_user)],
    ) -> CurrentUser:
        if not current.has_any(*codes):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Requires permission: {' or '.join(codes)}"
            )
        return current

    return _guard


# --- metering ---------------------------------------------------------------


async def enforce_billing(
    db: AsyncSession, current: CurrentUser, metric: str
) -> None:
    """Rate-limit, quota-check and meter one billable request.

    Only API-key callers are billable. Everything the browser app does with a
    session token is the customer looking at their own dashboard, and charging
    for that would make the pricing page a lie.

    Order matters: the rate limit is checked before the quota because it is
    free to evaluate, and the usage is recorded before the handler runs rather
    than after. Metering on entry slightly over-counts (a request that 500s is
    still counted) but cannot under-count, and it keeps this a dependency
    instead of a response hook that would have to re-derive the caller.
    """
    if not settings.billing_enabled or not current.is_api_client:
        return

    entitlement = current.entitlement
    if entitlement is None:
        return

    try:
        billing.rate_limiter.check(str(current.api_key_id), entitlement.rate_limit_per_minute)
    except billing.RateLimited as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            str(exc),
            headers={
                "Retry-After": str(exc.retry_after),
                "X-RateLimit-Limit": str(exc.limit_per_minute),
            },
        ) from exc

    try:
        await billing.check_quota(db, current.id, entitlement, metric)
    except billing.QuotaExceeded as exc:
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            f"{exc} on the {entitlement.plan_name} plan. Upgrade at "
            f"{settings.public_site_url}/pricing to raise this limit.",
            headers={"X-Quota-Limit": str(exc.limit), "X-Quota-Used": str(exc.used)},
        ) from exc

    billing.usage.record(current.id, metric, api_key_id=current.api_key_id)
    await billing.usage.maybe_flush(db)


def metered(metric: str, *, tile: bool = False):
    """Dependency factory: authenticate, then meter the request.

    `tile=True` selects the tile resolver, which additionally accepts the
    `?access_token=` fallback.
    """
    resolver = get_tile_user if tile else get_current_user

    async def _meter(
        current: Annotated[CurrentUser, Depends(resolver)],
        db: Annotated[AsyncSession, Depends(get_db)],
    ) -> CurrentUser:
        await enforce_billing(db, current, metric)
        return current

    return _meter


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
