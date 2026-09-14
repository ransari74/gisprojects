"""Entitlements, API keys, rate limiting and usage metering.

Everything commercial that is not a route handler lives here. The shape of the
problem is that the two hottest endpoints in the system -- tiles and feature
queries -- now have to answer three extra questions per request:

1. Who is this key, and what does its plan entitle it to?
2. Is it inside its per-minute rate limit?
3. Is it inside its monthly quota?

Answered naively that is three database round-trips on a path that was
deliberately built to need zero. So:

* **Key resolution is cached in-process** for ``api_key_cache_seconds``. One
  PostGIS query per key per minute, not per tile. The TTL is also the revocation
  lag, which is why it is short.
* **The rate limiter is a pure in-memory token bucket.** On a single instance
  that is exact; behind N instances each sees roughly 1/N of the traffic and the
  effective limit is the configured one, which is the right direction to be
  wrong in.
* **Usage counters buffer in memory and flush as upserts.** A tile request
  increments a dict entry; a background-ish flush (triggered by age or buffer
  size, on the request path, never blocking the response payload) folds them
  into ``billing.usage_daily``. Losing a few seconds of counters when an
  instance dies is an acceptable trade for not writing a row per tile.

Quota checks read a period SUM, cached for a minute per user. A caller can
therefore overshoot their quota by up to a minute of traffic; metering that is
exact to the request would cost a synchronous write per request, and nobody
prices an API that finely.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.billing import ApiKey, Plan, Subscription

# --- metric names -----------------------------------------------------------

TILE = "tile_request"
ANALYTICS = "analytics_request"
EXPORT = "export_request"

#: Which plan column caps which metric. Metrics absent from this map are
#: recorded for the invoice but never block a request.
QUOTA_COLUMN: dict[str, str] = {
    TILE: "tile_quota",
    ANALYTICS: "analytics_quota",
    EXPORT: "analytics_quota",
}

KEY_PREFIX = "gpk"


class QuotaExceeded(Exception):
    """Raised when a caller is over the metric's monthly allowance."""

    def __init__(self, metric: str, used: int, limit: int) -> None:
        self.metric = metric
        self.used = used
        self.limit = limit
        super().__init__(
            f"Monthly {metric.replace('_', ' ')} quota exhausted: {used:,} of {limit:,} used"
        )


class RateLimited(Exception):
    """Raised when a caller is over its plan's per-minute rate."""

    def __init__(self, limit_per_minute: int, retry_after: int) -> None:
        self.limit_per_minute = limit_per_minute
        self.retry_after = retry_after
        super().__init__(f"Rate limit of {limit_per_minute}/minute exceeded")


# --- key material -----------------------------------------------------------


def _env_token(environment: str | None = None) -> str:
    """`live` in production, `test` everywhere else.

    Two tokens rather than the environment name verbatim, because the point of
    putting it in the key is that a customer can tell at a glance which of
    their two keys is pointed at production -- and `gpk_deve_...` reads as a
    typo, not as an environment.
    """
    return "live" if (environment or settings.environment).lower().startswith("prod") else "test"


def generate_api_key(environment: str | None = None) -> tuple[str, str, str]:
    """Returns (raw_key, prefix, sha256_hash).

    The raw key is ``gpk_<env>_<prefix>_<secret>``. The prefix is stored in
    clear and shown back to the user so they can tell two keys apart in a list;
    only the digest of the whole key is persisted, so this table is not a
    credential store an attacker can replay.

    SHA-256 rather than bcrypt deliberately: the secret half is 32 bytes of
    ``secrets`` output, so there is no dictionary to attack, and bcrypt on the
    tile path would cost ~100ms per cache miss.
    """
    env = _env_token(environment)
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    raw = f"{KEY_PREFIX}_{env}_{prefix}_{secret}"
    return raw, prefix, hash_api_key(raw)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.strip().encode()).hexdigest()


def looks_like_api_key(value: str) -> bool:
    return value.strip().startswith(f"{KEY_PREFIX}_")


def mask_key(prefix: str, environment: str | None = None) -> str:
    return f"{KEY_PREFIX}_{_env_token(environment)}_{prefix}_{'*' * 8}"


# --- resolved caller --------------------------------------------------------


@dataclass(slots=True, frozen=True)
class Entitlement:
    """What a plan grants, flattened for the request path."""

    plan_code: str
    plan_name: str
    permissions: frozenset[str]
    rate_limit_per_minute: int
    quotas: dict[str, int | None]
    status: str

    def quota_for(self, metric: str) -> int | None:
        column = QUOTA_COLUMN.get(metric)
        return self.quotas.get(column) if column else None


@dataclass(slots=True, frozen=True)
class ResolvedKey:
    user_id: uuid.UUID
    key_id: uuid.UUID
    key_name: str
    entitlement: Entitlement


def entitlement_from(plan: Plan, status: str) -> Entitlement:
    return Entitlement(
        plan_code=plan.code,
        plan_name=plan.name,
        permissions=frozenset(plan.permissions or ()),
        rate_limit_per_minute=plan.rate_limit_per_minute,
        quotas={
            "tile_quota": plan.tile_quota,
            "analytics_quota": plan.analytics_quota,
        },
        status=status,
    )


class _TTLCache:
    """Small LRU+TTL map. Same shape as TileCache, different payload."""

    def __init__(self, max_entries: int, ttl_seconds: int) -> None:
        self._store: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._max = max_entries
        self._ttl = ttl_seconds

    def get(self, key: str) -> object | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        stored_at, payload = entry
        if time.monotonic() - stored_at > self._ttl:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return payload

    def set(self, key: str, payload: object) -> None:
        self._store[key] = (time.monotonic(), payload)
        self._store.move_to_end(key)
        while len(self._store) > self._max:
            self._store.popitem(last=False)

    def invalidate(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()

    def __len__(self) -> int:
        return len(self._store)


_key_cache = _TTLCache(settings.api_key_cache_max_entries, settings.api_key_cache_seconds)
_quota_cache = _TTLCache(settings.api_key_cache_max_entries, 60)

# One query, because the three facts a request needs -- key, subscription, plan
# -- are one join away from each other, and the tile path should not pay for
# three lazy loads.
RESOLVE_KEY_SQL = text(
    """
    SELECT k.id            AS key_id,
           k.user_id       AS user_id,
           k.name          AS key_name,
           k.revoked_at    AS revoked_at,
           u.is_active     AS user_active,
           s.status        AS status,
           s.current_period_end AS period_end,
           p.code          AS plan_code,
           p.name          AS plan_name,
           p.permissions   AS permissions,
           p.rate_limit_per_minute AS rate_limit,
           p.tile_quota    AS tile_quota,
           p.analytics_quota AS analytics_quota
    FROM billing.api_keys k
    JOIN auth.users u ON u.id = k.user_id
    LEFT JOIN billing.subscriptions s ON s.user_id = k.user_id
    LEFT JOIN billing.plans p ON p.code = COALESCE(s.plan_code, :default_plan)
    WHERE k.key_hash = :key_hash
    """
)


async def resolve_api_key(db: AsyncSession, raw_key: str) -> ResolvedKey | None:
    """Look up a raw key and flatten it to (user, entitlement).

    Returns None for an unknown, revoked or disabled key -- the caller turns
    that into a single 401 with no detail, so this endpoint cannot be used to
    tell "wrong key" apart from "revoked key".
    """
    digest = hash_api_key(raw_key)
    cached = _key_cache.get(digest)
    if cached is not None:
        return cached if isinstance(cached, ResolvedKey) else None

    row = (
        await db.execute(
            RESOLVE_KEY_SQL,
            {"key_hash": digest, "default_plan": settings.default_plan_code},
        )
    ).mappings().first()

    if row is None or row["revoked_at"] is not None or not row["user_active"]:
        # Negative results are cached too: an attacker spraying keys should not
        # get a free database query per attempt.
        _key_cache.set(digest, False)
        return None

    status = row["status"] or "active"
    if not _status_entitles(status, row["period_end"]):
        _key_cache.set(digest, False)
        return None

    if row["plan_code"] is None:
        # The configured default plan is missing from billing.plans, which is a
        # deployment error rather than a caller error. Fail closed.
        _key_cache.set(digest, False)
        return None

    resolved = ResolvedKey(
        user_id=row["user_id"],
        key_id=row["key_id"],
        key_name=row["key_name"],
        entitlement=Entitlement(
            plan_code=row["plan_code"],
            plan_name=row["plan_name"],
            permissions=frozenset(row["permissions"] or ()),
            rate_limit_per_minute=row["rate_limit"],
            quotas={
                "tile_quota": row["tile_quota"],
                "analytics_quota": row["analytics_quota"],
            },
            status=status,
        ),
    )
    _key_cache.set(digest, resolved)
    return resolved


def _status_entitles(status: str, period_end: datetime | None) -> bool:
    if status in ("trialing", "active"):
        return True
    if status == "past_due":
        # Dunning grace: keep serving for a few days after a failed payment.
        if period_end is None:
            return True
        deadline = period_end + timedelta(days=settings.past_due_grace_days)
        return datetime.now(UTC) <= deadline
    return False


def invalidate_key_cache(raw_or_hash: str | None = None) -> None:
    """Drop one key (by raw value or digest) or the whole cache."""
    if raw_or_hash is None:
        _key_cache.clear()
        return
    digest = raw_or_hash if len(raw_or_hash) == 64 and "_" not in raw_or_hash else hash_api_key(
        raw_or_hash
    )
    _key_cache.invalidate(digest)


# --- rate limiting ----------------------------------------------------------


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    """Per-key token bucket, refilled continuously at limit/60 per second.

    A burst of up to one minute's allowance is permitted, which is what makes a
    map client tolerable: MapLibre opens a dozen tile requests at once when the
    viewport moves, and a strict per-second limit would reject half of them.
    """

    def __init__(self, max_entries: int = 4096) -> None:
        self._buckets: OrderedDict[str, _Bucket] = OrderedDict()
        self._max = max_entries

    def check(self, key: str, limit_per_minute: int, cost: float = 1.0) -> None:
        if limit_per_minute <= 0:
            return
        now = time.monotonic()
        rate = limit_per_minute / 60.0
        bucket = self._buckets.get(key)
        if bucket is None:
            bucket = _Bucket(tokens=float(limit_per_minute), updated=now)
            self._buckets[key] = bucket
        else:
            bucket.tokens = min(
                float(limit_per_minute), bucket.tokens + (now - bucket.updated) * rate
            )
            bucket.updated = now

        self._buckets.move_to_end(key)
        while len(self._buckets) > self._max:
            self._buckets.popitem(last=False)

        if bucket.tokens < cost:
            deficit = cost - bucket.tokens
            raise RateLimited(limit_per_minute, retry_after=max(1, int(deficit / rate) + 1))
        bucket.tokens -= cost

    def clear(self) -> None:
        self._buckets.clear()


rate_limiter = TokenBucketLimiter()


# --- usage metering ---------------------------------------------------------

UPSERT_USAGE_SQL = text(
    """
    INSERT INTO billing.usage_daily (user_id, api_key_id, day, metric, quantity, updated_at)
    VALUES (:user_id, :api_key_id, :day, :metric, :quantity, now())
    ON CONFLICT (user_id, COALESCE(api_key_id, '00000000-0000-0000-0000-000000000000'::uuid), day, metric)
    DO UPDATE SET quantity = billing.usage_daily.quantity + EXCLUDED.quantity,
                  updated_at = now()
    """
)


TOUCH_KEYS_SQL = text(
    """
    UPDATE billing.api_keys SET last_used_at = now() WHERE id = ANY(:key_ids)
    """
)


@dataclass
class UsageRecorder:
    """Buffers counters in memory and folds them into the daily rollup.

    ``record`` is called on the request path and must stay allocation-cheap;
    ``maybe_flush`` is what actually touches the database, and only when the
    buffer is old enough or big enough to be worth a round-trip.
    """

    buffer: dict[tuple[uuid.UUID, uuid.UUID | None, date, str], int] = field(default_factory=dict)
    last_flush: float = field(default_factory=time.monotonic)
    flushed_rows: int = 0
    dropped_flushes: int = 0

    def record(
        self,
        user_id: uuid.UUID,
        metric: str,
        *,
        api_key_id: uuid.UUID | None = None,
        quantity: int = 1,
        day: date | None = None,
    ) -> None:
        bucket = (user_id, api_key_id, day or datetime.now(UTC).date(), metric)
        self.buffer[bucket] = self.buffer.get(bucket, 0) + quantity

    def due(self) -> bool:
        if not self.buffer:
            return False
        return (
            len(self.buffer) >= settings.usage_flush_max_buffered
            or time.monotonic() - self.last_flush >= settings.usage_flush_seconds
        )

    async def flush(self, db: AsyncSession) -> int:
        """Drain the buffer into billing.usage_daily. Returns rows written.

        The buffer is swapped out *before* the write so a concurrent request
        recording usage during the flush lands in the next batch rather than
        being counted twice or lost. On failure the batch is merged back in so
        a transient database blip costs latency, not revenue.
        """
        if not self.buffer:
            return 0
        batch, self.buffer = self.buffer, {}
        self.last_flush = time.monotonic()
        payload = [
            {
                "user_id": user_id,
                "api_key_id": key_id,
                "day": day,
                "metric": metric,
                "quantity": quantity,
            }
            for (user_id, key_id, day, metric), quantity in batch.items()
        ]
        key_ids = sorted({row["api_key_id"] for row in payload if row["api_key_id"]})
        try:
            await db.execute(UPSERT_USAGE_SQL, payload)
            # "Last used" rides along with the flush rather than being its own
            # write on the request path: a timestamp accurate to the flush
            # interval is all the account screen needs it to be.
            if key_ids:
                await db.execute(TOUCH_KEYS_SQL, {"key_ids": key_ids})
            await db.commit()
        except Exception:
            await db.rollback()
            self.dropped_flushes += 1
            for bucket, quantity in batch.items():
                self.buffer[bucket] = self.buffer.get(bucket, 0) + quantity
            raise
        self.flushed_rows += len(payload)
        _quota_cache.clear()
        return len(payload)

    async def maybe_flush(self, db: AsyncSession) -> int:
        if not self.due():
            return 0
        try:
            return await self.flush(db)
        except Exception:
            # Metering must never turn a served tile into a 500.
            return 0

    def stats(self) -> dict:
        return {
            "buffered": len(self.buffer),
            "flushedRows": self.flushed_rows,
            "failedFlushes": self.dropped_flushes,
        }


usage = UsageRecorder()


def period_start(now: datetime | None = None) -> date:
    """Quotas reset on the first of the calendar month.

    Anniversary-based periods are what a billing provider actually charges on,
    but a calendar month is what a customer can reason about without opening an
    invoice, and it makes the quota query a plain date range.
    """
    moment = now or datetime.now(UTC)
    return moment.date().replace(day=1)


PERIOD_USAGE_SQL = text(
    """
    SELECT metric, COALESCE(SUM(quantity), 0)::bigint AS used
    FROM billing.usage_daily
    WHERE user_id = :user_id AND day >= :since
    GROUP BY metric
    """
)


async def period_usage(db: AsyncSession, user_id: uuid.UUID) -> dict[str, int]:
    """Usage so far this billing period, by metric. Cached for a minute."""
    cache_key = f"usage:{user_id}"
    cached = _quota_cache.get(cache_key)
    if isinstance(cached, dict):
        return cached

    rows = (
        await db.execute(PERIOD_USAGE_SQL, {"user_id": user_id, "since": period_start()})
    ).mappings().all()
    totals = {row["metric"]: int(row["used"]) for row in rows}
    _quota_cache.set(cache_key, totals)
    return totals


async def check_quota(
    db: AsyncSession, user_id: uuid.UUID, entitlement: Entitlement, metric: str
) -> None:
    """Raise QuotaExceeded if this metric is exhausted for the period.

    Counts the in-memory buffer alongside the persisted total, so a caller
    cannot burst past the limit inside one flush window.
    """
    limit = entitlement.quota_for(metric)
    if limit is None:
        return
    persisted = (await period_usage(db, user_id)).get(metric, 0)
    buffered = sum(
        quantity
        for (buf_user, _key, _day, buf_metric), quantity in usage.buffer.items()
        if buf_user == user_id and buf_metric == metric
    )
    used = persisted + buffered
    if used >= limit:
        raise QuotaExceeded(metric, used, limit)


async def usage_summary(
    db: AsyncSession, user_id: uuid.UUID, entitlement: Entitlement
) -> dict:
    """Per-metric used/limit/remaining, for the account screen and invoices."""
    totals = await period_usage(db, user_id)
    out = {}
    for metric, column in (("tile_request", "tile_quota"), ("analytics_request", "analytics_quota")):
        limit = entitlement.quotas.get(column)
        used = totals.get(metric, 0)
        out[metric] = {
            "used": used,
            "limit": limit,
            "remaining": None if limit is None else max(0, limit - used),
            "percentUsed": None if limit in (None, 0) else round(100 * used / limit, 1),
        }
    out["export_request"] = {
        "used": totals.get("export_request", 0),
        "limit": None,
        "remaining": None,
        "percentUsed": None,
    }
    return {"periodStart": period_start().isoformat(), "metrics": out}


# --- subscriptions ----------------------------------------------------------


async def get_plan(db: AsyncSession, code: str) -> Plan | None:
    return (await db.execute(select(Plan).where(Plan.code == code))).scalar_one_or_none()


async def list_plans(db: AsyncSession, *, public_only: bool = True) -> list[Plan]:
    stmt = select(Plan).order_by(Plan.sort_order, Plan.code)
    if public_only:
        stmt = stmt.where(Plan.is_public.is_(True))
    return list((await db.execute(stmt)).scalars().all())


async def get_subscription(db: AsyncSession, user_id: uuid.UUID) -> Subscription | None:
    return (
        await db.execute(select(Subscription).where(Subscription.user_id == user_id))
    ).scalar_one_or_none()


async def ensure_subscription(db: AsyncSession, user_id: uuid.UUID) -> Subscription:
    """Return the user's subscription, creating a default-plan one if absent.

    Called lazily rather than at signup so an account that never touches the
    commercial API never gets a billing row.
    """
    existing = await get_subscription(db, user_id)
    if existing is not None:
        return existing
    sub = Subscription(
        user_id=user_id,
        plan_code=settings.default_plan_code,
        status="active",
        current_period_start=datetime.now(UTC),
        current_period_end=None,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


async def set_plan(
    db: AsyncSession,
    user_id: uuid.UUID,
    plan_code: str,
    *,
    status: str = "active",
    provider: str | None = None,
    provider_customer_id: str | None = None,
    provider_subscription_id: str | None = None,
    period_end: datetime | None = None,
) -> Subscription:
    sub = await ensure_subscription(db, user_id)
    sub.plan_code = plan_code
    sub.status = status
    sub.updated_at = datetime.now(UTC)
    if provider:
        sub.provider = provider
    if provider_customer_id:
        sub.provider_customer_id = provider_customer_id
    if provider_subscription_id:
        sub.provider_subscription_id = provider_subscription_id
    if period_end is not None:
        sub.current_period_end = period_end
    await db.commit()
    await db.refresh(sub)
    # Every cached key for this user was resolved against the old plan.
    invalidate_key_cache()
    return sub


async def entitlement_for_user(db: AsyncSession, user_id: uuid.UUID) -> Entitlement:
    """The entitlement a user holds through their subscription.

    Session-token callers keep their RBAC permissions; this is what the account
    screen shows them about the *purchased* side, and what meters their own
    dashboard traffic against the same quotas an API key would face.
    """
    sub = await get_subscription(db, user_id)
    code = sub.plan_code if sub else settings.default_plan_code
    status = sub.status if sub else "active"
    plan = await get_plan(db, code)
    if plan is None:
        return Entitlement(
            plan_code=code,
            plan_name=code.title(),
            permissions=frozenset(),
            rate_limit_per_minute=60,
            quotas={"tile_quota": None, "analytics_quota": None},
            status=status,
        )
    return entitlement_from(plan, status)


def cache_stats() -> dict:
    return {
        "resolvedKeys": len(_key_cache),
        "quotaEntries": len(_quota_cache),
        **usage.stats(),
    }
