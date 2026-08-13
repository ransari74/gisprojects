-- ---------------------------------------------------------------------------
-- PROJECT 5 -- 3D TERRAIN + CITY MODEL
--
-- Building footprints with height/level attributes for MapLibre
-- fill-extrusion, terrain contours from Copernicus DEM, and a viewshed /
-- solar-exposure analysis layer.
--
-- Geometry mix: POLYGON (buildings, viewsheds) + LINESTRING (contours, ridges)
-- ---------------------------------------------------------------------------

CREATE TABLE terrain.buildings (
    id             SERIAL PRIMARY KEY,
    osm_id         BIGINT,
    name           TEXT,
    building_type  TEXT NOT NULL,   -- residential | commercial | office | industrial | retail | civic | school | hospital
    levels         SMALLINT,
    height_m       DOUBLE PRECISION NOT NULL,
    min_height_m   DOUBLE PRECISION NOT NULL DEFAULT 0,
    -- terrain elevation at the footprint centroid; MapLibre needs
    -- fill-extrusion-base offset by this when draped over 3D terrain
    ground_elev_m  DOUBLE PRECISION,
    roof_shape     TEXT,            -- flat | gabled | hipped | pyramidal | dome
    roof_color     TEXT,
    footprint_m2   DOUBLE PRECISION,
    volume_m3      DOUBLE PRECISION,
    year_built     INTEGER,
    -- analytics
    solar_potential_kwh_m2 DOUBLE PRECISION,
    shadow_index   DOUBLE PRECISION,   -- 0 fully sunlit .. 1 fully shaded at noon
    energy_class   TEXT,               -- A..G
    geom           geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX buildings_geom_idx   ON terrain.buildings USING GIST (geom);
CREATE INDEX buildings_height_idx ON terrain.buildings (height_m DESC);
CREATE INDEX buildings_type_idx   ON terrain.buildings (building_type);

-- LINESTRING layer: DEM-derived contours
CREATE TABLE terrain.contours (
    id           SERIAL PRIMARY KEY,
    elevation_m  DOUBLE PRECISION NOT NULL,
    interval_m   SMALLINT NOT NULL DEFAULT 10,
    is_index     BOOLEAN NOT NULL DEFAULT FALSE,  -- every 5th contour, drawn heavier
    geom         geometry(MultiLineString, 4326) NOT NULL
);
CREATE INDEX contours_geom_idx ON terrain.contours USING GIST (geom);
CREATE INDEX contours_elev_idx ON terrain.contours (elevation_m);

-- LINESTRING layer: hydrology / ridge lines derived from the DEM
CREATE TABLE terrain.drainage_lines (
    id            SERIAL PRIMARY KEY,
    name          TEXT,
    line_type     TEXT NOT NULL,     -- stream | river | ridge | valley
    stream_order  SMALLINT,
    length_m      DOUBLE PRECISION,
    slope_pct     DOUBLE PRECISION,
    geom          geometry(MultiLineString, 4326) NOT NULL
);
CREATE INDEX drainage_geom_idx ON terrain.drainage_lines USING GIST (geom);

-- POLYGON layer: elevation bands for the hypsometric tint + D3 area chart
CREATE TABLE terrain.elevation_bands (
    id          SERIAL PRIMARY KEY,
    band_min_m  DOUBLE PRECISION NOT NULL,
    band_max_m  DOUBLE PRECISION NOT NULL,
    label       TEXT NOT NULL,
    color_hex   TEXT NOT NULL,
    area_km2    DOUBLE PRECISION,
    geom        geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX elev_bands_geom_idx ON terrain.elevation_bands USING GIST (geom);

-- Skyline profile samples backing the D3 elevation-transect chart
CREATE TABLE terrain.elevation_profile (
    id           BIGSERIAL PRIMARY KEY,
    transect_id  TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    distance_m   DOUBLE PRECISION NOT NULL,
    elevation_m  DOUBLE PRECISION NOT NULL,
    surface_elev_m DOUBLE PRECISION,   -- terrain + buildings
    geom         geometry(Point, 4326) NOT NULL,
    UNIQUE (transect_id, seq)
);
CREATE INDEX elev_profile_transect_idx ON terrain.elevation_profile (transect_id, seq);
