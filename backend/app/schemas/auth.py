"""Pydantic request/response models for auth and admin endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    resource: str
    action: str
    description: str | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None = None
    is_system: bool
    permissions: list[PermissionOut] = []


class RoleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    full_name: str | None = None
    is_active: bool
    is_superuser: bool
    last_login_at: datetime | None = None
    created_at: datetime
    roles: list[RoleSummary] = []


class MeResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None = None
    is_active: bool
    is_superuser: bool
    roles: list[str]
    permissions: list[str]
    #: Projects this user may open, derived from permissions -- lets the
    #: frontend build its navigation without duplicating the RBAC rules.
    projects: list[str]


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    full_name: str | None = None
    is_active: bool = True
    role_names: list[str] = Field(default_factory=list)

    @field_validator("password")
    @classmethod
    def _bcrypt_length(cls, v: str) -> str:
        if len(v.encode()) > 72:
            raise ValueError("password must be at most 72 bytes")
        return v


class UserUpdate(BaseModel):
    full_name: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=72)


class RoleAssignment(BaseModel):
    role_names: list[str]


class RolePermissionUpdate(BaseModel):
    permission_codes: list[str]


class AuditEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: uuid.UUID | None
    action: str
    resource: str | None
    detail: dict | None
    created_at: datetime
