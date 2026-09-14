"""Unit tests for the commercial layer.

Deliberately database-free, unlike test_api.py: everything that decides whether
a customer is charged, throttled or cut off is pure arithmetic over in-memory
state, and it should be testable on a machine with no Postgres. The parts that
do need SQL -- the usage upsert, the key-resolution join -- are exercised by
the integration suite.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key")

from app.services import billing, payments  # noqa: E402

# --- key material -----------------------------------------------------------


def test_generated_keys_are_unique_and_prefixed():
    raw_a, prefix_a, hash_a = billing.generate_api_key()
    raw_b, prefix_b, hash_b = billing.generate_api_key()

    assert raw_a.startswith("gpk_")
    assert billing.looks_like_api_key(raw_a)
    assert raw_a != raw_b and prefix_a != prefix_b and hash_a != hash_b
    # The prefix is in the raw key so a user can match a listed key to a stored one.
    assert prefix_a in raw_a


def test_hash_is_stable_and_not_the_key():
    raw, _prefix, digest = billing.generate_api_key()
    assert billing.hash_api_key(raw) == digest
    assert digest != raw
    assert len(digest) == 64
    # Surrounding whitespace from a copy-paste must not change the identity.
    assert billing.hash_api_key(f"  {raw}\n") == digest


def test_mask_never_leaks_the_secret_half():
    raw, prefix, _ = billing.generate_api_key()
    masked = billing.mask_key(prefix)
    secret_half = raw.rsplit("_", 1)[-1]
    assert secret_half not in masked
    assert prefix in masked


def test_key_environment_reads_as_live_or_test():
    """A customer must be able to tell production from staging at a glance."""
    raw_live, prefix, _ = billing.generate_api_key("production")
    raw_test, _, _ = billing.generate_api_key("development")
    assert raw_live.startswith("gpk_live_")
    assert raw_test.startswith("gpk_test_")
    assert billing.mask_key(prefix, "production").startswith("gpk_live_")


def test_a_jwt_is_not_mistaken_for_an_api_key():
    jwt_ish = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxIn0.signature"
    assert not billing.looks_like_api_key(jwt_ish)
    assert not billing.looks_like_api_key("")


# --- rate limiting ----------------------------------------------------------


def test_bucket_allows_a_full_minute_of_burst_then_throttles():
    limiter = billing.TokenBucketLimiter()
    key = "burst"
    for _ in range(60):
        limiter.check(key, 60)
    with pytest.raises(billing.RateLimited) as excinfo:
        limiter.check(key, 60)
    assert excinfo.value.limit_per_minute == 60
    assert excinfo.value.retry_after >= 1


def test_bucket_refills_over_time():
    limiter = billing.TokenBucketLimiter()
    key = "refill"
    # Drain it, then rewind the bucket's clock by two seconds. At 60/minute
    # that is two tokens back.
    for _ in range(60):
        limiter.check(key, 60)
    limiter._buckets[key].updated -= 2.0
    limiter.check(key, 60)
    limiter.check(key, 60)
    with pytest.raises(billing.RateLimited):
        limiter.check(key, 60)


def test_buckets_are_per_key():
    limiter = billing.TokenBucketLimiter()
    for _ in range(10):
        limiter.check("a", 10)
    with pytest.raises(billing.RateLimited):
        limiter.check("a", 10)
    limiter.check("b", 10)  # a different key is unaffected


def test_a_zero_limit_means_unlimited_not_blocked():
    """An enterprise row with no configured rate must not lock itself out."""
    limiter = billing.TokenBucketLimiter()
    for _ in range(1000):
        limiter.check("unmetered", 0)


def test_limiter_evicts_rather_than_growing_without_bound():
    limiter = billing.TokenBucketLimiter(max_entries=8)
    for i in range(50):
        limiter.check(f"key-{i}", 60)
    assert len(limiter._buckets) <= 8


# --- entitlements -----------------------------------------------------------


def _entitlement(tile_quota=None, analytics_quota=None, status="active") -> billing.Entitlement:
    return billing.Entitlement(
        plan_code="test",
        plan_name="Test",
        permissions=frozenset({"agriculture:read"}),
        rate_limit_per_minute=60,
        quotas={"tile_quota": tile_quota, "analytics_quota": analytics_quota},
        status=status,
    )


def test_quota_lookup_maps_metrics_to_plan_columns():
    ent = _entitlement(tile_quota=100, analytics_quota=7)
    assert ent.quota_for(billing.TILE) == 100
    assert ent.quota_for(billing.ANALYTICS) == 7
    # Export is priced out of the analytics allowance rather than its own.
    assert ent.quota_for(billing.EXPORT) == 7
    assert ent.quota_for("something_unmetered") is None


def test_unmetered_plan_has_no_quota():
    assert _entitlement().quota_for(billing.TILE) is None


def test_past_due_serves_traffic_inside_the_grace_window():
    recent = datetime.now(UTC) - timedelta(days=1)
    assert billing._status_entitles("past_due", recent)


def test_past_due_stops_serving_once_the_grace_expires():
    stale = datetime.now(UTC) - timedelta(days=365)
    assert not billing._status_entitles("past_due", stale)


def test_canceled_never_entitles():
    assert not billing._status_entitles("canceled", datetime.now(UTC))
    assert billing._status_entitles("trialing", None)
    assert billing._status_entitles("active", None)


# --- usage metering ---------------------------------------------------------


def test_recorder_collapses_repeat_calls_into_one_bucket():
    recorder = billing.UsageRecorder()
    user, key = uuid.uuid4(), uuid.uuid4()
    for _ in range(250):
        recorder.record(user, billing.TILE, api_key_id=key)

    assert len(recorder.buffer) == 1, "250 tile requests must not be 250 rows"
    assert sum(recorder.buffer.values()) == 250


def test_recorder_separates_metrics_keys_and_days():
    recorder = billing.UsageRecorder()
    user = uuid.uuid4()
    key_a, key_b = uuid.uuid4(), uuid.uuid4()
    today = datetime.now(UTC).date()

    recorder.record(user, billing.TILE, api_key_id=key_a)
    recorder.record(user, billing.ANALYTICS, api_key_id=key_a)
    recorder.record(user, billing.TILE, api_key_id=key_b)
    recorder.record(user, billing.TILE, api_key_id=key_a, day=today - timedelta(days=1))

    assert len(recorder.buffer) == 4


def test_flush_is_due_on_size_before_the_interval_elapses():
    recorder = billing.UsageRecorder()
    assert not recorder.due(), "an empty buffer is never worth a round-trip"

    recorder.record(uuid.uuid4(), billing.TILE)
    recorder.last_flush = time.monotonic()
    assert not recorder.due()

    for _ in range(1000):
        recorder.record(uuid.uuid4(), billing.TILE)
    assert recorder.due()


def test_flush_is_due_once_the_interval_elapses():
    recorder = billing.UsageRecorder()
    recorder.record(uuid.uuid4(), billing.TILE)
    recorder.last_flush = time.monotonic() - 10_000
    assert recorder.due()


# --- webhook signatures -----------------------------------------------------


def _sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    stamp = timestamp if timestamp is not None else int(time.time())
    digest = hmac.new(
        secret.encode(), f"{stamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return f"t={stamp},v1={digest}"


@pytest.fixture
def webhook_secret(monkeypatch):
    secret = "whsec_test_value"
    monkeypatch.setattr(payments.settings, "stripe_webhook_secret", secret)
    return secret


def test_valid_signature_returns_the_event(webhook_secret):
    body = json.dumps({"type": "checkout.session.completed"}).encode()
    event = payments.verify_webhook(body, _sign(body, webhook_secret))
    assert event["type"] == "checkout.session.completed"


def test_tampered_body_is_rejected(webhook_secret):
    body = json.dumps({"type": "checkout.session.completed", "plan": "free"}).encode()
    signature = _sign(body, webhook_secret)
    forged = body.replace(b"free", b"pro!")
    with pytest.raises(payments.PaymentsError):
        payments.verify_webhook(forged, signature)


def test_signature_from_another_secret_is_rejected(webhook_secret):
    body = b"{}"
    with pytest.raises(payments.PaymentsError):
        payments.verify_webhook(body, _sign(body, "whsec_someone_elses"))


def test_replayed_old_signature_is_rejected(webhook_secret):
    body = b"{}"
    stale = int(time.time()) - payments.SIGNATURE_TOLERANCE_SECONDS - 60
    with pytest.raises(payments.PaymentsError):
        payments.verify_webhook(body, _sign(body, webhook_secret, timestamp=stale))


def test_missing_or_malformed_header_is_rejected(webhook_secret):
    with pytest.raises(payments.PaymentsError):
        payments.verify_webhook(b"{}", None)
    with pytest.raises(payments.PaymentsError):
        payments.verify_webhook(b"{}", "not-a-signature")


def test_unset_secret_refuses_rather_than_trusting(monkeypatch):
    """An unconfigured webhook endpoint must not be a free plan upgrade API."""
    monkeypatch.setattr(payments.settings, "stripe_webhook_secret", "")
    body = b"{}"
    with pytest.raises(payments.PaymentsNotConfigured):
        payments.verify_webhook(body, _sign(body, "anything"))


def test_checkout_refuses_without_credentials(monkeypatch):
    monkeypatch.setattr(payments.settings, "stripe_secret_key", "")
    assert not payments.configured()
    with pytest.raises(payments.PaymentsNotConfigured):
        payments._require_configured()


# --- the seeded price list --------------------------------------------------


def _plan_seed() -> list[tuple]:
    """Load PLANS straight out of the migration file.

    Importing it by path rather than duplicating the tiers here means these
    assertions fail if someone edits the migration into an inconsistent state,
    which is the only place the price list actually lives.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260101_0013-0013_billing_schema.py"
    )
    spec = importlib.util.spec_from_file_location("billing_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PLANS


def test_every_seeded_plan_grants_only_real_permission_codes():
    """A plan granting a code auth has never heard of would authorise nothing."""
    known = {
        "agriculture:read", "parcel:read", "demographics:read", "transport:read",
        "terrain:read", "remote_sensing:read", "agriculture:write", "parcel:write",
        "demographics:write", "transport:write", "terrain:write", "remote_sensing:write",
        "data:export", "analytics:read", "admin:users", "admin:roles", "admin:audit",
    }
    for plan in _plan_seed():
        code, permissions = plan[0], plan[8]
        unknown = set(permissions) - known
        assert not unknown, f"plan {code} grants unknown permission(s) {sorted(unknown)}"


def test_tiers_are_monotonic_in_price_quota_and_rate():
    """A tier that costs more must not give less, or the pricing page lies."""
    by_code = {plan[0]: plan for plan in _plan_seed()}
    free, starter, pro = by_code["free"], by_code["starter"], by_code["pro"]

    assert free[3] == 0 and starter[3] > free[3] and pro[3] > starter[3]
    for index in (4, 5):  # tile quota, analytics quota
        assert free[index] < starter[index] < pro[index]
    assert free[6] < starter[6] < pro[6]  # rate limit
    assert free[7] < starter[7] < pro[7]  # key allowance

    # Entitlements only ever widen going up the ladder.
    assert set(free[8]) < set(starter[8]) <= set(pro[8])
    assert "data:export" in pro[8] and "data:export" not in starter[8]


def test_enterprise_is_a_sales_conversation_not_a_free_tier():
    """A NULL price must mean 'contact us', never 'take it for nothing'."""
    enterprise = next(plan for plan in _plan_seed() if plan[0] == "enterprise")
    assert enterprise[3] is None
    assert enterprise[4] is None and enterprise[5] is None  # unmetered
    assert enterprise[10] is True  # still listed publicly


def test_default_plan_exists_in_the_seed():
    from app.core.config import settings

    assert settings.default_plan_code in {plan[0] for plan in _plan_seed()}


def test_no_public_plan_grants_administration():
    """Nothing on the price list may sell the admin screens."""
    for plan in _plan_seed():
        code, permissions, is_public = plan[0], plan[8], plan[10]
        if not is_public:
            continue
        sold_writes = [p for p in permissions if p.endswith(":write")]
        assert not sold_writes, f"plan {code} sells write access: {sold_writes}"
        assert "admin:users" not in permissions and "admin:roles" not in permissions
