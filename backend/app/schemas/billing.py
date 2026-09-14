"""Request/response models for the commercial endpoints."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    blurb: str | None = None
    #: None means "contact us" -- rendered as such, never as free.
    price_cents: int | None = None
    currency: str = "EUR"
    billing_interval: str = "month"
    tile_quota: int | None = None
    analytics_quota: int | None = None
    rate_limit_per_minute: int
    max_api_keys: int
    permissions: list[str] = []
    features: list[str] = []
    #: True when this is the plan the authenticated caller is on.
    current: bool = False
    #: False when the tier can only be bought by talking to someone.
    self_serve: bool = True
    #: Who to email about this tier. Set only where self_serve is False, so the
    #: pricing page never has to hardcode an address.
    sales_email: str | None = None


class SubscriptionOut(BaseModel):
    plan: PlanOut
    status: str
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    provider: str | None = None
    #: True when a hosted checkout can actually be started in this deployment.
    payments_configured: bool = False


class MetricUsage(BaseModel):
    used: int
    limit: int | None = None
    remaining: int | None = None
    percent_used: float | None = Field(default=None, alias="percentUsed")

    model_config = ConfigDict(populate_by_name=True)


class UsageOut(BaseModel):
    period_start: str
    metrics: dict[str, MetricUsage]


class ApiKeyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    #: Masked -- the secret half is never readable after creation.
    masked: str
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ApiKeyCreated(ApiKeyOut):
    #: Shown exactly once. Only its SHA-256 digest is stored.
    secret: str


class PlanChangeRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=40)


class CheckoutResponse(BaseModel):
    #: Where to send the browser. Absent when the plan needed no payment.
    checkout_url: str | None = None
    plan_code: str
    status: str
    message: str
