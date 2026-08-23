"""Remote sensing schema

Project 6. The earth-observation side of the portfolio: a scene catalogue
(POLYGON footprints), a raster-derived analysis grid carrying spectral indices
and land surface temperature (POLYGON), detected land-cover change areas
(POLYGON), InSAR persistent-scatterer velocities (POINT), deformation profiles
along infrastructure corridors (LINESTRING), SAR-derived water extent
(POLYGON), and a non-spatial index time series.

The grid is the piece that makes this work without a raster stack. Real
workflows zonal-summarise rasters onto a vector geometry sooner or later --
doing that once at load time is what lets the whole project ship as MVT like
every other layer, instead of needing a separate raster tile server.

Revision ID: 0010
Revises: 0009
Create Date: 2026-01-01 00:10:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "rs"


def upgrade() -> None:
    # 0001 predates this project, so the schema is created here rather than
    # amended into that revision -- a migration that has already run on a
    # deployed database must never be edited in place.
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    # ---------------------------------------------------------------- scenes
    op.create_table(
        "scenes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scene_id", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("sensor", sa.Text(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cloud_pct", sa.Float(), nullable=False),
        sa.Column("sun_elevation_deg", sa.Float(), nullable=True),
        sa.Column("orbit_direction", sa.Text(), nullable=True),
        sa.Column("processing_level", sa.Text(), nullable=True),
        sa.Column("resolution_m", sa.Float(), nullable=True),
        sa.Column("usable", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON", srid=4326, from_text="ST_GeomFromEWKT",
                name="geometry", nullable=False,
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scene_id", name="uq_rs_scenes_scene_id"),
        schema=SCHEMA,
    )
    op.create_index(op.f("ix_rs_scenes_platform"), "scenes", ["platform"], schema=SCHEMA)
    op.create_index(op.f("ix_rs_scenes_acquired_at"), "scenes", ["acquired_at"], schema=SCHEMA)

    # ----------------------------------------------------------- index cells
    op.create_table(
        "index_cells",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cell_code", sa.Text(), nullable=False),
        sa.Column("ndvi", sa.Float(), nullable=False),
        sa.Column("ndwi", sa.Float(), nullable=False),
        sa.Column("ndbi", sa.Float(), nullable=False),
        sa.Column("nbr", sa.Float(), nullable=True),
        sa.Column("lst_c", sa.Float(), nullable=False),
        sa.Column("lst_anomaly_c", sa.Float(), nullable=False),
        sa.Column("albedo", sa.Float(), nullable=True),
        sa.Column("landcover_class", sa.Text(), nullable=False),
        sa.Column("landcover_prev", sa.Text(), nullable=False),
        sa.Column("changed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("imperviousness_pct", sa.Float(), nullable=True),
        sa.Column("tree_cover_pct", sa.Float(), nullable=True),
        sa.Column("ndvi_delta", sa.Float(), nullable=True),
        sa.Column("area_ha", sa.Float(), nullable=True),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON", srid=4326, from_text="ST_GeomFromEWKT",
                name="geometry", nullable=False,
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cell_code", name="uq_rs_index_cells_cell_code"),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_rs_index_cells_landcover_class"), "index_cells", ["landcover_class"], schema=SCHEMA
    )
    op.create_index(op.f("ix_rs_index_cells_ndvi"), "index_cells", ["ndvi"], schema=SCHEMA)
    op.create_index(op.f("ix_rs_index_cells_lst_c"), "index_cells", ["lst_c"], schema=SCHEMA)
    op.create_index(op.f("ix_rs_index_cells_changed"), "index_cells", ["changed"], schema=SCHEMA)

    # ------------------------------------------------------- change polygons
    op.create_table(
        "change_polygons",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("change_code", sa.Text(), nullable=False),
        sa.Column("from_class", sa.Text(), nullable=False),
        sa.Column("to_class", sa.Text(), nullable=False),
        sa.Column("change_type", sa.Text(), nullable=False),
        sa.Column("detected_year", sa.SmallInteger(), nullable=False),
        sa.Column("baseline_year", sa.SmallInteger(), nullable=False),
        sa.Column("area_ha", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("ndvi_delta", sa.Float(), nullable=True),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON", srid=4326, from_text="ST_GeomFromEWKT",
                name="geometry", nullable=False,
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_rs_change_polygons_change_type"), "change_polygons", ["change_type"], schema=SCHEMA
    )
    op.create_index(
        op.f("ix_rs_change_polygons_detected_year"), "change_polygons", ["detected_year"], schema=SCHEMA
    )

    # ---------------------------------------------------- subsidence (InSAR)
    op.create_table(
        "subsidence_points",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ps_id", sa.Text(), nullable=False),
        # Negative is downward, matching the sign convention InSAR products
        # ship with -- storing it any other way invites a sign error the first
        # time somebody compares this against a published velocity map.
        sa.Column("velocity_mm_yr", sa.Float(), nullable=False),
        sa.Column("cumulative_mm", sa.Float(), nullable=False),
        sa.Column("coherence", sa.Float(), nullable=False),
        sa.Column("std_mm_yr", sa.Float(), nullable=True),
        sa.Column("height_m", sa.Float(), nullable=True),
        sa.Column("soil_type", sa.Text(), nullable=False),
        sa.Column("land_use", sa.Text(), nullable=True),
        sa.Column("risk_class", sa.Text(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="POINT", srid=4326, from_text="ST_GeomFromEWKT",
                name="geometry", nullable=False,
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ps_id", name="uq_rs_subsidence_points_ps_id"),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_rs_subsidence_points_soil_type"), "subsidence_points", ["soil_type"], schema=SCHEMA
    )
    op.create_index(
        op.f("ix_rs_subsidence_points_velocity_mm_yr"),
        "subsidence_points", ["velocity_mm_yr"], schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_rs_subsidence_points_risk_class"), "subsidence_points", ["risk_class"], schema=SCHEMA
    )

    # ---------------------------------------------------- deformation profiles
    op.create_table(
        "deformation_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("length_m", sa.Float(), nullable=False),
        sa.Column("mean_velocity_mm_yr", sa.Float(), nullable=False),
        sa.Column("min_velocity_mm_yr", sa.Float(), nullable=False),
        # Uniform settlement is tolerable; it is the *difference* along a
        # structure that cracks it. This is the number an asset manager acts on.
        sa.Column("differential_mm_yr", sa.Float(), nullable=False),
        sa.Column("ps_count", sa.Integer(), nullable=True),
        sa.Column("dominant_soil", sa.Text(), nullable=True),
        sa.Column("risk_class", sa.Text(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="MULTILINESTRING", srid=4326, from_text="ST_GeomFromEWKT",
                name="geometry", nullable=False,
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_code", name="uq_rs_deformation_profiles_code"),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_rs_deformation_profiles_asset_type"),
        "deformation_profiles", ["asset_type"], schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_rs_deformation_profiles_risk_class"),
        "deformation_profiles", ["risk_class"], schema=SCHEMA,
    )

    # ----------------------------------------------------------- water extent
    op.create_table(
        "water_extent",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("water_type", sa.Text(), nullable=False),
        sa.Column("area_ha", sa.Float(), nullable=False),
        sa.Column("backscatter_db", sa.Float(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "geom",
            geoalchemy2.types.Geometry(
                geometry_type="MULTIPOLYGON", srid=4326, from_text="ST_GeomFromEWKT",
                name="geometry", nullable=False,
            ),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_rs_water_extent_water_type"), "water_extent", ["water_type"], schema=SCHEMA
    )
    op.create_index(
        op.f("ix_rs_water_extent_observed_on"), "water_extent", ["observed_on"], schema=SCHEMA
    )

    # ------------------------------------------------------- index timeseries
    op.create_table(
        "index_timeseries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("observed_on", sa.Date(), nullable=False),
        sa.Column("landcover_class", sa.Text(), nullable=False),
        sa.Column("index_name", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("p10", sa.Float(), nullable=True),
        sa.Column("p90", sa.Float(), nullable=True),
        sa.Column("sample_n", sa.Integer(), nullable=True),
        sa.Column("cloud_pct", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "observed_on", "landcover_class", "index_name", name="uq_rs_index_timeseries_obs"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        op.f("ix_rs_index_timeseries_index_name"), "index_timeseries", ["index_name"], schema=SCHEMA
    )


def downgrade() -> None:
    op.drop_table("index_timeseries", schema=SCHEMA)
    op.drop_table("water_extent", schema=SCHEMA)
    op.drop_table("deformation_profiles", schema=SCHEMA)
    op.drop_table("subsidence_points", schema=SCHEMA)
    op.drop_table("change_polygons", schema=SCHEMA)
    op.drop_table("index_cells", schema=SCHEMA)
    op.drop_table("scenes", schema=SCHEMA)
    op.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
