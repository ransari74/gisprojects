-- ---------------------------------------------------------------------------
-- Extensions + schemas
-- Runs first (docker-entrypoint-initdb.d executes files in lexical order).
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgcrypto;      -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- One schema per portfolio project keeps the MVT layer registry unambiguous
-- and lets us grant/revoke per project at the database level later on.
CREATE SCHEMA IF NOT EXISTS auth;        -- users, roles, permissions
CREATE SCHEMA IF NOT EXISTS agri;        -- project 1: agriculture
CREATE SCHEMA IF NOT EXISTS parcel;      -- project 2: cadastre / land use
CREATE SCHEMA IF NOT EXISTS demog;       -- project 3: demographics
CREATE SCHEMA IF NOT EXISTS transport;   -- project 4: mobility network
CREATE SCHEMA IF NOT EXISTS terrain;     -- project 5: 3D terrain + buildings
CREATE SCHEMA IF NOT EXISTS meta;        -- shared: study area, layer registry

-- ---------------------------------------------------------------------------
-- Shared study-area definition. Every ETL job clips to this polygon so the
-- five projects overlay exactly.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS meta.study_area (
    id          SERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    country     TEXT,
    epsg_local  INTEGER NOT NULL DEFAULT 3857,   -- projected SRID for area/length maths
    geom        geometry(MultiPolygon, 4326) NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS study_area_geom_idx ON meta.study_area USING GIST (geom);

-- Free-form key/value used by the ETL to record dataset provenance so the
-- frontend "data sources" panel is generated, not hand-maintained.
CREATE TABLE IF NOT EXISTS meta.dataset_source (
    id           SERIAL PRIMARY KEY,
    project      TEXT NOT NULL,
    layer        TEXT NOT NULL,
    dataset_name TEXT NOT NULL,
    provider     TEXT,
    license      TEXT,
    source_url   TEXT,
    fetched_at   TIMESTAMPTZ,
    feature_count INTEGER,
    notes        TEXT,
    UNIQUE (project, layer, dataset_name)
);
