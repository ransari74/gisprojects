"""Stripe, over httpx, without the SDK.

Three calls and one signature check is the entire surface this product needs --
create a Checkout Session, create a Billing Portal session, read a webhook --
and each is a form-encoded POST to a documented URL. Taking the SDK for that
would add a dependency with its own HTTP stack to a Lambda bundle that is
already close to the layer limit, and `httpx` is here regardless because the
test suite runs on it.

The provider is optional. With `stripe_secret_key` unset every function here
raises `PaymentsNotConfigured`, the checkout endpoint answers 503 naming the
sales address, and the rest of the product -- plans, keys, quotas, metering --
works exactly as it does in production. That is deliberate: a deployment should
be able to run the metered API on invoices alone.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time

import httpx

from app.core.config import settings

STRIPE_API_VERSION = "2024-06-20"
# Stripe rejects a signature whose timestamp is far from now; five minutes is
# the tolerance their own libraries use.
SIGNATURE_TOLERANCE_SECONDS = 300


class PaymentsNotConfigured(RuntimeError):
    """No provider credentials in this deployment."""


class PaymentsError(RuntimeError):
    """The provider rejected the call."""


def configured() -> bool:
    return settings.payments_configured


def _require_configured() -> str:
    if not settings.stripe_secret_key:
        raise PaymentsNotConfigured(
            "No payment provider is configured for this deployment. "
            f"Invoiced plans are available from {settings.sales_email}."
        )
    return settings.stripe_secret_key


async def _post(path: str, form: dict[str, str]) -> dict:
    key = _require_configured()
    url = f"{settings.stripe_api_base.rstrip('/')}/{path.lstrip('/')}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            url,
            data=form,
            auth=(key, ""),
            headers={"Stripe-Version": STRIPE_API_VERSION},
        )
    if response.status_code >= 400:
        detail = response.json().get("error", {}).get("message", response.text)
        raise PaymentsError(f"Stripe {response.status_code}: {detail}")
    return response.json()


async def create_checkout_session(
    *,
    price_id: str,
    customer_email: str,
    client_reference_id: str,
    plan_code: str,
    success_url: str,
    cancel_url: str,
) -> dict:
    """Start a hosted checkout for a recurring price.

    `client_reference_id` carries our user id through the hosted flow, and the
    metadata carries the plan code. The webhook needs both: Stripe's session
    object is the only thing that comes back, and it must be enough to decide
    which row in `billing.subscriptions` to update and to what.
    """
    return await _post(
        "checkout/sessions",
        {
            "mode": "subscription",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "customer_email": customer_email,
            "client_reference_id": client_reference_id,
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata[plan_code]": plan_code,
            "metadata[user_id]": client_reference_id,
            "subscription_data[metadata][plan_code]": plan_code,
            "subscription_data[metadata][user_id]": client_reference_id,
            "allow_promotion_codes": "true",
        },
    )


async def create_portal_session(*, customer_id: str, return_url: str) -> dict:
    """Hand the customer to Stripe's own portal to change card or cancel.

    Building card management in-house would mean handling PANs; this is the
    one screen worth not owning.
    """
    return await _post(
        "billing_portal/sessions",
        {"customer": customer_id, "return_url": return_url},
    )


def verify_webhook(payload: bytes, signature_header: str | None) -> dict:
    """Validate a `Stripe-Signature` header and return the parsed event.

    Without this check the webhook endpoint is an unauthenticated "upgrade any
    account to any plan" API, so an unset webhook secret is a hard error rather
    than a skipped check.
    """
    secret = settings.stripe_webhook_secret
    if not secret:
        raise PaymentsNotConfigured("STRIPE_WEBHOOK_SECRET is not set; refusing to trust webhooks")
    if not signature_header:
        raise PaymentsError("Missing Stripe-Signature header")

    parts = dict(
        piece.split("=", 1) for piece in signature_header.split(",") if "=" in piece
    )
    timestamp = parts.get("t")
    provided = parts.get("v1")
    if not timestamp or not provided:
        raise PaymentsError("Malformed Stripe-Signature header")

    try:
        age = abs(time.time() - int(timestamp))
    except ValueError as exc:
        raise PaymentsError("Malformed Stripe-Signature timestamp") from exc
    if age > SIGNATURE_TOLERANCE_SECONDS:
        raise PaymentsError("Stripe-Signature timestamp is outside the tolerance window")

    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, provided):
        raise PaymentsError("Stripe-Signature does not match")

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PaymentsError("Webhook body is not JSON") from exc
