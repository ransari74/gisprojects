"""Auth + RBAC FastAPI dependencies.

Usage in a router:

    @router.get("/fields", dependencies=[Depends(require_permission("agriculture:read"))])

or, when the handler needs the caller identity:

    async def handler(user: CurrentUser = Depends(require_permission("parcel:write"))):
"""

import uuid
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import ACCESS, JWTError, decode_token
from app.models.auth import User

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class CurrentUser:
    """Identity resolved from the access token -- no DB hit on the hot path."""

    id: uuid.UUID
    permissions: frozenset[str] = field(default_factory=frozenset)
    roles: tuple[str, ...] = ()
    is_superuser: bool = False

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


async def get_current_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser:
    if creds is None or not creds.credentials:
        raise _credentials_error("Not authenticated")
    return _decode(creds.credentials)


async def get_optional_user(
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> CurrentUser | None:
    if creds is None or not creds.credentials:
        return None
    try:
        return _decode(creds.credentials)
    except HTTPException:
        return None


async def get_tile_user(
    request: Request,
    creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    access_token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> CurrentUser:
    """Tile requests are issued by MapLibre's internal fetcher.

    MapLibre can attach an Authorization header via `transformRequest`, and that
    is the path the frontend uses. The `?access_token=` query fallback exists
    because some tile consumers (native SDKs, a bare <img> for a raster preview)
    cannot set headers at all.
    """
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


def require_permission(*codes: str, require_all: bool = False):
    """Dependency factory gating a route on permission codes.

    By default the caller needs ANY of the codes; pass require_all=True to
    demand every one of them.
    """

    async def _guard(
        current: Annotated[CurrentUser, Depends(get_current_user)],
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


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
