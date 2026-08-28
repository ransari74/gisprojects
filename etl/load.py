"""Load generated (or downloaded) rows into PostGIS.

    python -m etl.load --generate          # synthetic Utrecht data, no network
    python -m etl.load --generate --truncate
    python -m etl.load --stats             # row counts only

Geometry columns arrive as WKT strings and are converted with ST_GeomFromText
on the way in, so the generator never needs a PostGIS connection to build them.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime

import psycopg
from psycopg import sql

from etl.config import DATABASE_URL, DATASETS

# Insert order matters: children reference parents by serial id, and the
# generator assumes ids are assigned 1..N in insertion order.
LOAD_ORDER = [
    "meta.study_area",
    "agri.fields",
    "agri.irrigation_canals",
    "agri.soil_samples",
    "agri.field_ndvi_timeseries",
    "agri.field_embeddings",
    "parcel.zoning_districts",
    "parcel.parcels",
    "parcel.boundary_lines",
    "parcel.sales_history",
    "demog.census_tracts",
    "demog.age_structure",
    "demog.commute_flows",
    "demog.population_grid",
    "transport.road_segments",
    "transport.transit_routes",
    "transport.transit_stops",
    "transport.isochrones",
    "transport.traffic_counts",
    "terrain.buildings",
    "terrain.contours",
    "terrain.drainage_lines",
    "terrain.elevation_bands",
    "terrain.elevation_profile",
    "rs.scenes",
    "rs.index_cells",
    "rs.change_polygons",
    "rs.subsidence_points",
    "rs.deformation_profiles",
    "rs.water_extent",
    "rs.index_timeseries",
]

# Truncate in reverse dependency order.
TRUNCATE_ORDER = list(reversed(LOAD_ORDER))

GEOM_COLUMNS = {"geom"}


def _split_qualified(table: str) -> tuple[str, str]:
    schema, _, name = table.partition(".")
    return schema, name


def insert_rows(conn: psycopg.Connection, table: str, rows: list[dict], batch: int = 500) -> int:
    if not rows:
        return 0

    schema, name = _split_qualified(table)
    columns = list(rows[0].keys())

    # Geometry columns need ST_GeomFromText(%s, 4326); everything else is a
    # plain placeholder. Build the VALUES template once.
    placeholders = sql.SQL(", ").join(
        sql.SQL("ST_GeomFromText(%s, 4326)") if c in GEOM_COLUMNS else sql.Placeholder()
        for c in columns
    )
    stmt = sql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
        sql.Identifier(schema),
        sql.Identifier(name),
        sql.SQL(", ").join(sql.Identifier(c) for c in columns),
        placeholders,
    )

    inserted = 0
    with conn.cursor() as cur:
        for start in range(0, len(rows), batch):
            chunk = rows[start : start + batch]
            cur.executemany(stmt, [[row[c] for c in columns] for row in chunk])
            inserted += len(chunk)
    return inserted


def truncate_all(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        for table in TRUNCATE_ORDER:
            schema, name = _split_qualified(table)
            cur.execute(
                sql.SQL("TRUNCATE TABLE {}.{} RESTART IDENTITY CASCADE").format(
                    sql.Identifier(schema), sql.Identifier(name)
                )
            )
    conn.commit()


#: Layers actually fetched from OSM Overpass under --real, whose registered
#: Dataset entry (Geofabrik PBF / 3DBAG) describes a different, heavier
#: pipeline than what this run used. `dataset_name` is intentionally NOT
#: overridden here -- it's part of the ON CONFLICT key in record_sources, so
#: changing it on a --real run would leave the old row stranded instead of
#: updating it; the actual source is called out in the notes instead.
OSM_OVERRIDE = {
    "agri_canals": ("OpenStreetMap contributors", "ODbL-1.0", "https://overpass-api.de/api/interpreter"),
    "transport_roads": ("OpenStreetMap contributors", "ODbL-1.0", "https://overpass-api.de/api/interpreter"),
    "terrain_buildings": ("OpenStreetMap contributors", "ODbL-1.0", "https://overpass-api.de/api/interpreter"),
}


def record_sources(conn: psycopg.Connection, counts: dict[str, int], real_layers: set[str]) -> None:
    """Populate meta.dataset_source so the frontend's provenance panel is
    generated from the same registry the ETL used. `real_layers` names which
    layers this run fetched from a real open source rather than synthesizing."""
    layer_to_table = {
        "agri_fields": "agri.fields",
        "agri_canals": "agri.irrigation_canals",
        "agri_field_embeddings": "agri.field_embeddings",
        "parcel_parcels": "parcel.parcels",
        "demog_tracts": "demog.census_tracts",
        "demog_popgrid": "demog.population_grid",
        "transport_roads": "transport.road_segments",
        "transport_transit_routes": "transport.transit_routes",
        "terrain_buildings": "terrain.buildings",
        "terrain_contours": "terrain.contours",
    }
    with conn.cursor() as cur:
        for ds in DATASETS:
            table = layer_to_table.get(ds.layer)
            is_real = ds.layer in real_layers
            provider, license_, url = ds.provider, ds.license, ds.url
            if is_real and ds.layer in OSM_OVERRIDE:
                provider, license_, url = OSM_OVERRIDE[ds.layer]
                note_prefix = "Actually fetched from OSM Overpass for this run (see provider/url above), not the registered source below. "
            elif is_real:
                note_prefix = ""
            else:
                note_prefix = (
                    "SYNTHETIC STAND-IN generated by etl/generate.py -- same schema and "
                    "attribute distributions, no network required. "
                )
            cur.execute(
                """
                INSERT INTO meta.dataset_source
                    (project, layer, dataset_name, provider, license, source_url,
                     fetched_at, feature_count, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (project, layer, dataset_name) DO UPDATE SET
                    provider = EXCLUDED.provider,
                    license = EXCLUDED.license,
                    source_url = EXCLUDED.source_url,
                    fetched_at = EXCLUDED.fetched_at,
                    feature_count = EXCLUDED.feature_count,
                    notes = EXCLUDED.notes
                """,
                (
                    ds.project,
                    ds.layer,
                    ds.name,
                    provider,
                    license_,
                    url,
                    datetime.now(UTC),
                    counts.get(table) if table else None,
                    note_prefix + ds.notes,
                ),
            )
    conn.commit()


def analyze(conn: psycopg.Connection) -> None:
    """ANALYZE after a bulk load -- without it the planner has no statistics
    and the tile queries pick sequential scans over the GiST indexes."""
    with conn.cursor() as cur:
        for table in LOAD_ORDER:
            schema, name = _split_qualified(table)
            cur.execute(sql.SQL("ANALYZE {}.{}").format(sql.Identifier(schema), sql.Identifier(name)))
    conn.commit()


def table_stats(conn: psycopg.Connection) -> dict[str, int]:
    counts = {}
    with conn.cursor() as cur:
        for table in LOAD_ORDER:
            schema, name = _split_qualified(table)
            try:
                cur.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(name)
                    )
                )
                counts[table] = cur.fetchone()[0]
            except psycopg.Error:
                conn.rollback()
                counts[table] = -1
    return counts


#: Layers real_data.py loads from etl/real_boundaries/ under --real; see etl/real_data.py.
REAL_LAYERS = {"agri_fields", "agri_canals", "parcel_parcels", "transport_roads", "terrain_buildings"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Load geospatial portfolio data into PostGIS")
    parser.add_argument("--generate", action="store_true", help="Generate synthetic Utrecht data")
    parser.add_argument(
        "--real", action="store_true",
        help="Use bundled real fields/canals/parcels/roads/buildings from etl/real_boundaries/ instead of "
             "synthesizing them, falling back to synthetic per-layer for anything not yet harvested -- no network "
             "needed (run `python -m etl.real_data harvest` separately to (re)fetch the bundled files); "
             "implies --generate for everything else",
    )
    parser.add_argument("--truncate", action="store_true", help="Empty all tables first")
    parser.add_argument("--stats", action="store_true", help="Print row counts and exit")
    parser.add_argument("--database-url", default=DATABASE_URL)
    args = parser.parse_args()

    # psycopg wants the plain libpq URL, not SQLAlchemy's +asyncpg form.
    dsn = args.database_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        conn = psycopg.connect(dsn)
    except psycopg.Error as exc:
        print(f"Cannot connect to the database: {exc}", file=sys.stderr)
        return 2

    with conn:
        if args.stats:
            for table, count in table_stats(conn).items():
                marker = "MISSING" if count < 0 else f"{count:>9,}"
                print(f"  {marker}  {table}")
            return 0

        if args.truncate:
            print("Truncating all project tables...")
            truncate_all(conn)

        if not (args.generate or args.real):
            print("Nothing to do. Pass --generate, --real (or --stats).", file=sys.stderr)
            return 1

        print("Loading bundled real boundaries + generating the rest..." if args.real else "Generating synthetic Utrecht dataset...")
        t0 = time.perf_counter()
        from etl.generate import generate_all

        data = generate_all(real=args.real)
        print(f"  built in {time.perf_counter() - t0:.1f}s")

        print("Loading into PostGIS...")
        counts: dict[str, int] = {}
        t1 = time.perf_counter()
        for table in LOAD_ORDER:
            rows = data.get(table, [])
            n = insert_rows(conn, table, rows)
            conn.commit()
            counts[table] = n
            print(f"  {n:>9,}  {table}")
        print(f"  loaded in {time.perf_counter() - t1:.1f}s")

        record_sources(conn, counts, real_layers=REAL_LAYERS if args.real else set())
        print("Running ANALYZE...")
        analyze(conn)

        total = sum(counts.values())
        print(f"\nDone. {total:,} rows across {len(counts)} tables.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
