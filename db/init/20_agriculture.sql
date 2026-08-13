-- ---------------------------------------------------------------------------
-- PROJECT 1 -- AGRICULTURE
--
-- Field parcels enriched with ISRIC SoilGrids soil chemistry, ESA WorldCover
-- land-cover class and a per-season NDVI/yield series.
--
-- Geometry mix: POLYGON (fields, soil zones) + LINESTRING (irrigation canals)
--               + POINT (soil sample sites, weather stations)
-- ---------------------------------------------------------------------------

CREATE TABLE agri.fields (
    id                SERIAL PRIMARY KEY,
    field_code        TEXT UNIQUE NOT NULL,
    farm_name         TEXT,
    crop_type         TEXT NOT NULL,          -- wheat | maize | barley | potato | sugarbeet | rapeseed | grassland
    crop_year         INTEGER NOT NULL,
    area_ha           DOUBLE PRECISION NOT NULL,
    irrigated         BOOLEAN NOT NULL DEFAULT FALSE,
    organic           BOOLEAN NOT NULL DEFAULT FALSE,

    -- SoilGrids 250 m, 0-30 cm depth-weighted means
    soil_ph           DOUBLE PRECISION,       -- pH in H2O
    soil_organic_c    DOUBLE PRECISION,       -- g/kg
    soil_nitrogen     DOUBLE PRECISION,       -- cg/kg
    soil_clay_pct     DOUBLE PRECISION,
    soil_sand_pct     DOUBLE PRECISION,
    soil_silt_pct     DOUBLE PRECISION,
    soil_texture      TEXT,                   -- derived USDA class

    -- ESA WorldCover 2021 majority class within the field
    landcover_class   TEXT,
    landcover_code    INTEGER,

    -- Sentinel-2 derived season aggregates
    ndvi_mean         DOUBLE PRECISION,
    ndvi_max          DOUBLE PRECISION,
    ndvi_stddev       DOUBLE PRECISION,

    elevation_m       DOUBLE PRECISION,
    slope_deg         DOUBLE PRECISION,
    yield_t_ha        DOUBLE PRECISION,
    yield_class       TEXT,                   -- low | medium | high
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    geom              geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX fields_geom_idx      ON agri.fields USING GIST (geom);
CREATE INDEX fields_crop_year_idx ON agri.fields (crop_year, crop_type);
CREATE INDEX fields_yield_idx     ON agri.fields (yield_t_ha);

-- LINESTRING layer: irrigation / drainage network
CREATE TABLE agri.irrigation_canals (
    id            SERIAL PRIMARY KEY,
    canal_code    TEXT UNIQUE NOT NULL,
    name          TEXT,
    canal_type    TEXT NOT NULL,              -- primary | secondary | tertiary | drainage
    lined         BOOLEAN NOT NULL DEFAULT FALSE,
    capacity_m3s  DOUBLE PRECISION,
    length_m      DOUBLE PRECISION,
    condition     TEXT,                       -- good | fair | poor
    geom          geometry(MultiLineString, 4326) NOT NULL
);
CREATE INDEX canals_geom_idx ON agri.irrigation_canals USING GIST (geom);
CREATE INDEX canals_type_idx ON agri.irrigation_canals (canal_type);

-- POINT layer: ground-truth soil samples backing the SoilGrids interpolation
CREATE TABLE agri.soil_samples (
    id             SERIAL PRIMARY KEY,
    sample_code    TEXT UNIQUE NOT NULL,
    sampled_on     DATE,
    depth_cm       INTEGER,
    ph             DOUBLE PRECISION,
    organic_c      DOUBLE PRECISION,
    nitrogen       DOUBLE PRECISION,
    phosphorus     DOUBLE PRECISION,
    potassium      DOUBLE PRECISION,
    geom           geometry(Point, 4326) NOT NULL
);
CREATE INDEX soil_samples_geom_idx ON agri.soil_samples USING GIST (geom);

-- Time series feeding the D3 multi-line NDVI chart
CREATE TABLE agri.field_ndvi_timeseries (
    id         BIGSERIAL PRIMARY KEY,
    field_id   INTEGER NOT NULL REFERENCES agri.fields(id) ON DELETE CASCADE,
    obs_date   DATE NOT NULL,
    ndvi       DOUBLE PRECISION NOT NULL,
    cloud_pct  DOUBLE PRECISION,
    UNIQUE (field_id, obs_date)
);
CREATE INDEX ndvi_ts_field_date_idx ON agri.field_ndvi_timeseries (field_id, obs_date);
