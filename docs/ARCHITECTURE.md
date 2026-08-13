# Architecture

## The shape of it

```
Browser ── MapLibre ──► GET /api/tiles/{layer}/{z}/{x}/{y}.mvt ──► PostGIS ST_AsMVT
        │                     (Authorization: Bearer …)
        └─ D3 panels  ──► GET /api/{project}/{analysis}      ──► PostGIS aggregate
```

One FastAPI service, one PostGIS database, one static frontend. No tile server, no Redis, no
message queue — a portfolio that needs four processes to demonstrate itself does not get
demonstrated.

---

## Why the tile query is written the way it is

This is the single most performance-critical query in the project, and the obvious way to write
it is wrong.

```sql
WITH bounds AS (
    SELECT ST_TileEnvelope(:z, :x, :y) AS tile_3857,
           ST_Transform(ST_TileEnvelope(:z, :x, :y, margin => :margin), 4326) AS query_4326
),
src AS (
    SELECT ST_AsMVTGeom(ST_Transform(t.geom, 3857), bounds.tile_3857, 4096, 64, true) AS geom,
           t.id AS feature_id, …
    FROM agri.fields t, bounds
    WHERE t.geom && bounds.query_4326          -- ← the important line
      AND ST_Intersects(t.geom, bounds.query_4326)
    LIMIT :max_features
)
SELECT ST_AsMVT(src, 'agri_fields', 4096, 'geom', 'feature_id') FROM src
```

Geometry is stored in EPSG:4326 and the GiST index is built on it in that CRS. MVT output has
to be in web mercator, so a transform is unavoidable somewhere — the question is which side.

- `WHERE ST_Transform(t.geom, 3857) && tile_envelope` transforms **every row** before comparing.
  The index on `t.geom` cannot help, so it degrades to a sequential scan of the whole table on
  every single tile.
- `WHERE t.geom && ST_Transform(tile_envelope, 4326)` transforms **one envelope** and compares
  against the indexed column. The index does the filtering, and only the surviving rows get
  transformed inside `ST_AsMVTGeom`.

The `&&` bounding-box test comes first as a cheap index probe; `ST_Intersects` then does the
exact test on the small set that survives. `margin` widens the query envelope by the MVT buffer
so features crossing a tile edge are not clipped away from the neighbouring tile.

Below a per-layer zoom threshold, geometry is generalised before tiling with a tolerance of
about 1.5 screen pixels at that zoom. Building footprints opt out — they are already small, and
simplifying them turns a building into a triangle.

`tests/test_migrations.py::test_every_geometry_column_has_a_gist_index` asserts the indexes this
depends on actually exist, because a missing one is a silent performance cliff rather than an
error.

---

## The layer registry

`backend/app/services/layers.py` declares all sixteen layers in one place:

```python
LayerSpec(
    name="agri_fields", project="agriculture", schema="agri", table="fields",
    geom_kind="polygon", permission="agriculture:read",
    columns=("field_code", "crop_type", "yield_t_ha", …),
    filterable=("crop_type", "yield_class", …),
    range_filterable=("yield_t_ha", "soil_ph", …),
    min_zoom=8, style_hint={"type": "fill", "colorBy": "yield_t_ha"},
)
```

Driven from it: the tile endpoint, `/tiles/capabilities`, TileJSON, the generic
feature/histogram/breakdown/export endpoints, and the frontend's layer panel, legend and styling.
Adding a layer is one entry plus a migration.

### Why interpolating identifiers here is safe

The tile and feature queries interpolate `schema`, `table` and column names into SQL — they
cannot be bound parameters. That is only acceptable because those strings come exclusively from
this module, never from a request, and `LayerSpec.__post_init__` re-validates every identifier
against `^[a-z_][a-z0-9_]*$` at import time. A future edit that tried to slip something else in
raises before the app starts. All *values* are bound parameters as normal.

`filterable` and `range_filterable` are checked to be subsets of `columns`, so a filter can
never reach a column the layer does not select. Unknown filter parameters are ignored rather
than rejected, so a stale bookmark keeps working instead of 400-ing.

`tests/test_layers.py` asserts an injection attempt in a table name raises, and
`test_migrations.py` asserts every registry entry still matches a real table with the columns it
claims — so a migration that renames a column fails a test rather than producing 500s at
request time.

---

## Access control

The model is `user → role → permission`, where permissions are opaque `<resource>:<action>`
codes. **The API never checks a role name.** Guards look like:

```python
Read = Annotated[CurrentUser, Depends(require_permission("agriculture:read"))]
```

so roles can be reshaped from the admin screen without an application change.

Permissions are embedded in the access token. The hot path — tile requests, several dozen per
map interaction — therefore authorises with zero database round-trips. The cost is that a
revocation is not visible until the token expires, which is why access tokens default to one
hour and refresh tokens rotate.

Refresh tokens are stored as SHA-256 hashes, so a dump of `auth.refresh_tokens` is not directly
replayable. Each refresh burns the presented token as it issues the replacement: a stolen token
works at most once before the theft surfaces as a failed refresh for the real client.

`/tiles/capabilities` is filtered server-side. A user without `parcel:read` is not told the
parcel layers exist — the frontend builds its entire navigation and layer panel from that
response, so there is no client-side list to leak.

See **[RBAC.md](RBAC.md)** for the full matrix.

---

## Why the geo tables have models but are queried with SQL

`app/models/spatial.py` declares every project table with GeoAlchemy2, but the API queries them
through hand-written SQL. That is deliberate, not an oversight.

The models exist so Alembic's `--autogenerate` has something to diff against, which makes the
schema a reviewable, version-controlled artefact instead of loose DDL. Aligning them with the
migrations immediately caught real drift in the auth tables (`varchar` vs `text`, Python-side vs
server-side defaults) that would otherwise have surfaced as a confusing diff months later.

The queries stay in SQL because `ST_AsMVT`, `ST_SimplifyPreserveTopology`,
`percentile_cont … WITHIN GROUP`, `width_bucket` and `regr_r2` all express far more clearly that
way, and the tile path benefits from exact control over the emitted query. The ORM is used where
it earns its place: the RBAC tables, which are relationship-heavy and performance-insensitive.

---

## Frontend

`ProjectShell` owns the layout every project shares — map left, analytics rail right, layer
panel and legend over the map, filter row above the charts. The five project pages differ only
in their layers and their charts.

`MapView` owns MapLibre. Notable pieces:

- **Auth on tiles.** MapLibre issues tile requests itself, so the bearer token is attached via
  `transformRequest`, reading from an in-memory token cache that a background refresh keeps
  current. A `?access_token=` query fallback exists on the API for consumers that cannot set
  headers, but the browser path uses the header.
- **Draw order** is by geometry kind — polygons, then lines, then points — so a large fill never
  buries the network drawn over it.
- **Filter changes call `setTiles()`** rather than tearing the source down, so the layers stacked
  on it survive.
- **Terrain is probed before it is enabled.** MapLibre renders a terrain-enabled map through the
  DEM's depth buffer; if those tiles never arrive it paints *nothing at all* — buildings vanish
  along with the terrain. Reacting to the error event is not enough, because the failure surfaces
  as a fetch rejection inside a worker. So the DEM is fetched once first, and terrain is only
  switched on if it is reachable. Otherwise the map stays flat and says so.

### Charts

A shared kit (`components/charts/`) supplies bar, line, scatter, stacked bar, histogram, box
plot, population pyramid and terrain profile, all on the same axis/grid/tooltip plumbing.

The colour rules are enforced in `styles/theme.ts`, not left to each chart:

- The categorical order is validated for colour-vision deficiency in both modes — worst
  adjacent-pair ΔE 9.1 light, 8.4 dark. It is a fixed order, assigned by index from a stable
  domain list, so filtering a category out never repaints the survivors.
- Forms where any series can sit beside any other (scatter, bubble) cap at **three** series,
  because that is where the stricter all-pairs gate still passes. Past three, the tail folds into
  "Other" rather than getting an invented hue.
- Sequential encodings are one hue, light to dark. Map fills draw from the *ordinal* sub-range —
  the palest steps are designed to recede toward a chart surface, which is right for a heatmap
  cell and wrong for a polygon on a basemap, where the lightest features simply vanish.
- No chart has two y-axes. Where two measures do not share a scale — traffic volume and speed —
  they are two charts.
- Every chart with two or more series carries a legend, and every chart offers a table view, so
  nothing is conveyed by colour alone.

---

## Deliberate limitations

- **One API instance applies migrations at startup.** Fine for a single container; past one
  replica, move `alembic upgrade head` to a release step so two instances cannot race.
- **The tile cache is process-local**, not Redis. On a one-instance free-tier deployment that
  captures nearly all the benefit; HTTP `Cache-Control` does the rest at the CDN and browser.
- **Isochrones are pre-computed polygons, not routed.** Real ones need a routing engine (OSRM,
  Valhalla), which is a service this deliberately does not add. The area-to-population
  relationship they demonstrate is the part the accessibility panel is about.
- **`viewshed` compares neighbour heights**, it does not trace rays against the DEM. It answers
  "what breaks this roof's skyline", which is the screening question, not a full visibility
  analysis.
- **No write UI.** The `*:write` permissions exist and are enforced, but the projects are
  read-only analysis; the admin screen is the only mutating interface.
