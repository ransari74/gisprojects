-- ---------------------------------------------------------------------------
-- PROJECT 3 -- DEMOGRAPHICS
--
-- Census tract style polygons with population structure, income and housing,
-- plus origin-destination commute flows rendered as lines.
--
-- Geometry mix: POLYGON (census tracts, population hex grid)
--               + LINESTRING (commute desire lines)
-- ---------------------------------------------------------------------------

CREATE TABLE demog.census_tracts (
    id              SERIAL PRIMARY KEY,
    tract_code      TEXT UNIQUE NOT NULL,
    tract_name      TEXT,
    district        TEXT,

    population      INTEGER NOT NULL,
    households      INTEGER,
    avg_household_size DOUBLE PRECISION,
    area_km2        DOUBLE PRECISION NOT NULL,
    density_km2     DOUBLE PRECISION,

    -- age structure (percentages, sum ~100)
    pct_under_15    DOUBLE PRECISION,
    pct_15_29       DOUBLE PRECISION,
    pct_30_44       DOUBLE PRECISION,
    pct_45_64       DOUBLE PRECISION,
    pct_65_plus     DOUBLE PRECISION,
    median_age      DOUBLE PRECISION,

    -- socio-economic
    median_income        NUMERIC(12,2),
    unemployment_rate    DOUBLE PRECISION,
    pct_tertiary_educated DOUBLE PRECISION,
    pct_foreign_born     DOUBLE PRECISION,

    -- housing
    dwellings        INTEGER,
    pct_owner_occupied DOUBLE PRECISION,
    pct_vacant       DOUBLE PRECISION,
    median_rent      NUMERIC(10,2),

    -- derived composite index, 0-100, used for the choropleth default
    deprivation_index DOUBLE PRECISION,

    census_year     INTEGER NOT NULL DEFAULT 2021,
    geom            geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX tracts_geom_idx    ON demog.census_tracts USING GIST (geom);
CREATE INDEX tracts_density_idx ON demog.census_tracts (density_km2);
CREATE INDEX tracts_income_idx  ON demog.census_tracts (median_income);

-- Fine-grained population grid (Kontur / GHS-POP style) for the heat layer
CREATE TABLE demog.population_grid (
    id          SERIAL PRIMARY KEY,
    cell_id     TEXT UNIQUE NOT NULL,
    population  DOUBLE PRECISION NOT NULL,
    resolution_m INTEGER NOT NULL DEFAULT 500,
    geom        geometry(Polygon, 4326) NOT NULL
);
CREATE INDEX popgrid_geom_idx ON demog.population_grid USING GIST (geom);
CREATE INDEX popgrid_pop_idx  ON demog.population_grid (population);

-- LINESTRING layer: origin-destination desire lines
CREATE TABLE demog.commute_flows (
    id            SERIAL PRIMARY KEY,
    origin_code   TEXT NOT NULL,
    dest_code     TEXT NOT NULL,
    trips         INTEGER NOT NULL,
    mode          TEXT NOT NULL,        -- car | transit | bike | walk
    avg_duration_min DOUBLE PRECISION,
    distance_km   DOUBLE PRECISION,
    geom          geometry(LineString, 4326) NOT NULL,
    UNIQUE (origin_code, dest_code, mode)
);
CREATE INDEX flows_geom_idx  ON demog.commute_flows USING GIST (geom);
CREATE INDEX flows_trips_idx ON demog.commute_flows (trips DESC);

-- Age/sex pyramid source for the D3 population-pyramid chart
CREATE TABLE demog.age_structure (
    id         BIGSERIAL PRIMARY KEY,
    tract_id   INTEGER NOT NULL REFERENCES demog.census_tracts(id) ON DELETE CASCADE,
    age_band   TEXT NOT NULL,     -- '0-4', '5-9', ... '85+'
    band_order SMALLINT NOT NULL,
    male       INTEGER NOT NULL,
    female     INTEGER NOT NULL,
    UNIQUE (tract_id, age_band)
);
CREATE INDEX age_structure_tract_idx ON demog.age_structure (tract_id, band_order);
