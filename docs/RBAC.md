# Role-based access control

## The model

```
user ──< user_roles >── role ──< role_permissions >── permission
```

A permission is an opaque string code, `<resource>:<action>`. **The API never checks a role
name** — every guard names a permission code:

```python
Read = Annotated[CurrentUser, Depends(require_permission("agriculture:read"))]

@router.get("/summary")
async def summary(_: Read, db: Db) -> dict: ...
```

That indirection is the whole point. An administrator can give the `viewer` role export rights,
or split `planner` into two roles, from the admin screen — no code change, no deploy.

---

## The permission catalogue

Seeded by migration `0009`, which is where it belongs: the codes are part of the schema
contract, since the route guards reference them by name.

| Code | Grants |
|---|---|
| `agriculture:read` | Agriculture layers, tiles and analytics |
| `parcel:read` | Cadastral parcels and zoning |
| `demographics:read` | Census tracts and population data |
| `transport:read` | Road network, transit and isochrones |
| `terrain:read` | 3D buildings, contours and terrain |
| `agriculture:write` … `terrain:write` | Create/update records in that project |
| `data:export` | Export query results as GeoJSON/CSV |
| `analytics:read` | Aggregate analytics endpoints (histograms, breakdowns) |
| `admin:users` | Create, edit and deactivate users |
| `admin:roles` | Assign roles and edit role permissions |
| `admin:audit` | Read the audit log |

## The built-in roles

| | admin | analyst | agronomist | planner | viewer |
|---|:-:|:-:|:-:|:-:|:-:|
| agriculture:read | ✅ | ✅ | ✅ | — | ✅ |
| agriculture:write | ✅ | — | ✅ | — | — |
| parcel:read | ✅ | ✅ | — | ✅ | ✅ |
| parcel:write | ✅ | — | — | ✅ | — |
| demographics:read | ✅ | ✅ | ✅ | ✅ | ✅ |
| transport:read | ✅ | ✅ | — | ✅ | ✅ |
| transport:write | ✅ | — | — | ✅ | — |
| terrain:read | ✅ | ✅ | ✅ | ✅ | ✅ |
| analytics:read | ✅ | ✅ | ✅ | ✅ | — |
| data:export | ✅ | ✅ | ✅ | ✅ | — |
| admin:* | ✅ | — | — | — | — |

The roles are deliberately *asymmetric* — the agronomist cannot see the cadastre and the planner
cannot see agriculture — because a demo where every role differs only in quantity does not
actually show enforcement working. Sign in as each and the navigation changes.

`admin` is granted with a `CROSS JOIN` over the permission table rather than an enumerated list,
so a permission added by a later migration is automatically included. The API refuses to narrow
the admin role's permissions.

---

## Where enforcement happens

Three layers, each independently sufficient:

**1. The token.** On login the user's permission set is embedded in the JWT (superusers get a
`*` wildcard instead, so a permission added later applies without re-issuing). Every guard reads
it from the token, so the high-frequency path — tile requests — costs no database round-trip.

**2. Route guards.** `require_permission(...)` on every project router;
`require_tile_permission(...)` on the tile endpoint, which also accepts the `?access_token=`
fallback for consumers that cannot set headers.

**3. Response filtering.** `/tiles/capabilities` only returns layers the caller may request, and
`/meta/projects` marks the rest `accessible: false`. The frontend builds its navigation, layer
panel and legends entirely from those responses, so there is no client-side list to leak — but
the API would refuse the request anyway.

The test suite asserts the whole matrix, including that a direct tile request for a forbidden
layer returns 403 rather than an empty tile.

---

## Token lifecycle

| | Lifetime | Storage | Notes |
|---|---|---|---|
| Access token | 60 min | In-memory only | Carries the permission set |
| Refresh token | 14 days | `localStorage`, SHA-256 hashed server-side | Rotates on every use |

Because permissions live in the access token, **a revocation takes effect at the next refresh,
not instantly.** That is the explicit trade-off for making tile authorisation free, and it is
why the access-token lifetime is short. If your threat model needs immediate revocation, check
`auth.user_permissions` per request instead and accept the round-trip.

Each refresh burns the token it was given as it issues the replacement. A stolen refresh token
is therefore usable at most once, and the theft surfaces as a failed refresh for the legitimate
client. Changing a user's password deletes all their refresh tokens.

Login returns an identical response for "no such user" and "wrong password", so the endpoint
cannot be used to enumerate registered addresses. There is a test for this.

Every login, logout, user change and role assignment is written to `auth.audit_log` with the
acting user and a JSONB detail blob.

---

## Extending it

**Add a permission:**

```python
# alembic/versions/…_add_export_scheduling.py
PERMISSIONS = [("data:schedule", "data", "schedule", "Schedule recurring exports")]
```

Then guard the route with `require_permission("data:schedule")`. `admin` picks it up
automatically; other roles need an explicit grant in the same migration.

**Add a project:** add a `LayerSpec` per layer with `permission="myproject:read"`, an entry in
`PROJECTS`, the permission codes in a migration, and a page component. The tile endpoint,
capabilities, feature/export endpoints and layer panel all follow from the registry.

**Per-row access** (a user seeing only their own municipality's parcels) is *not* implemented.
The natural place is a tenant column plus a filter injected into `_build_where` from the token's
claims — the tile query already composes its WHERE clause from a validated filter object, so
that is where the hook goes.

---

## Demo accounts

All use the password `demo1234`. They are created on startup by
`app/core/bootstrap.py` and controlled by `SEED_DEMO_USERS`.

```
admin@geo.dev        admin        everything + administration
analyst@geo.dev      analyst      all five projects, analytics, export
agronomist@geo.dev   agronomist   agriculture read/write; no cadastre
planner@geo.dev      planner      cadastre + transport; no agriculture
viewer@geo.dev       viewer       map layers only; no analytics, no export
```

**Set `SEED_DEMO_USERS=false` in any real deployment**, and set `SECRET_KEY` to something you
generated. The default key is a development placeholder and the application says so.
