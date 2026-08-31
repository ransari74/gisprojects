"""User and role administration -- gated on admin:* permissions."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import CurrentUser, require_permission
from app.core.security import hash_password
from app.models.auth import AuditLog, Permission, RefreshToken, Role, RolePermission, User, UserRole
from app.schemas.auth import (
    AuditEntry,
    PermissionOut,
    RoleAssignment,
    RoleOut,
    RolePermissionUpdate,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(prefix="/admin", tags=["admin"])

AdminUsers = Annotated[CurrentUser, Depends(require_permission("admin:users"))]
AdminRoles = Annotated[CurrentUser, Depends(require_permission("admin:roles"))]
Db = Annotated[AsyncSession, Depends(get_db)]


def _block_if_demo_read_only() -> None:
    if settings.demo_read_only:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This is a public demo deployment -- admin write actions are disabled here. "
            "Clone the repo and run it locally (see the README) to try user/role administration.",
        )


async def _resolve_roles(db: AsyncSession, names: list[str]) -> list[Role]:
    if not names:
        return []
    roles = list((await db.execute(select(Role).where(Role.name.in_(names)))).scalars())
    missing = set(names) - {r.name for r in roles}
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown roles: {sorted(missing)}")
    return roles


@router.get("/users", response_model=list[UserOut])
async def list_users(
    _: AdminUsers,
    db: Db,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[User]:
    result = await db.execute(select(User).order_by(User.created_at).limit(limit).offset(offset))
    return list(result.scalars())


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, admin: AdminUsers, db: Db) -> User:
    _block_if_demo_read_only()
    email = payload.email.strip().lower()
    exists = (await db.execute(select(User.id).where(User.email == email))).first()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with that email already exists")

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_active=payload.is_active,
    )
    user.roles = await _resolve_roles(db, payload.role_names)
    db.add(user)
    await db.flush()
    db.add(
        AuditLog(
            user_id=admin.id,
            action="user.create",
            resource=f"user:{user.id}",
            detail={"email": email, "roles": payload.role_names},
        )
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: uuid.UUID, _: AdminUsers, db: Db) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: uuid.UUID, payload: UserUpdate, admin: AdminUsers, db: Db) -> User:
    _block_if_demo_read_only()
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    changed: dict = {}
    if payload.full_name is not None:
        user.full_name = payload.full_name
        changed["full_name"] = payload.full_name
    if payload.is_active is not None:
        if user.id == admin.id and not payload.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate your own account")
        user.is_active = payload.is_active
        changed["is_active"] = payload.is_active
    if payload.password:
        user.hashed_password = hash_password(payload.password)
        changed["password"] = "changed"
        # A password change must not leave old sessions alive.
        await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))

    db.add(
        AuditLog(user_id=admin.id, action="user.update", resource=f"user:{user_id}", detail=changed)
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: uuid.UUID, admin: AdminUsers, db: Db) -> None:
    _block_if_demo_read_only()
    if user_id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete your own account")
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    await db.delete(user)
    db.add(AuditLog(user_id=admin.id, action="user.delete", resource=f"user:{user_id}"))
    await db.commit()


@router.put("/users/{user_id}/roles", response_model=UserOut)
async def set_user_roles(
    user_id: uuid.UUID, payload: RoleAssignment, admin: AdminRoles, db: Db
) -> User:
    _block_if_demo_read_only()
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    user.roles = await _resolve_roles(db, payload.role_names)
    db.add(
        AuditLog(
            user_id=admin.id,
            action="user.roles.set",
            resource=f"user:{user_id}",
            detail={"roles": payload.role_names},
        )
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(_: AdminRoles, db: Db) -> list[Role]:
    return list((await db.execute(select(Role).order_by(Role.name))).scalars())


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(_: AdminRoles, db: Db) -> list[Permission]:
    return list(
        (await db.execute(select(Permission).order_by(Permission.resource, Permission.action))).scalars()
    )


@router.put("/roles/{role_id}/permissions", response_model=RoleOut)
async def set_role_permissions(
    role_id: int, payload: RolePermissionUpdate, admin: AdminRoles, db: Db
) -> Role:
    _block_if_demo_read_only()
    role = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.name == "admin":
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "The admin role always holds every permission and cannot be narrowed",
        )

    perms = list(
        (await db.execute(select(Permission).where(Permission.code.in_(payload.permission_codes)))).scalars()
    )
    missing = set(payload.permission_codes) - {p.code for p in perms}
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown permissions: {sorted(missing)}")

    await db.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
    for perm in perms:
        db.add(RolePermission(role_id=role_id, permission_id=perm.id))

    db.add(
        AuditLog(
            user_id=admin.id,
            action="role.permissions.set",
            resource=f"role:{role_id}",
            detail={"permissions": payload.permission_codes},
        )
    )
    await db.commit()

    refreshed = (await db.execute(select(Role).where(Role.id == role_id))).scalar_one()
    await db.refresh(refreshed, ["permissions"])
    return refreshed


@router.get("/audit", response_model=list[AuditEntry])
async def read_audit_log(
    _: Annotated[CurrentUser, Depends(require_permission("admin:audit"))],
    db: Db,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AuditLog]:
    result = await db.execute(select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit))
    return list(result.scalars())


@router.get("/stats")
async def admin_stats(_: AdminUsers, db: Db) -> dict:
    users = (await db.execute(select(User))).scalars().all()
    role_counts: dict[str, int] = {}
    for u in users:
        for r in u.roles:
            role_counts[r.name] = role_counts.get(r.name, 0) + 1
    active_sessions = (
        await db.execute(select(RefreshToken).where(RefreshToken.revoked_at.is_(None)))
    ).scalars().all()
    return {
        "total_users": len(users),
        "active_users": sum(1 for u in users if u.is_active),
        "users_by_role": role_counts,
        "active_sessions": len(active_sessions),
    }
