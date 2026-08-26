"""AlphaEarth satellite embeddings per crop parcel

One 64-dimensional unit vector per parcel per year, zonal-averaged from
Google's AlphaEarth Foundations Satellite Embedding V1 (10 m, annual, CC-BY
4.0) and re-normalised to unit length.

Why a table of floats rather than a raster or an Earth Engine call: the
embeddings are published as public COGs, so the expensive part -- reducing
~5 million 10 m pixels to one vector per parcel -- happens once in the ETL. At
request time this is 64 numbers a row and the whole analysis is a dot product,
with no credentialed service in the serving path.

Storage is `double precision[]` rather than pgvector. pgvector is the right
answer at scale, but it is not installed on every free-tier Postgres, and at
this row count an ANN index would be theatre: a sequential scan over ~1,600
parcels is roughly 100k multiply-adds.

Revision ID: 0012
Revises: 0011
Create Date: 2026-01-01 00:12:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 64

# Both operands are unit-length, so the dot product IS the cosine of the angle
# between them -- there is no magnitude to divide out. Naming it for what it
# returns rather than for what it computes keeps the call sites honest.
CREATE_SIMILARITY_FN = f"""
CREATE OR REPLACE FUNCTION agri.embedding_similarity(
    a double precision[], b double precision[]
) RETURNS double precision AS $$
    SELECT sum(a[i] * b[i])
    FROM generate_series(1, {EMBEDDING_DIM}) AS i
$$ LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE;
"""

COMMENT_SIMILARITY_FN = """
COMMENT ON FUNCTION agri.embedding_similarity(double precision[], double precision[])
IS 'Cosine similarity of two unit-length AlphaEarth embeddings, in [-1, 1]. '
   'Valid only for normalised vectors -- the check constraint on '
   'agri.field_embeddings.embedding is what guarantees that.';
"""


def upgrade() -> None:
    # Must exist before the table: the unit-length check constraint calls it.
    op.execute(CREATE_SIMILARITY_FN)
    op.execute(COMMENT_SIMILARITY_FN)

    op.create_table(
        "field_embeddings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("field_id", sa.Integer(), nullable=False),
        sa.Column("year", sa.SmallInteger(), nullable=False),
        sa.Column("embedding", sa.ARRAY(sa.Float(), dimensions=1), nullable=False),
        #: The crop declared for *this* year. BRP is published annually, so a
        #: parcel has a label per year -- which is what makes the classifier
        #: trainable and rotation detection checkable.
        sa.Column("declared_crop", sa.Text(), nullable=False),
        #: How many 10 m pixels the parcel mean was taken over. A parcel with
        #: too few is a mean of edge pixels and mostly measures its neighbours.
        sa.Column("pixel_count", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="AlphaEarth Foundations V1"),
        sa.ForeignKeyConstraint(["field_id"], ["agri.fields.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("field_id", "year", name="uq_agri_field_embeddings_field_year"),
        sa.CheckConstraint(
            f"array_length(embedding, 1) = {EMBEDDING_DIM}",
            name="ck_agri_field_embeddings_dim",
        ),
        # Every similarity result in the API assumes unit length. Enforcing it
        # here means a bad ETL run fails at load rather than silently returning
        # similarities that are not cosines.
        sa.CheckConstraint(
            "abs(agri.embedding_similarity(embedding, embedding) - 1.0) < 1e-6",
            name="ck_agri_field_embeddings_unit_length",
        ),
        schema="agri",
    )
    op.create_index(
        op.f("ix_agri_field_embeddings_year"), "field_embeddings", ["year"], schema="agri"
    )
    op.create_index(
        op.f("ix_agri_field_embeddings_declared_crop"),
        "field_embeddings", ["declared_crop"], schema="agri",
    )


def downgrade() -> None:
    op.drop_table("field_embeddings", schema="agri")
    op.execute(
        "DROP FUNCTION IF EXISTS agri.embedding_similarity(double precision[], double precision[])"
    )
