"""Password hashing and JWT issuing/decoding."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ACCESS = "access"
REFRESH = "refresh"


def hash_password(password: str) -> str:
    # bcrypt silently truncates past 72 bytes; reject rather than surprise the caller
    if len(password.encode()) > 72:
        raise ValueError("password must be at most 72 bytes")
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except ValueError:
        return False


def create_access_token(
    *, subject: str, permissions: list[str], roles: list[str]
) -> tuple[str, int]:
    """Returns (token, expires_in_seconds).

    Permissions are embedded in the token so the common path (tile requests,
    which are high-frequency) needs no database round-trip to authorise.
    The trade-off is that a permission revocation only takes effect after the
    access token expires -- hence the deliberately short default lifetime.
    """
    expires_in = settings.access_token_expire_minutes * 60
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": ACCESS,
        "perms": permissions,
        "roles": roles,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm), expires_in


def create_refresh_token(*, subject: str) -> tuple[str, str, datetime]:
    """Returns (raw_token, sha256_hash, expires_at).

    Only the hash is persisted, so a dump of auth.refresh_tokens is not
    directly replayable.
    """
    raw = secrets.token_urlsafe(48)
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_expire_days)
    return raw, hash_refresh_token(raw), expires_at


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def decode_token(token: str) -> dict:
    """Raises JWTError on invalid signature, malformed token or expiry."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


__all__ = [
    "ACCESS",
    "REFRESH",
    "JWTError",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "hash_refresh_token",
    "verify_password",
]
