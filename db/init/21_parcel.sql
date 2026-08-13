-- ---------------------------------------------------------------------------
-- PROJECT 2 -- PARCEL / CADASTRE
--
-- Cadastral parcels with zoning, land use, assessed value and building
-- coverage -- the classic "land information system" portfolio piece.
--
-- Geometry mix: POLYGON (parcels, zoning districts)
--               + LINESTRING (parcel boundary edges / easements)
-- ---------------------------------------------------------------------------

CREATE TABLE parcel.zoning_districts (
    id            SERIAL PRIMARY KEY,
    zone_code     TEXT NOT NULL,
    zone_name     TEXT NOT NULL,
    zone_category TEXT NOT NULL,        -- residential | commercial | industrial | mixed | agricultural | open_space
    max_far       DOUBLE PRECISION,     -- floor area ratio
    max_height_m  DOUBLE PRECISION,
    min_lot_m2    DOUBLE PRECISION,
    adopted_on    DATE,
    geom          geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX zoning_geom_idx ON parcel.zoning_districts USING GIST (geom);
CREATE INDEX zoning_cat_idx  ON parcel.zoning_districts (zone_category);

CREATE TABLE parcel.parcels (
    id                 SERIAL PRIMARY KEY,
    parcel_pin         TEXT UNIQUE NOT NULL,   -- parcel identification number
    address            TEXT,
    district           TEXT,
    zone_code          TEXT,
    zoning_district_id INTEGER REFERENCES parcel.zoning_districts(id) ON DELETE SET NULL,

    land_use           TEXT NOT NULL,   -- residential | retail | office | industrial | civic | vacant | mixed
    owner_type         TEXT,            -- private | corporate | municipal | state | ngo
    lot_area_m2        DOUBLE PRECISION NOT NULL,
    building_area_m2   DOUBLE PRECISION,
    floor_area_ratio   DOUBLE PRECISION,
    coverage_ratio     DOUBLE PRECISION,
    num_buildings      INTEGER DEFAULT 0,
    num_units          INTEGER DEFAULT 0,
    floors             INTEGER,
    year_built         INTEGER,

    assessed_value     NUMERIC(14,2),
    land_value         NUMERIC(14,2),
    improvement_value  NUMERIC(14,2),
    value_per_m2       DOUBLE PRECISION,
    last_sale_date     DATE,
    last_sale_price    NUMERIC(14,2),
    tax_exempt         BOOLEAN NOT NULL DEFAULT FALSE,

    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    geom               geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX parcels_geom_idx     ON parcel.parcels USING GIST (geom);
CREATE INDEX parcels_landuse_idx  ON parcel.parcels (land_use);
CREATE INDEX parcels_value_idx    ON parcel.parcels (assessed_value);
CREATE INDEX parcels_zone_idx     ON parcel.parcels (zone_code);
CREATE INDEX parcels_year_idx     ON parcel.parcels (year_built);

-- LINESTRING layer: legal boundary edges + easements/rights of way
CREATE TABLE parcel.boundary_lines (
    id             SERIAL PRIMARY KEY,
    parcel_pin     TEXT,
    boundary_type  TEXT NOT NULL,   -- lot_line | easement | right_of_way | setback | disputed
    survey_date    DATE,
    length_m       DOUBLE PRECISION,
    is_disputed    BOOLEAN NOT NULL DEFAULT FALSE,
    geom           geometry(MultiLineString, 4326) NOT NULL
);
CREATE INDEX boundary_geom_idx ON parcel.boundary_lines USING GIST (geom);
CREATE INDEX boundary_type_idx ON parcel.boundary_lines (boundary_type);

-- Sale history driving the D3 price-trend chart
CREATE TABLE parcel.sales_history (
    id          BIGSERIAL PRIMARY KEY,
    parcel_id   INTEGER NOT NULL REFERENCES parcel.parcels(id) ON DELETE CASCADE,
    sale_date   DATE NOT NULL,
    sale_price  NUMERIC(14,2) NOT NULL,
    price_per_m2 DOUBLE PRECISION,
    buyer_type  TEXT
);
CREATE INDEX sales_parcel_date_idx ON parcel.sales_history (parcel_id, sale_date);
CREATE INDEX sales_date_idx        ON parcel.sales_history (sale_date);
