# Deployment on free tiers

The goal: a portfolio someone can open from a link, that stays up, and that costs nothing.
Those three pull against each other, and most "free tier" lists ignore the second one.

---

## Managed Postgres with PostGIS

PostGIS is the constraint. Plenty of providers have a free Postgres tier; fewer let you
`CREATE EXTENSION postgis` on it, and fewer still stay running.

| Provider | PostGIS free? | Storage | Sleep / expiry | Verdict |
|---|---|---|---|---|
| **Aiven** | Yes | 1 GB | **None** — no sleep, no expiry, no card | **Pick this.** The only always-on option here, and Amsterdam is a region. |
| **Neon** | Yes | 0.5 GB | Scales to zero after 5 min (~1 s cold start), 100 compute-hrs/mo | Best developer experience; branching is a good talking point. 0.5 GB is tight. |
| **Supabase** | Yes, not Pro-gated | 500 MB | **Pauses after 7 days idle** | Fine if you add a keep-alive ping. Two active projects max. |
| **Koyeb** | Yes | small | Auto-sleep after 5 min, 50 hrs/mo | Workable; you can co-locate the API. |
| **Render** | Yes | 1 GB | **Database expires 30 days after creation** | A trap for a portfolio. It will be dead when someone looks. |
| **Railway** | Yes | — | **Not actually free** — $5 trial, then paused | Same trap. |

Two of these are traps specifically for this use case: a portfolio's whole job is to be working
when someone you are not talking to opens it, and a database that expires after 30 days or
pauses after 7 idle days fails exactly then.

**Recommended:** Aiven for always-on, Neon if you want the branching demo and can live inside
0.5 GB.

### Fitting the data in 0.5 GB

The demo dataset is ~45k rows and lands around 120 MB with indexes. If you load the real
extracts instead:

- Load **only the study-area clip**, never a national file. The Utrecht OSM extract is 90 MB;
  the Netherlands file is 1.3 GB.
- Keep **rasters out of Postgres.** DEM, WorldCover and SoilGrids belong on object storage as
  COGs, sampled into columns at ETL time. That is already how `agri.fields` carries its soil and
  land-cover attributes — the raster is never queried at request time.
- For the biggest static layers, consider **pre-rendering to PMTiles** and serving from a CDN,
  leaving the database to answer only analytics queries. See below.

---

## API hosting

| Provider | Free allowance | Cold start | Notes |
|---|---|---|---|
| **Hugging Face Spaces** | 2 vCPU / **16 GB RAM**, Docker | Sleeps after 48 h idle | Most generous resources on this list. HF-branded URL. |
| **Koyeb** | 1 GB RAM, 50 hrs/mo | 5 min auto-sleep | Can co-locate the database. |
| **Cloudflare Workers** | 100k req/day | ~0 | **10 ms CPU per request** — fine as a proxy, not for PostGIS work. Direct TCP to Postgres needs Hyperdrive (paid). |
| **AWS Lambda** | 1M requests + 400k GB-s, always free | 200 ms – 2 s | Use **Function URLs**, not API Gateway, whose free tier is 12 months only. Container image for a GDAL layer. |
| **Fly.io** | **None in 2026** | — | The old three-VM allowance is gone; new orgs get 2 VM-hours. Do not plan around it. |

The API is a normal container (`backend/Dockerfile`, non-root, health-checked), so any of these
work. `entrypoint.sh` waits for the database, runs `alembic upgrade head`, then serves.

### The cold-start problem, and how to dodge it

A sleeping API means the first visitor waits several seconds staring at an empty map. The fix is
to split what has to be fast from what can spin up:

```
Frontend   Cloudflare Pages          static, instant, custom domain
Tiles      Cloudflare R2 (PMTiles)   10 GB free, no egress fees, no cold start
API        Hugging Face Spaces       analytics queries only — a spinner here is fine
Database   Aiven                     always-on
```

Pre-render the vector tiles to PMTiles and put them on R2, and the map draws immediately from
the CDN even while the API is still waking. The API is then only hit for the chart panels, where
a brief spinner is unremarkable.

That is a change to how tiles are *served*, not to how they are *made* — `ST_AsMVT` still
generates them, `tippecanoe`/`pmtiles` just packages the output. The trade-off is that tiles
become a build artefact rather than live, so per-user filtering and RBAC on tiles no longer
apply. **If the point is to demonstrate access control, keep tiles on the API.** For this
project that is the whole thesis, so the default configuration serves them live.

---

## Frontend

Static build (`npm run build`) to Cloudflare Pages, Vercel or Netlify — all comfortably free.

Set `VITE_API_BASE` at build time to the API origin when they are on different hosts:

```bash
VITE_API_BASE=https://your-api.hf.space/api npm run build
```

Leave it unset to use a same-origin `/api` proxy. `frontend/Dockerfile` has an nginx `serve`
stage if you prefer a container; it caches hashed assets for a year and falls through to
`index.html` for client-side routes.

Add the frontend origin to `CORS_ORIGINS` on the API.

---

## Configuration

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | local dev URL | Accepts the plain `postgres://` URL providers hand out; the driver prefix and `sslmode` are normalised for asyncpg |
| `SECRET_KEY` | insecure placeholder | **Set this.** `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `SEED_DEMO_USERS` | `true` | **Set `false` in production** |
| `DEMO_PASSWORD` | `demo1234` | Only used when seeding |
| `CORS_ORIGINS` | localhost dev origins | Comma-separated |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Shorter = faster revocation, more refreshes |
| `TILE_CACHE_SECONDS` | `3600` | Also the `Cache-Control` max-age |
| `DB_POOL_SIZE` / `DB_POOL_RECYCLE` | `5` / `300` | Serverless Postgres drops idle connections; keep recycle low |

Managed providers that require TLS but present a chain asyncpg cannot verify (Neon, the Supabase
pooler, Aiven) are detected by hostname in `app/core/db.py`, which requests TLS without
verification — matching what `sslmode=require` does. If you need full verification, supply the
provider CA and set `verify_mode` there.

---

## Checklist

```
[ ] SECRET_KEY set to a generated value
[ ] SEED_DEMO_USERS=false, or the demo password changed
[ ] CORS_ORIGINS lists only your frontend origin
[ ] Database provider chosen for always-on, not just "free"
[ ] alembic upgrade head ran (the entrypoint does this)
[ ] Data loaded: python -m etl.load --generate
[ ] /health returns {"database": "connected"}
[ ] One API replica, or migrations moved to a release step
```

## Cost if you outgrow free

The architecture does not change shape. The first paid step is the database (~$10–20/mo for a
few GB with PostGIS); the API runs comfortably on the smallest instance any provider sells,
because the expensive work happens in Postgres. The second step, if tile traffic grows, is
pre-rendered PMTiles on object storage — which costs less than serving them live.
