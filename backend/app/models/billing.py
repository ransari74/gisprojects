"""SQLAlchemy models for the billing schema.

These four tables are the commercial half of the API: what is for sale
(``Plan``), who bought it (``Subscription``), what they authenticate with
(``ApiKey``) and what they consumed (``UsageDaily``).

The plan's entitlement is a list of the same permission codes ``auth``
already defines, so nothing downstream of the dependency layer has to know
that plans exist -- a request authorises against ``parcel:read`` whether the
caller arrived with a session token or a purchased key.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

# Every table here carries a foreign key to auth.users, which SQLAlchemy
# resolves by name against the shared metadata -- so the auth models have to be
# registered before these map, whatever order the importer happens to use.
from app.models.auth import User  # noqa: F401


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("price_cents IS NULL OR price_cents >= 0", name="plans_price_non_negative"),
        {"schema": "billing"},
    )

    code: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    blurb: Mapped[str | None] = mapped_column(Text)
    # NULL means "contact us" -- distinct from 0, which is genuinely free.
    price_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="EUR")
    billing_interval: Mapped[str] = mapped_column(Text, nullable=False, server_default="month")
    # NULL quota means unmetered.
    tile_quota: Mapped[int | None] = mapped_column(BigInteger)
    analytics_quota: Mapped[int | None] = mapped_column(BigInteger)
    rate_limit_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, server_default="60")
    max_api_keys: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")
    permissions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    features: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    provider_price_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def is_metered(self) -> bool:
        return self.tile_quota is not None or self.analytics_quota is not None

    @property
    def requires_sales_contact(self) -> bool:
        return self.price_cents is None


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        # One live subscription per user: a plan change updates this row rather
        # than stacking a second entitlement the quota check would reconcile.
        UniqueConstraint("user_id", name="subscriptions_one_per_user"),
        Index("ix_subscriptions_provider_subscription", "provider_subscription_id"),
        CheckConstraint(
            "status IN ('trialing', 'active', 'past_due', 'canceled')",
            name="subscriptions_status_valid",
        ),
        {"schema": "billing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    plan_code: Mapped[str] = mapped_column(
        Text, ForeignKey("billing.plans.code", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    provider: Mapped[str | None] = mapped_column(Text)
    provider_customer_id: Mapped[str | None] = mapped_column(Text)
    provider_subscription_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def is_live(self) -> bool:
        """Entitlements hold while trialing or active, and during a dunning grace.

        ``past_due`` deliberately still serves traffic: cutting an integration
        off the hour a card expires loses more revenue than the few days of
        usage it saves.
        """
        return self.status in ("trialing", "active", "past_due")


class ApiKey(Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_user", "user_id"),
        {"schema": "billing"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    prefix: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class UsageDaily(Base):
    __tablename__ = "usage_daily"
    # The unique bucket index is on COALESCE(api_key_id, zero-uuid) and has no
    # declarative equivalent, so it is created in the migration and excluded
    # from autogenerate in alembic/env.py.
    __table_args__ = (
        Index("ix_usage_daily_user_day", "user_id", "day"),
        {"schema": "billing"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False
    )
    api_key_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("billing.api_keys.id", ondelete="SET NULL")
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    metric: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
