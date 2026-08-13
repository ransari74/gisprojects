"""3D terrain schema

Project 5. Building footprints with height attributes and elevation bands
(POLYGON), DEM contours and hydrology (LINESTRING), and transect samples.

Revision ID: 0008
Revises: 0007
Create Date: 2026-01-01 00:08:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "terrain"


def upgrade() -> None:
    op.create_table('buildings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('osm_id', sa.BigInteger(), nullable=True),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('building_type', sa.Text(), nullable=False),
    sa.Column('levels', sa.SmallInteger(), nullable=True),
    sa.Column('height_m', sa.Float(), nullable=False),
    sa.Column('min_height_m', sa.Float(), server_default='0', nullable=False),
    sa.Column('ground_elev_m', sa.Float(), nullable=True),
    sa.Column('roof_shape', sa.Text(), nullable=True),
    sa.Column('roof_color', sa.Text(), nullable=True),
    sa.Column('footprint_m2', sa.Float(), nullable=True),
    sa.Column('volume_m3', sa.Float(), nullable=True),
    sa.Column('year_built', sa.Integer(), nullable=True),
    sa.Column('solar_potential_kwh_m2', sa.Float(), nullable=True),
    sa.Column('shadow_index', sa.Float(), nullable=True),
    sa.Column('energy_class', sa.String(length=1), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='terrain'
    )
    op.create_index(op.f('ix_terrain_buildings_building_type'), 'buildings', ['building_type'], unique=False, schema='terrain')
    op.create_index(op.f('ix_terrain_buildings_height_m'), 'buildings', ['height_m'], unique=False, schema='terrain')
    op.create_table('contours',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('elevation_m', sa.Float(), nullable=False),
    sa.Column('interval_m', sa.SmallInteger(), server_default='10', nullable=False),
    sa.Column('is_index', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTILINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='terrain'
    )
    op.create_index(op.f('ix_terrain_contours_elevation_m'), 'contours', ['elevation_m'], unique=False, schema='terrain')
    op.create_table('drainage_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('line_type', sa.Text(), nullable=False),
    sa.Column('stream_order', sa.SmallInteger(), nullable=True),
    sa.Column('length_m', sa.Float(), nullable=True),
    sa.Column('slope_pct', sa.Float(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTILINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='terrain'
    )
    op.create_table('elevation_bands',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('band_min_m', sa.Float(), nullable=False),
    sa.Column('band_max_m', sa.Float(), nullable=False),
    sa.Column('label', sa.Text(), nullable=False),
    sa.Column('color_hex', sa.Text(), nullable=False),
    sa.Column('area_km2', sa.Float(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='terrain'
    )
    op.create_table('elevation_profile',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('transect_id', sa.Text(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('distance_m', sa.Float(), nullable=False),
    sa.Column('elevation_m', sa.Float(), nullable=False),
    sa.Column('surface_elev_m', sa.Float(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('transect_id', 'seq', name='elevation_profile_transect_seq_key'),
    schema='terrain'
    )


def downgrade() -> None:
    op.drop_table("elevation_profile", schema=SCHEMA)
    op.drop_table("elevation_bands", schema=SCHEMA)
    op.drop_table("drainage_lines", schema=SCHEMA)
    op.drop_table("contours", schema=SCHEMA)
    op.drop_table("buildings", schema=SCHEMA)

