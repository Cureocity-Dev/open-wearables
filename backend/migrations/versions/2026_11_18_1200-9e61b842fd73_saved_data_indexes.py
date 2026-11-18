"""Add source/key indexes for bounded saved-data reads.

Revision ID: 9e61b842fd73
Revises: f7a913c6b820
"""

from alembic import op

revision = "9e61b842fd73"
down_revision = "f7a913c6b820"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_data_point_series_source_id",
            "data_point_series",
            ["data_source_id", "id"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_event_record_source_id",
            "event_record",
            ["data_source_id", "id"],
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_event_record_source_id", table_name="event_record", postgresql_concurrently=True, if_exists=True
        )
        op.drop_index(
            "ix_data_point_series_source_id",
            table_name="data_point_series",
            postgresql_concurrently=True,
            if_exists=True,
        )
