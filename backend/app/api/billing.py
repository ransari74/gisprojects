"""Commercial endpoints: plans, subscriptions, API keys, usage, webhooks.

    GET    /api/billing/plans          -- public price list (no auth)
    GET    /api/billing/subscription   -- the caller's plan, status and usage
    POST   /api/billing/checkout       -- start a hosted checkout, or switch
                                          straight to a free plan
    POST   /api/billing/portal         -- hand the customer to Stripe's portal
    POST   /api/billing/webhook        -- provider callback (signature-checked)
    GET    /api/billing/keys           -- list the caller's API keys
    POST   /api/billing/keys           -- mint one (secret shown exactly once)
    DELETE /api/billing/keys/{id}      -- revoke one
    GET    /api/billing/usage          -- usage against quota, this period

The price list is deliberately unauthenticated: a pricing page that needs a
login is a pricing page nobody reads.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user, get_db_user, get_optional_user
from app.models.auth import User
from app.models.billing import ApiKey, Plan
from app.schemas.billing import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    CheckoutResponse,
    PlanChangeRequest,
    PlanOut,
    SubscriptionOut,
)
from app.services import billing, payments

log = logging.getLogger("app.billing")

router = APIRouter(prefix="/billing", tags=["billing"])

Db = Annotated[AsyncSession, Depends(get_db)]
Current = Annotated[CurrentUser, Depends(get_current_user)]
DbUser = Annotated[User, Depends(get_db_user)]


def _plan_out(plan: Plan, *, current_code: str | None = None) -> PlanOut:
    return PlanOut(
        code=plan.code,
        name=plan.name,
        blurb=plan.blurb,
        price_cents=plan.price_cents,
        currency=plan.currency,
        billing_interval=plan.billing_interval,
        tile_quota=plan.tile_quota,
        analytics_quota=plan.analytics_quota,
        rate_limit_per_minute=plan.rate_limit_per_minute,
        max_api_keys=plan.max_api_keys,
        permissions=list(plan.permissions or []),
        features=list(plan.features or []),
        current=current_code == plan.code,
        self_serve=not plan.requires_sales_contact,
        sales_email=settings.sales_email if plan.requires_sales_contact else None,
    )


@router.get("/plans", response_model=list[PlanOut])
async def list_plans(
    db: Db,
    current: Annotated[CurrentUser | None, Depends(get_optional_user)] = None,
) -> list[PlanOut]:
    """The public price list, with the caller's own plan flagged if signed in."""
    current_code = None
    if current is not None:
        sub = await billing.get_subscription(db, current.id)
        current_code = sub.plan_code if sub else settings.default_plan_code

    plans = await billing.list_plans(db, public_only=True)
    return [_plan_out(plan, current_code=current_code) for plan in plans]


@router.get("/subscription", response_model=SubscriptionOut)
async def my_subscription(current: Current, db: Db) -> SubscriptionOut:
    sub = await billing.ensure_subscription(db, current.id)
    plan = await billing.get_plan(db, sub.plan_code)
    if plan is None:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Subscription references unknown plan {sub.plan_code!r}",
        )
    return SubscriptionOut(
        plan=_plan_out(plan, current_code=plan.code),
        status=sub.status,
        current_period_start=sub.current_period_start,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
        provider=sub.provider,
        payments_configured=payments.configured(),
    )


@router.get("/usage")
async def my_usage(current: Current, db: Db) -> dict:
    """Usage against quota for the current period.

    Flushes the in-memory buffer first, so a customer who just made a request
    and immediately opened this screen does not see a stale number and conclude
    the meter is broken.
    """
    try:
        await billing.usage.flush(db)
    except Exception as exc:  # noqa: BLE001
        log.warning("Usage flush before summary failed (%s: %s)", type(exc).__name__, exc)

    entitlement = await billing.entitlement_for_user(db, current.id)
    summary = await billing.usage_summary(db, current.id, entitlement)
    return {
        "planCode": entitlement.plan_code,
        "planName": entitlement.plan_name,
        "status": entitlement.status,
        "rateLimitPerMinute": entitlement.rate_limit_per_minute,
        **summary,
    }


@router.post("/checkout", response_model=CheckoutResponse)
async def checkout(body: PlanChangeRequest, user: DbUser, db: Db) -> CheckoutResponse:
    """Move to a plan, via hosted checkout when money changes hands.

    Three outcomes, in order of how much of the world has to cooperate:

    * A free plan is applied immediately -- there is nothing to charge.
    * A priced plan with a provider configured returns a checkout URL; the
      subscription row is not touched until the webhook confirms payment.
      Granting entitlements on the redirect instead would hand the plan to
      anyone who can guess the success URL.
    * A priced plan with no provider (or no price id on the row) is a sales
      conversation, answered with 503 and an address.
    """
    plan = await billing.get_plan(db, body.plan_code)
    if plan is None or not plan.is_public:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown plan {body.plan_code!r}")

    if settings.demo_read_only:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This is a public demo deployment -- plan changes are disabled here.",
        )

    if plan.price_cents == 0:
        await billing.set_plan(db, user.id, plan.code, status="active")
        return CheckoutResponse(
            checkout_url=None,
            plan_code=plan.code,
            status="active",
            message=f"You are now on the {plan.name} plan.",
        )

    if plan.requires_sales_contact or not payments.configured() or not plan.provider_price_id:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"The {plan.name} plan is sold by invoice. Email {settings.sales_email} "
            "and we will have it running the same day.",
        )

    base = settings.public_site_url.rstrip("/")
    try:
        session = await payments.create_checkout_session(
            price_id=plan.provider_price_id,
            customer_email=user.email,
            client_reference_id=str(user.id),
            plan_code=plan.code,
            success_url=f"{base}/account?checkout=success",
            cancel_url=f"{base}/pricing?checkout=cancelled",
        )
    except payments.PaymentsNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except payments.PaymentsError as exc:
        log.error("Checkout session failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not start checkout") from exc

    return CheckoutResponse(
        checkout_url=session.get("url"),
        plan_code=plan.code,
        status="pending",
        message=f"Complete payment to activate {plan.name}.",
    )


@router.post("/portal")
async def portal(current: Current, db: Db) -> dict:
    """Stripe's own screen for changing card details or cancelling."""
    sub = await billing.get_subscription(db, current.id)
    if sub is None or not sub.provider_customer_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "No payment account is attached to this subscription yet.",
        )
    try:
        session = await payments.create_portal_session(
            customer_id=sub.provider_customer_id,
            return_url=f"{settings.public_site_url.rstrip('/')}/account",
        )
    except payments.PaymentsNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except payments.PaymentsError as exc:
        log.error("Portal session failed: %s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not open the billing portal") from exc
    return {"portalUrl": session.get("url")}


# Events we act on. Anything else is acknowledged and ignored -- returning a
# non-2xx for an event type we do not handle would make Stripe retry it
# forever.
HANDLED_EVENTS = {
    "checkout.session.completed",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.payment_failed",
}

# Stripe's subscription statuses, mapped onto the four this schema allows.
STATUS_MAP = {
    "trialing": "trialing",
    "active": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "incomplete": "past_due",
    "incomplete_expired": "canceled",
    "canceled": "canceled",
    "paused": "canceled",
}


@router.post("/webhook", include_in_schema=False)
async def provider_webhook(
    request: Request,
    db: Db,
    stripe_signature: Annotated[str | None, Header(alias="Stripe-Signature")] = None,
) -> Response:
    payload = await request.body()
    try:
        event = payments.verify_webhook(payload, stripe_signature)
    except payments.PaymentsNotConfigured as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except payments.PaymentsError as exc:
        # 400, not 401: a bad signature is a malformed request from something
        # claiming to be the provider, and Stripe treats 4xx as "do not retry".
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    event_type = event.get("type", "")
    if event_type not in HANDLED_EVENTS:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    obj = (event.get("data") or {}).get("object") or {}
    metadata = obj.get("metadata") or {}
    user_id = metadata.get("user_id") or obj.get("client_reference_id")
    plan_code = metadata.get("plan_code")

    if not user_id:
        log.warning("Webhook %s carried no user reference; ignoring", event_type)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        log.warning("Webhook %s carried an unparsable user id %r", event_type, user_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if event_type == "customer.subscription.deleted":
        await billing.set_plan(
            db, user_uuid, settings.default_plan_code, status="active", provider="stripe"
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if event_type == "invoice.payment_failed":
        sub = await billing.get_subscription(db, user_uuid)
        if sub is not None:
            await billing.set_plan(db, user_uuid, sub.plan_code, status="past_due", provider="stripe")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    if plan_code is None:
        log.warning("Webhook %s carried no plan_code; ignoring", event_type)
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    if await billing.get_plan(db, plan_code) is None:
        log.warning("Webhook %s named unknown plan %r; ignoring", event_type, plan_code)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    period_end = obj.get("current_period_end")
    await billing.set_plan(
        db,
        user_uuid,
        plan_code,
        status=STATUS_MAP.get(obj.get("status", "active"), "active"),
        provider="stripe",
        provider_customer_id=obj.get("customer"),
        provider_subscription_id=obj.get("subscription") or obj.get("id"),
        period_end=datetime.fromtimestamp(period_end, UTC) if period_end else None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- API keys ---------------------------------------------------------------


def _key_out(key: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=key.id,
        name=key.name,
        masked=billing.mask_key(key.prefix),
        created_at=key.created_at,
        last_used_at=key.last_used_at,
        revoked_at=key.revoked_at,
    )


@router.get("/keys", response_model=list[ApiKeyOut])
async def list_keys(current: Current, db: Db) -> list[ApiKeyOut]:
    keys = (
        (
            await db.execute(
                select(ApiKey)
                .where(ApiKey.user_id == current.id)
                .order_by(ApiKey.revoked_at.isnot(None), ApiKey.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [_key_out(key) for key in keys]


@router.post("/keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_key(body: ApiKeyCreate, current: Current, db: Db) -> ApiKeyCreated:
    """Mint a key. The secret is in this response and nowhere else, ever."""
    if settings.demo_read_only:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "This is a public demo deployment -- minting API keys is disabled here.",
        )

    entitlement = await billing.entitlement_for_user(db, current.id)
    plan = await billing.get_plan(db, entitlement.plan_code)
    live = (
        await db.execute(
            select(ApiKey).where(ApiKey.user_id == current.id, ApiKey.revoked_at.is_(None))
        )
    ).scalars().all()
    if plan is not None and len(live) >= plan.max_api_keys:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The {plan.name} plan allows {plan.max_api_keys} active keys. "
            "Revoke one, or upgrade.",
        )

    raw, prefix, digest = billing.generate_api_key()
    key = ApiKey(user_id=current.id, name=body.name.strip(), prefix=prefix, key_hash=digest)
    db.add(key)
    await db.commit()
    await db.refresh(key)

    return ApiKeyCreated(**_key_out(key).model_dump(), secret=raw)


@router.delete("/keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(key_id: uuid.UUID, current: Current, db: Db) -> None:
    key = (
        await db.execute(
            select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == current.id)
        )
    ).scalar_one_or_none()
    if key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such API key")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await db.commit()
    # The resolver caches by digest and the digest is what is stored, so the
    # revocation is exact and immediate rather than waiting out the TTL.
    billing.invalidate_key_cache(key.key_hash)
