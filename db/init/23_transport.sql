-- ---------------------------------------------------------------------------
-- PROJECT 4 -- TRANSPORTATION
--
-- OSM-derived road network with traffic volumes, transit routes and stops,
-- plus accessibility isochrones.
--
-- Geometry mix: LINESTRING (roads, transit routes, cycle network)
--               + POLYGON (isochrones / service areas) + POINT (stops)
-- ---------------------------------------------------------------------------

CREATE TABLE transport.road_segments (
    id             SERIAL PRIMARY KEY,
    osm_id         BIGINT,
    name           TEXT,
    highway_class  TEXT NOT NULL,   -- motorway | trunk | primary | secondary | tertiary | residential | service | cycleway | footway
    functional_class SMALLINT,      -- 1 (highest) .. 7
    oneway         BOOLEAN NOT NULL DEFAULT FALSE,
    lanes          SMALLINT,
    maxspeed_kmh   SMALLINT,
    surface        TEXT,
    bridge         BOOLEAN NOT NULL DEFAULT FALSE,
    tunnel         BOOLEAN NOT NULL DEFAULT FALSE,
    length_m       DOUBLE PRECISION NOT NULL,

    -- traffic / performance attributes
    aadt           INTEGER,          -- annual average daily traffic
    peak_speed_kmh DOUBLE PRECISION,
    congestion_index DOUBLE PRECISION,   -- 0 free flow .. 1 gridlock
    accident_count INTEGER DEFAULT 0,
    has_bike_lane  BOOLEAN NOT NULL DEFAULT FALSE,

    geom           geometry(MultiLineString, 4326) NOT NULL
);
CREATE INDEX roads_geom_idx       ON transport.road_segments USING GIST (geom);
CREATE INDEX roads_class_idx      ON transport.road_segments (highway_class);
CREATE INDEX roads_aadt_idx       ON transport.road_segments (aadt DESC);
CREATE INDEX roads_congestion_idx ON transport.road_segments (congestion_index);

CREATE TABLE transport.transit_routes (
    id            SERIAL PRIMARY KEY,
    route_code    TEXT UNIQUE NOT NULL,
    route_name    TEXT,
    mode          TEXT NOT NULL,   -- bus | tram | metro | rail | ferry
    operator      TEXT,
    color         TEXT,
    headway_min   DOUBLE PRECISION,
    daily_ridership INTEGER,
    length_km     DOUBLE PRECISION,
    geom          geometry(MultiLineString, 4326) NOT NULL
);
CREATE INDEX transit_routes_geom_idx ON transport.transit_routes USING GIST (geom);
CREATE INDEX transit_routes_mode_idx ON transport.transit_routes (mode);

CREATE TABLE transport.transit_stops (
    id            SERIAL PRIMARY KEY,
    stop_code     TEXT UNIQUE NOT NULL,
    stop_name     TEXT,
    mode          TEXT NOT NULL,
    wheelchair_accessible BOOLEAN,
    shelter       BOOLEAN,
    daily_boardings INTEGER,
    routes_served SMALLINT,
    geom          geometry(Point, 4326) NOT NULL
);
CREATE INDEX transit_stops_geom_idx ON transport.transit_stops USING GIST (geom);

-- POLYGON layer: walk/transit accessibility bands around stops
CREATE TABLE transport.isochrones (
    id            SERIAL PRIMARY KEY,
    origin_code   TEXT NOT NULL,
    mode          TEXT NOT NULL,      -- walk | bike | car | transit
    minutes       SMALLINT NOT NULL,  -- 5 | 10 | 15 | 30
    population_reached INTEGER,
    jobs_reached  INTEGER,
    area_km2      DOUBLE PRECISION,
    geom          geometry(MultiPolygon, 4326) NOT NULL,
    UNIQUE (origin_code, mode, minutes)
);
CREATE INDEX isochrones_geom_idx ON transport.isochrones USING GIST (geom);
CREATE INDEX isochrones_lookup_idx ON transport.isochrones (mode, minutes);

-- Hourly traffic counts driving the D3 small-multiples chart
CREATE TABLE transport.traffic_counts (
    id          BIGSERIAL PRIMARY KEY,
    segment_id  INTEGER NOT NULL REFERENCES transport.road_segments(id) ON DELETE CASCADE,
    count_date  DATE NOT NULL,
    hour        SMALLINT NOT NULL CHECK (hour BETWEEN 0 AND 23),
    vehicles    INTEGER NOT NULL,
    avg_speed_kmh DOUBLE PRECISION,
    UNIQUE (segment_id, count_date, hour)
);
CREATE INDEX traffic_counts_segment_idx ON transport.traffic_counts (segment_id, count_date, hour);
