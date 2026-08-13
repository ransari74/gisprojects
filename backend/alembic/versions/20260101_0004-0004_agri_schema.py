"""Agriculture schema

Project 1. Field parcels with SoilGrids chemistry and WorldCover land cover
(POLYGON), the irrigation network (LINESTRING), ground-truth samples (POINT)
and a per-field NDVI series.

Revision ID: 0004
Revises: 0003
Create Date: 2026-01-01 00:04:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "agri"


def upgrade() -> None:
    op.create_table('fields',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('field_code', sa.Text(), nullable=False),
    sa.Column('farm_name', sa.Text(), nullable=True),
    sa.Column('crop_type', sa.Text(), nullable=False),
    sa.Column('crop_year', sa.Integer(), nullable=False),
    sa.Column('area_ha', sa.Float(), nullable=False),
    sa.Column('irrigated', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('organic', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('soil_ph', sa.Float(), nullable=True),
    sa.Column('soil_organic_c', sa.Float(), nullable=True),
    sa.Column('soil_nitrogen', sa.Float(), nullable=True),
    sa.Column('soil_clay_pct', sa.Float(), nullable=True),
    sa.Column('soil_sand_pct', sa.Float(), nullable=True),
    sa.Column('soil_silt_pct', sa.Float(), nullable=True),
    sa.Column('soil_texture', sa.Text(), nullable=True),
    sa.Column('landcover_class', sa.Text(), nullable=True),
    sa.Column('landcover_code', sa.Integer(), nullable=True),
    sa.Column('ndvi_mean', sa.Float(), nullable=True),
    sa.Column('ndvi_max', sa.Float(), nullable=True),
    sa.Column('ndvi_stddev', sa.Float(), nullable=True),
    sa.Column('elevation_m', sa.Float(), nullable=True),
    sa.Column('slope_deg', sa.Float(), nullable=True),
    sa.Column('yield_t_ha', sa.Float(), nullable=True),
    sa.Column('yield_class', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('field_code'),
    schema='agri'
    )
    op.create_index(op.f('ix_agri_fields_crop_type'), 'fields', ['crop_type'], unique=False, schema='agri')
    op.create_index(op.f('ix_agri_fields_crop_year'), 'fields', ['crop_year'], unique=False, schema='agri')
    op.create_index(op.f('ix_agri_fields_yield_t_ha'), 'fields', ['yield_t_ha'], unique=False, schema='agri')
    op.create_table('irrigation_canals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('canal_code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('canal_type', sa.Text(), nullable=False),
    sa.Column('lined', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('capacity_m3s', sa.Float(), nullable=True),
    sa.Column('length_m', sa.Float(), nullable=True),
    sa.Column('condition', sa.Text(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTILINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('canal_code'),
    schema='agri'
    )
    op.create_index(op.f('ix_agri_irrigation_canals_canal_type'), 'irrigation_canals', ['canal_type'], unique=False, schema='agri')
    op.create_table('soil_samples',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sample_code', sa.Text(), nullable=False),
    sa.Column('sampled_on', sa.Date(), nullable=True),
    sa.Column('depth_cm', sa.Integer(), nullable=True),
    sa.Column('ph', sa.Float(), nullable=True),
    sa.Column('organic_c', sa.Float(), nullable=True),
    sa.Column('nitrogen', sa.Float(), nullable=True),
    sa.Column('phosphorus', sa.Float(), nullable=True),
    sa.Column('potassium', sa.Float(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('sample_code'),
    schema='agri'
    )
    op.create_table('field_ndvi_timeseries',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('field_id', sa.Integer(), nullable=False),
    sa.Column('obs_date', sa.Date(), nullable=False),
    sa.Column('ndvi', sa.Float(), nullable=False),
    sa.Column('cloud_pct', sa.Float(), nullable=True),
    sa.ForeignKeyConstraint(['field_id'], ['agri.fields.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('field_id', 'obs_date', name='ndvi_ts_field_date_key'),
    schema='agri'
    )
    op.create_index(op.f('ix_agri_field_ndvi_timeseries_field_id'), 'field_ndvi_timeseries', ['field_id'], unique=False, schema='agri')


def downgrade() -> None:
    op.drop_table("field_ndvi_timeseries", schema=SCHEMA)
    op.drop_table("soil_samples", schema=SCHEMA)
    op.drop_table("irrigation_canals", schema=SCHEMA)
    op.drop_table("fields", schema=SCHEMA)

