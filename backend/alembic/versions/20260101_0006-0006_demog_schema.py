"""Demographics schema

Project 3. Census tracts and a population grid (POLYGON), origin-destination
commute desire lines (LINESTRING), and the age/sex breakdown.

Revision ID: 0006
Revises: 0005
Create Date: 2026-01-01 00:06:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "demog"


def upgrade() -> None:
    op.create_table('census_tracts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tract_code', sa.Text(), nullable=False),
    sa.Column('tract_name', sa.Text(), nullable=True),
    sa.Column('district', sa.Text(), nullable=True),
    sa.Column('population', sa.Integer(), nullable=False),
    sa.Column('households', sa.Integer(), nullable=True),
    sa.Column('avg_household_size', sa.Float(), nullable=True),
    sa.Column('area_km2', sa.Float(), nullable=False),
    sa.Column('density_km2', sa.Float(), nullable=True),
    sa.Column('pct_under_15', sa.Float(), nullable=True),
    sa.Column('pct_15_29', sa.Float(), nullable=True),
    sa.Column('pct_30_44', sa.Float(), nullable=True),
    sa.Column('pct_45_64', sa.Float(), nullable=True),
    sa.Column('pct_65_plus', sa.Float(), nullable=True),
    sa.Column('median_age', sa.Float(), nullable=True),
    sa.Column('median_income', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('unemployment_rate', sa.Float(), nullable=True),
    sa.Column('pct_tertiary_educated', sa.Float(), nullable=True),
    sa.Column('pct_foreign_born', sa.Float(), nullable=True),
    sa.Column('dwellings', sa.Integer(), nullable=True),
    sa.Column('pct_owner_occupied', sa.Float(), nullable=True),
    sa.Column('pct_vacant', sa.Float(), nullable=True),
    sa.Column('median_rent', sa.Numeric(precision=10, scale=2), nullable=True),
    sa.Column('deprivation_index', sa.Float(), nullable=True),
    sa.Column('census_year', sa.Integer(), server_default='2021', nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tract_code'),
    schema='demog'
    )
    op.create_index(op.f('ix_demog_census_tracts_density_km2'), 'census_tracts', ['density_km2'], unique=False, schema='demog')
    op.create_index(op.f('ix_demog_census_tracts_median_income'), 'census_tracts', ['median_income'], unique=False, schema='demog')
    op.create_table('commute_flows',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('origin_code', sa.Text(), nullable=False),
    sa.Column('dest_code', sa.Text(), nullable=False),
    sa.Column('trips', sa.Integer(), nullable=False),
    sa.Column('mode', sa.Text(), nullable=False),
    sa.Column('avg_duration_min', sa.Float(), nullable=True),
    sa.Column('distance_km', sa.Float(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='LINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('origin_code', 'dest_code', 'mode', name='commute_flows_od_mode_key'),
    schema='demog'
    )
    op.create_index(op.f('ix_demog_commute_flows_trips'), 'commute_flows', ['trips'], unique=False, schema='demog')
    op.create_table('population_grid',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cell_id', sa.Text(), nullable=False),
    sa.Column('population', sa.Float(), nullable=False),
    sa.Column('resolution_m', sa.Integer(), server_default='500', nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('cell_id'),
    schema='demog'
    )
    op.create_index(op.f('ix_demog_population_grid_population'), 'population_grid', ['population'], unique=False, schema='demog')
    op.create_table('age_structure',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('tract_id', sa.Integer(), nullable=False),
    sa.Column('age_band', sa.Text(), nullable=False),
    sa.Column('band_order', sa.SmallInteger(), nullable=False),
    sa.Column('male', sa.Integer(), nullable=False),
    sa.Column('female', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['tract_id'], ['demog.census_tracts.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('tract_id', 'age_band', name='age_structure_tract_band_key'),
    schema='demog'
    )
    op.create_index(op.f('ix_demog_age_structure_tract_id'), 'age_structure', ['tract_id'], unique=False, schema='demog')


def downgrade() -> None:
    op.drop_table("age_structure", schema=SCHEMA)
    op.drop_table("population_grid", schema=SCHEMA)
    op.drop_table("commute_flows", schema=SCHEMA)
    op.drop_table("census_tracts", schema=SCHEMA)

