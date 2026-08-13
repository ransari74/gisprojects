"""Cadastre schema

Project 2. Zoning districts and cadastral parcels (POLYGON), legal boundary
lines and easements (LINESTRING), and transaction history.

Revision ID: 0005
Revises: 0004
Create Date: 2026-01-01 00:05:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "parcel"


def upgrade() -> None:
    op.create_table('boundary_lines',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('parcel_pin', sa.Text(), nullable=True),
    sa.Column('boundary_type', sa.Text(), nullable=False),
    sa.Column('survey_date', sa.Date(), nullable=True),
    sa.Column('length_m', sa.Float(), nullable=True),
    sa.Column('is_disputed', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTILINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='parcel'
    )
    op.create_index(op.f('ix_parcel_boundary_lines_boundary_type'), 'boundary_lines', ['boundary_type'], unique=False, schema='parcel')
    op.create_table('zoning_districts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('zone_code', sa.Text(), nullable=False),
    sa.Column('zone_name', sa.Text(), nullable=False),
    sa.Column('zone_category', sa.Text(), nullable=False),
    sa.Column('max_far', sa.Float(), nullable=True),
    sa.Column('max_height_m', sa.Float(), nullable=True),
    sa.Column('min_lot_m2', sa.Float(), nullable=True),
    sa.Column('adopted_on', sa.Date(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='parcel'
    )
    op.create_index(op.f('ix_parcel_zoning_districts_zone_category'), 'zoning_districts', ['zone_category'], unique=False, schema='parcel')
    op.create_table('parcels',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('parcel_pin', sa.Text(), nullable=False),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('district', sa.Text(), nullable=True),
    sa.Column('zone_code', sa.Text(), nullable=True),
    sa.Column('zoning_district_id', sa.Integer(), nullable=True),
    sa.Column('land_use', sa.Text(), nullable=False),
    sa.Column('owner_type', sa.Text(), nullable=True),
    sa.Column('lot_area_m2', sa.Float(), nullable=False),
    sa.Column('building_area_m2', sa.Float(), nullable=True),
    sa.Column('floor_area_ratio', sa.Float(), nullable=True),
    sa.Column('coverage_ratio', sa.Float(), nullable=True),
    sa.Column('num_buildings', sa.Integer(), server_default='0', nullable=True),
    sa.Column('num_units', sa.Integer(), server_default='0', nullable=True),
    sa.Column('floors', sa.Integer(), nullable=True),
    sa.Column('year_built', sa.Integer(), nullable=True),
    sa.Column('assessed_value', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('land_value', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('improvement_value', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('value_per_m2', sa.Float(), nullable=True),
    sa.Column('last_sale_date', sa.Date(), nullable=True),
    sa.Column('last_sale_price', sa.Numeric(precision=14, scale=2), nullable=True),
    sa.Column('tax_exempt', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.ForeignKeyConstraint(['zoning_district_id'], ['parcel.zoning_districts.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('parcel_pin'),
    schema='parcel'
    )
    op.create_index(op.f('ix_parcel_parcels_assessed_value'), 'parcels', ['assessed_value'], unique=False, schema='parcel')
    op.create_index(op.f('ix_parcel_parcels_land_use'), 'parcels', ['land_use'], unique=False, schema='parcel')
    op.create_index(op.f('ix_parcel_parcels_year_built'), 'parcels', ['year_built'], unique=False, schema='parcel')
    op.create_index(op.f('ix_parcel_parcels_zone_code'), 'parcels', ['zone_code'], unique=False, schema='parcel')
    op.create_table('sales_history',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('parcel_id', sa.Integer(), nullable=False),
    sa.Column('sale_date', sa.Date(), nullable=False),
    sa.Column('sale_price', sa.Numeric(precision=14, scale=2), nullable=False),
    sa.Column('price_per_m2', sa.Float(), nullable=True),
    sa.Column('buyer_type', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['parcel_id'], ['parcel.parcels.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    schema='parcel'
    )
    op.create_index(op.f('ix_parcel_sales_history_parcel_id'), 'sales_history', ['parcel_id'], unique=False, schema='parcel')
    op.create_index(op.f('ix_parcel_sales_history_sale_date'), 'sales_history', ['sale_date'], unique=False, schema='parcel')


def downgrade() -> None:
    op.drop_table("sales_history", schema=SCHEMA)
    op.drop_table("parcels", schema=SCHEMA)
    op.drop_table("zoning_districts", schema=SCHEMA)
    op.drop_table("boundary_lines", schema=SCHEMA)

