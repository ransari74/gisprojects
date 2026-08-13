"""Shared study area and dataset provenance

The study-area polygon every ETL job clips to, and the dataset registry the
frontend's provenance panel is generated from.

Revision ID: 0003
Revises: 0002
Create Date: 2026-01-01 00:03:00
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "meta"


def upgrade() -> None:
    op.create_table('dataset_source',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project', sa.Text(), nullable=False),
    sa.Column('layer', sa.Text(), nullable=False),
    sa.Column('dataset_name', sa.Text(), nullable=False),
    sa.Column('provider', sa.Text(), nullable=True),
    sa.Column('license', sa.Text(), nullable=True),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('feature_count', sa.Integer(), nullable=True),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project', 'layer', 'dataset_name', name='dataset_source_key'),
    schema='meta'
    )
    op.create_table('study_area',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('country', sa.Text(), nullable=True),
    sa.Column('epsg_local', sa.Integer(), server_default='3857', nullable=False),
    sa.Column('geom', geoalchemy2.types.Geometry(geometry_type='MULTIPOLYGON', srid=4326, from_text='ST_GeomFromEWKT', name='geometry', nullable=False), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('code'),
    schema='meta'
    )


def downgrade() -> None:
    op.drop_table("study_area", schema=SCHEMA)
    op.drop_table("dataset_source", schema=SCHEMA)

