# Selling the API

The portfolio is the demo; the product is the API behind it. This document is the whole
commercial layer — what is sold, how entitlement is enforced, what it costs to run, and
what has to be true before the first invoice goes out.

---

## What is actually for sale

Not the web app. The web app is the shop window. What a customer buys is **programmatic
access to the same endpoints it runs on**:

| Sold | Endpoint family | Metered as |
|---|---|---|
| Vector tiles | `GET /api/tiles/{layer}/{z}/{x}/{y}.mvt` | `tile_request` |
| Layer analytics | `GET /api/{project}/…`, `GET /api/layers/{layer}/…` | `analytics_request` |
| Bulk export | `GET /api/layers/{layer}/export` | `export_request` |

Traffic from the browser app, authenticated with a session token, is **not metered**. A
customer pays for machine access, not for looking at their own dashboard — and metering
the dashboard would make the free tier's 20,000 tiles evaporate on one afternoon of
panning a map.

---

## The tiers

Seeded by migration `0013`, which is where they belong: the codes are referenced by
`DEFAULT_PLAN_CODE` and by the checkout flow, so they are part of the schema contract.

| | Free | Starter | Pro | Enterprise |
|---|---|---|---|---|
| Price | €0 | €49 / month | €199 / month | invoiced |
| Projects | agriculture, terrain | all six | all six | all six |
| Tiles / month | 20,000 | 250,000 | 2,000,000 | unmetered |
| Analytics / month | 500 | 10,000 | 100,000 | unmetered |
| Rate limit | 60/min | 300/min | 1,200/min | 6,000/min |
| API keys | 2 | 5 | 25 | 100 |
| Bulk export | — | — | ✓ | ✓ |

The ladder is enforced by a test, not by good intentions: `test_tiers_are_monotonic_in_price_quota_and_rate`
fails if a tier ever costs more and gives less.

**No public tier sells write access or administration.** `test_no_public_plan_grants_administration`
asserts it. The product is read access to a curated dataset; selling `:write` would mean
selling the ability to corrupt every other customer's view of the same rows.

---

## How entitlement is enforced

A plan row carries a `permissions` text[] of the **same permission codes** `auth.permissions`
already defines. So there is no second access model:

```
session token ─┐
               ├─→ CurrentUser(permissions=…) ─→ current.has("parcel:read")
API key ───────┘
```

Downstream of `app/core/deps.py`, nothing knows plans exist. The tile endpoint asks one
question and gets one answer, whichever credential arrived.

The consequence worth stating out loud: **a key carries its plan's permissions, never its
owner's.** An administrator who pastes a key into a client-side app exposes the tier they
bought, not their account. `test_api_key_sees_only_what_its_plan_grants` pins that down
using a superuser's key.

### Three checks per billable request

1. **Rate limit** — in-process token bucket, per key, refilled at `limit/60` per second with
   up to a minute of burst. The burst is not generosity: MapLibre opens a dozen tile
   requests the instant a viewport moves, and a strict per-second limit would reject half
   a normal pan.
2. **Quota** — a `SUM` over `billing.usage_daily` for the calendar month, cached for 60
   seconds, plus whatever is still sitting in the in-memory buffer. Over quota is `402`
   with `X-Quota-Used` / `X-Quota-Limit`.
3. **Meter** — increment an in-memory counter; flush to Postgres by age or buffer size.

Metering happens *on entry*, before the handler. That over-counts a request that later
500s and cannot under-count. The alternative — a response hook — would have to re-derive
the caller from a request that has already finished.

### What this costs on the hot path

| | Before | After |
|---|---|---|
| Tile request, session token | 1 query (the tile) | 1 query |
| Tile request, API key, warm cache | — | 1 query |
| Tile request, API key, cold cache | — | 2 queries |
| DB writes per 10,000 tiles | 0 | ~1 upsert |

Key resolution caches for `API_KEY_CACHE_SECONDS` (60 by default). That TTL is also the
revocation lag for a key nobody explicitly revoked — an explicit revoke drops the exact
digest from the cache, so `DELETE /api/billing/keys/{id}` is immediate.

---

## Authenticating with a key

Three slots, in order of preference:

```bash
curl -H "X-API-Key: $GEO_KEY"        "$API/tiles/agri_fields/11/1053/675.mvt"
curl -H "Authorization: Bearer $GEO_KEY" "$API/agriculture/yield-by-crop"
curl                                  "$API/tiles/agri_fields/11/1053/675.mvt?api_key=$GEO_KEY"
```

The query form exists because some consumers genuinely cannot set headers — a native map
SDK, a bare `<img>` raster preview. It lands in access logs, which is why it is documented
last and why keys are cheap to rotate.

Keys are `gpk_<live|test>_<prefix>_<secret>`. Only a SHA-256 digest is stored, so a dump of
`billing.api_keys` is not replayable. SHA-256 rather than bcrypt is deliberate: the secret
half is 32 bytes of `secrets` output, so there is no dictionary to attack, and bcrypt on a
tile-path cache miss would cost ~100 ms.

---

## Taking money

Stripe, over `httpx`, without the SDK — three calls and one signature check
(`app/services/payments.py`). Configure:

```bash
STRIPE_SECRET_KEY=sk_live_…
STRIPE_WEBHOOK_SECRET=whsec_…
PUBLIC_SITE_URL=https://your-deployment.example
SALES_EMAIL=you@example.com
```

Then set each paid plan's `provider_price_id` to the Stripe price it maps to:

```sql
UPDATE billing.plans SET provider_price_id = 'price_…' WHERE code = 'starter';
UPDATE billing.plans SET provider_price_id = 'price_…' WHERE code = 'pro';
```

A price id is deployment-specific, so it is a column rather than seeded data — the same
migration runs against a test and a live Stripe account.

**Entitlements are granted by the webhook, never by the success redirect.** Granting on
redirect would hand any plan to anyone who can guess the success URL. The webhook
verifies `Stripe-Signature` with a constant-time HMAC compare and a five-minute timestamp
window; an unset `STRIPE_WEBHOOK_SECRET` is a hard `503`, because an unsigned webhook
endpoint is an "upgrade any account to any plan" API.

**With no provider configured, everything else still works.** `/billing/plans` serves the
price list, keys mint, quotas enforce, usage meters. Paid tiers answer `503` naming
`SALES_EMAIL`. That is a supported mode, not a broken one: invoicing four customers by
hand is a perfectly good way to find out whether there are forty.

### Dunning

A failed payment moves the subscription to `past_due` and keys keep working for
`PAST_DUE_GRACE_DAYS` (7). Cutting an integration off the hour a card expires loses more
revenue than the week of usage it saves. After the grace window the key resolves to
nothing and returns `401`. Cancelling drops the account to Free; its keys keep working at
Free's limits rather than dying.

---

## Data model

```
billing.plans ──< billing.subscriptions >── auth.users ──< billing.api_keys
                                                │              │
                                                └──< billing.usage_daily >──┘
```

`usage_daily` is a **daily counter, not an event log**. Metering tile requests as rows
would put a write on the hottest path in the system to produce data nobody queries at
per-request resolution — every invoice and every quota check is a `SUM` over a period.

The unique index is on `(user_id, COALESCE(api_key_id, zero-uuid), day, metric)`. The
`COALESCE` is load-bearing: a plain unique constraint never conflicts on `NULL`, so
non-keyed traffic would insert a new row on every single flush.

---

## Before the first invoice

Ordered by what blocks money, not by what is most interesting to build.

1. **Self-serve signup.** There is no public registration endpoint — accounts are seeded or
   created by an admin. Today's funnel is "email us"; that is fine for the first ten
   customers and fatal at a hundred.
2. **Stripe price ids.** Two `UPDATE` statements, above.
3. **Terms, a privacy policy and a DPA.** The dataset is open data; the *usage records* are
   personal data under GDPR, and this is a Dutch-domiciled product.
4. **Invoice reconciliation.** `usage_daily` is per calendar month; Stripe bills on the
   subscription anniversary. They disagree by up to 30 days. It does not matter while
   pricing is flat-rate with a cap, and it matters enormously the day overage billing is
   introduced.
5. **A status page and an SLA** before selling anything that says "SLA" — Enterprise does.

## What is deliberately not built

- **Overage billing.** A surprise invoice is how you lose the customer *and* the money.
  Hitting the cap returns `402` and a link to the next tier.
- **Per-seat pricing.** The unit of value is requests, not people.
- **A usage event log.** See above; it buys per-request forensics nobody has asked for at
  the cost of a write on the hot path.
- **Cross-instance rate limiting.** The bucket is per process. Behind N instances each sees
  roughly 1/N of one key's traffic, so the effective limit is N× the configured one. That
  is the right direction to be wrong in, and a shared limiter means Redis, which the
  free-tier deployment target does not have.
