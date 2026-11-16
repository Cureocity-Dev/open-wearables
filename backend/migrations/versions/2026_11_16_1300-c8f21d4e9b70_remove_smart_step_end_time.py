"""Remove the unused smart-step interval end column.

Revision ID: c8f21d4e9b70
Revises: 32b3e142ff4d
"""

import sqlalchemy as sa
from alembic import op

revision = "c8f21d4e9b70"
down_revision = "32b3e142ff4d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Smart aggregation has been removed; existing interval end values are discarded.
    op.drop_column("data_point_series", "end_at")


def downgrade() -> None:
    # Restores the schema only; deleted interval end values cannot be recovered.
    op.add_column("data_point_series", sa.Column("end_at", sa.DateTime(timezone=True), nullable=True))
