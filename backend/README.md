---
title: Geospatial Portfolio API
emoji: 🗺️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8000
pinned: false
---

FastAPI backend for the Geospatial Portfolio project. See the main repo README
for what this serves: PostGIS-backed vector tiles, analytics endpoints and
role-based access control across five geospatial projects.

Configuration is via environment variables (Space secrets) — see
`docs/DEPLOYMENT.md` in the main repo for the full list
(`DATABASE_URL`, `SECRET_KEY`, `CORS_ORIGINS`, etc.).
