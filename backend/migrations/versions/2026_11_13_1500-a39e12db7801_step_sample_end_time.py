"""Preserve SDK metric interval end times.

Revision ID: a39e12db7801
Revises: d8a0bc9afdd9
"""

import sqlalchemy as sa
from alembic import op

revision = "a39e12db7801"
down_revision = "d8a0bc9afdd9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("data_point_series", sa.Column("end_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("data_point_series", "end_at")
