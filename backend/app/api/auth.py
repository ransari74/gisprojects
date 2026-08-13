"""Login, refresh, logout and identity endpoints."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_db_user
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_refresh_token,
    verify_password,
)
from app.models.auth import AuditLog, RefreshToken, User
from app.schemas.auth import (
    LoginRequest,
    MeResponse,
    RefreshRequest,
    TokenResponse,
)
from app.services.layers import PROJECTS

router = APIRouter(prefix="/auth", tags=["auth"])


def _permissions_for_token(user: User) -> list[str]:
    # Superusers get a wildcard rather than an enumerated list, so a permission
    # added later is picked up without re-issuing their token.
    return ["*"] if user.is_superuser else user.permission_codes


def _projects_for(permissions: set[str], is_superuser: bool) -> list[str]:
    return [
        name
        for name, meta in PROJECTS.items()
        if is_superuser or meta["permission"] in permissions
    ]


async def _issue_tokens(db: AsyncSession, user: User, user_agent: str | None) -> TokenResponse:
    access, expires_in = create_access_token(
        subject=str(user.id),
        permissions=_permissions_for_token(user),
        roles=user.role_names,
    )
    raw_refresh, token_hash, expires_at = create_refresh_token(subject=str(user.id))
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            user_agent=(user_agent or "")[:300] or None,
        )
    )
    return TokenResponse(access_token=access, refresh_token=raw_refresh, expires_in=expires_in)


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    email = payload.email.strip().lower()
    user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()

    # Identical response for "no such user" and "wrong password" so the endpoint
    # cannot be used to enumerate registered addresses.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account is disabled")

    tokens = await _issue_tokens(db, user, request.headers.get("user-agent"))
    await db.execute(
        update(User).where(User.id == user.id).values(last_login_at=datetime.now(UTC))
    )
    db.add(AuditLog(user_id=user.id, action="login", resource="auth"))
    await db.commit()
    return tokens


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    payload: RefreshRequest,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()

    if stored is None or stored.revoked_at is not None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid refresh token")
    if stored.expires_at <= datetime.now(UTC):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Refresh token has expired")

    user = (await db.execute(select(User).where(User.id == stored.user_id))).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "User account is disabled")

    # Rotate: the presented token is burned as the replacement is issued, so a
    # stolen refresh token is usable at most once before the theft shows up as
    # a failed refresh for the legitimate client.
    stored.revoked_at = datetime.now(UTC)
    tokens = await _issue_tokens(db, user, request.headers.get("user-agent"))
    await db.commit()
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    payload: RefreshRequest,
    current: Annotated[CurrentUser, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    token_hash = hash_refresh_token(payload.refresh_token)
    stored = (
        await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    ).scalar_one_or_none()
    # Only the owner may revoke, otherwise a leaked token value would let an
    # attacker log other sessions out.
    if stored is not None and stored.user_id == current.id and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        db.add(AuditLog(user_id=current.id, action="logout", resource="auth"))
        await db.commit()


@router.get("/me", response_model=MeResponse)
async def me(user: Annotated[User, Depends(get_db_user)]) -> MeResponse:
    perms = set(user.permission_codes)
    return MeResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superuser=user.is_superuser,
        roles=user.role_names,
        permissions=sorted(perms),
        projects=_projects_for(perms, user.is_superuser),
    )
