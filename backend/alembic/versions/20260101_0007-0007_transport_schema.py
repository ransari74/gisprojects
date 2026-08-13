"""Transport schema

Project 4. Road centrelines and transit alignments (LINESTRING), accessibility
isochrones (POLYGON), stops (POINT) and hourly traffic counts.

Revision ID: 0007
Revises: 0006
Create Date: 2026-01-01 00:07:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "transport"


def upgrade() -> None:
    op.create_table('isochrones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('origin_code', sa.Text(), nullable=False),
    sa.Column('mode', sa.Text(), nullable=False),
    sa.Column('minutes', sa.SmallInteger(), nullable=False),
    sa.Column('population_reached', sa.Integer(), nullable=True),
    sa.Column('jobs_reached', sa.Integer(), nullable=True),
    sa.Column('area_km2', sa.Float(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('origin_code', 'mode', 'minutes', name='isochrones_origin_mode_min_key'),
    schema='transport'
    )
    op.create_table('road_segments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('osm_id', sa.BigInteger(), nullable=True),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('highway_class', sa.Text(), nullable=False),
    sa.Column('functional_class', sa.SmallInteger(), nullable=True),
    sa.Column('oneway', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('lanes', sa.SmallInteger(), nullable=True),
    sa.Column('maxspeed_kmh', sa.SmallInteger(), nullable=True),
    sa.Column('surface', sa.Text(), nullable=True),
    sa.Column('bridge', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('tunnel', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('length_m', sa.Float(), nullable=False),
    sa.Column('aadt', sa.Integer(), nullable=True),
    sa.Column('peak_speed_kmh', sa.Float(), nullable=True),
    sa.Column('congestion_index', sa.Float(), nullable=True),
    sa.Column('accident_count', sa.Integer(), server_default='0', nullable=True),
    sa.Column('has_bike_lane', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTILINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    schema='transport'
    )
    op.create_index(op.f('ix_transport_road_segments_aadt'), 'road_segments', ['aadt'], unique=False, schema='transport')
    op.create_index(op.f('ix_transport_road_segments_congestion_index'), 'road_segments', ['congestion_index'], unique=False, schema='transport')
    op.create_index(op.f('ix_transport_road_segments_highway_class'), 'road_segments', ['highway_class'], unique=False, schema='transport')
    op.create_table('transit_routes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('route_code', sa.Text(), nullable=False),
    sa.Column('route_name', sa.Text(), nullable=True),
    sa.Column('mode', sa.Text(), nullable=False),
    sa.Column('operator', sa.Text(), nullable=True),
    sa.Column('color', sa.Text(), nullable=True),
    sa.Column('headway_min', sa.Float(), nullable=True),
    sa.Column('daily_ridership', sa.Integer(), nullable=True),
    sa.Column('length_km', sa.Float(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTILINESTRING', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('route_code'),
    schema='transport'
    )
    op.create_index(op.f('ix_transport_transit_routes_mode'), 'transit_routes', ['mode'], unique=False, schema='transport')
    op.create_table('transit_stops',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('stop_code', sa.Text(), nullable=False),
    sa.Column('stop_name', sa.Text(), nullable=True),
    sa.Column('mode', sa.Text(), nullable=False),
    sa.Column('wheelchair_accessible', sa.Boolean(), nullable=True),
    sa.Column('shelter', sa.Boolean(), nullable=True),
    sa.Column('daily_boardings', sa.Integer(), nullable=True),
    sa.Column('routes_served', sa.SmallInteger(), nullable=True),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='POINT', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stop_code'),
    schema='transport'
    )
    op.create_table('traffic_counts',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('segment_id', sa.Integer(), nullable=False),
    sa.Column('count_date', sa.Date(), nullable=False),
    sa.Column('hour', sa.SmallInteger(), nullable=False),
    sa.Column('vehicles', sa.Integer(), nullable=False),
    sa.Column('avg_speed_kmh', sa.Float(), nullable=True),
    sa.CheckConstraint('hour BETWEEN 0 AND 23', name='traffic_counts_hour_range'),
    sa.ForeignKeyConstraint(['segment_id'], ['transport.road_segments.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('segment_id', 'count_date', 'hour', name='traffic_counts_seg_date_hour_key'),
    schema='transport'
    )
    op.create_index(op.f('ix_transport_traffic_counts_segment_id'), 'traffic_counts', ['segment_id'], unique=False, schema='transport')


def downgrade() -> None:
    op.drop_table("traffic_counts", schema=SCHEMA)
    op.drop_table("transit_stops", schema=SCHEMA)
    op.drop_table("transit_routes", schema=SCHEMA)
    op.drop_table("road_segments", schema=SCHEMA)
    op.drop_table("isochrones", schema=SCHEMA)

