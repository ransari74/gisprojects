"""Billing: plans, subscriptions, API keys and metered usage

The portfolio API becomes a product here. Three tables and one rollup:

* ``billing.plans``         -- what is for sale, and what each tier grants.
* ``billing.subscriptions`` -- which plan a user is on, and its billing period.
* ``billing.api_keys``      -- machine credentials, stored as SHA-256 digests.
* ``billing.usage_daily``   -- one row per (user, key, day, metric) counter.

Two decisions worth defending:

**Plan entitlements are permission codes, not a second access model.** A plan
row carries a ``permissions`` text[] of the same codes ``auth.permissions``
already defines, so the tile endpoint keeps asking one question -- "does this
caller hold ``parcel:read``?" -- whether the caller arrived with a session
token or an API key. Nothing in the request path learns what a plan is.

**Usage is a daily counter, not an event log.** Metering tile requests as rows
would put a write on the hottest path in the system for data nobody queries at
per-request resolution; every invoice and every quota check is a SUM over a
period. The unique index turns metering into one upsert per key per day per
metric, which the service layer batches behind an in-process buffer.

Revision ID: 0013
Revises: 0012
Create Date: 2026-01-01 00:13:00
"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "billing"

ALL_READ = [
    "agriculture:read",
    "parcel:read",
    "demographics:read",
    "transport:read",
    "terrain:read",
    "remote_sensing:read",
]

# (code, name, blurb, price_cents, tile_quota, analytics_quota, rate_limit,
#  max_keys, permissions, features, is_public, sort_order)
# A NULL quota means unlimited; a NULL price means "talk to us".
PLANS: list[tuple] = [
    (
        "free",
        "Free",
        "Evaluate the API against the live study area. No card, no expiry.",
        0,
        20_000,
        500,
        60,
        2,
        ["agriculture:read", "terrain:read", "analytics:read"],
        [
            "Agriculture and 3D terrain layers",
            "20,000 tile requests / month",
            "500 analytics calls / month",
            "2 API keys",
            "Community support",
        ],
        True,
        10,
    ),
    (
        "starter",
        "Starter",
        "All six projects, enough volume for an internal dashboard.",
        4900,
        250_000,
        10_000,
        300,
        5,
        [*ALL_READ, "analytics:read"],
        [
            "All six project layer sets",
            "250,000 tile requests / month",
            "10,000 analytics calls / month",
            "5 API keys",
            "Email support, 2 business days",
        ],
        True,
        20,
    ),
    (
        "pro",
        "Pro",
        "Production volume, bulk export and the headroom to embed it in a product.",
        19900,
        2_000_000,
        100_000,
        1200,
        25,
        [*ALL_READ, "analytics:read", "data:export"],
        [
            "Everything in Starter",
            "2,000,000 tile requests / month",
            "100,000 analytics calls / month",
            "GeoJSON + CSV bulk export",
            "25 API keys",
            "Email support, 1 business day",
        ],
        True,
        30,
    ),
    (
        "enterprise",
        "Enterprise",
        "Your own study area, your own SLA, invoiced annually.",
        None,
        None,
        None,
        6000,
        100,
        [*ALL_READ, "analytics:read", "data:export", "admin:audit"],
        [
            "Everything in Pro, unmetered",
            "A study area of your choosing, loaded from your data",
            "Single sign-on and audit-log export",
            "Contractual SLA and named support",
        ],
        True,
        40,
    ),
]

INSERT_PLAN = sa.text(
    """
    INSERT INTO billing.plans (
        code, name, blurb, price_cents, currency, billing_interval,
        tile_quota, analytics_quota, rate_limit_per_minute, max_api_keys,
        permissions, features, is_public, sort_order
    ) VALUES (
        :code, :name, :blurb, :price_cents, 'EUR', 'month',
        :tile_quota, :analytics_quota, :rate_limit, :max_keys,
        :permissions, CAST(:features AS jsonb), :is_public, :sort_order
    )
    ON CONFLICT (code) DO UPDATE SET
        name = EXCLUDED.name,
        blurb = EXCLUDED.blurb,
        price_cents = EXCLUDED.price_cents,
        tile_quota = EXCLUDED.tile_quota,
        analytics_quota = EXCLUDED.analytics_quota,
        rate_limit_per_minute = EXCLUDED.rate_limit_per_minute,
        max_api_keys = EXCLUDED.max_api_keys,
        permissions = EXCLUDED.permissions,
        features = EXCLUDED.features,
        is_public = EXCLUDED.is_public,
        sort_order = EXCLUDED.sort_order
    """
)


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "plans",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("blurb", sa.Text(), nullable=True),
        # NULL price = "contact us"; 0 = genuinely free.
        sa.Column("price_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=False, server_default="EUR"),
        sa.Column("billing_interval", sa.Text(), nullable=False, server_default="month"),
        sa.Column("tile_quota", sa.BigInteger(), nullable=True),
        sa.Column("analytics_quota", sa.BigInteger(), nullable=True),
        sa.Column("rate_limit_per_minute", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("max_api_keys", sa.Integer(), nullable=False, server_default="2"),
        sa.Column(
            "permissions",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        # A provider price id is deployment-specific, so it is a column rather
        # than seeded data: the same migration runs against test and live
        # Stripe accounts.
        sa.Column("provider_price_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("code"),
        sa.CheckConstraint("price_cents IS NULL OR price_cents >= 0", name="plans_price_non_negative"),
        schema=SCHEMA,
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_code", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("current_period_start", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("provider_customer_id", sa.Text(), nullable=True),
        sa.Column("provider_subscription_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # One live subscription per user: a plan change updates this row rather
        # than stacking a second entitlement the quota check would have to
        # reconcile.
        sa.UniqueConstraint("user_id", name="subscriptions_one_per_user"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_code"], [f"{SCHEMA}.plans.code"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'canceled')",
            name="subscriptions_status_valid",
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_subscriptions_provider_subscription",
        "subscriptions",
        ["provider_subscription_id"],
        unique=False,
        schema=SCHEMA,
    )

    op.create_table(
        "api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # The prefix is the half shown back to the user; the digest is the only
        # copy of the secret half, so a dump of this table is not replayable.
        sa.Column("prefix", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prefix", name="api_keys_prefix_unique"),
        sa.UniqueConstraint("key_hash", name="api_keys_hash_unique"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        schema=SCHEMA,
    )
    op.create_index("ix_api_keys_user", "api_keys", ["user_id"], schema=SCHEMA)

    op.create_table(
        "usage_daily",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_key_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("quantity", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["auth.users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["api_key_id"], [f"{SCHEMA}.api_keys.id"], ondelete="SET NULL"),
        schema=SCHEMA,
    )
    # COALESCE, not a plain unique constraint: NULL api_key_id (session-token
    # traffic) would otherwise never conflict, so every flush would insert a
    # new row instead of incrementing the day's counter.
    op.execute(
        """
        CREATE UNIQUE INDEX usage_daily_bucket ON billing.usage_daily (
            user_id,
            COALESCE(api_key_id, '00000000-0000-0000-0000-000000000000'::uuid),
            day,
            metric
        )
        """
    )
    op.create_index("ix_usage_daily_user_day", "usage_daily", ["user_id", "day"], schema=SCHEMA)

    conn = op.get_bind()
    for (
        code, name, blurb, price_cents, tile_quota, analytics_quota,
        rate_limit, max_keys, permissions, features, is_public, sort_order,
    ) in PLANS:
        conn.execute(
            INSERT_PLAN,
            {
                "code": code,
                "name": name,
                "blurb": blurb,
                "price_cents": price_cents,
                "tile_quota": tile_quota,
                "analytics_quota": analytics_quota,
                "rate_limit": rate_limit,
                "max_keys": max_keys,
                "permissions": permissions,
                "features": json.dumps(features),
                "is_public": is_public,
                "sort_order": sort_order,
            },
        )


def downgrade() -> None:
    op.drop_table("usage_daily", schema=SCHEMA)
    op.drop_table("api_keys", schema=SCHEMA)
    op.drop_table("subscriptions", schema=SCHEMA)
    op.drop_table("plans", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
