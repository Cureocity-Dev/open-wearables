"""Store received sync capture bodies in PostgreSQL.

Revision ID: f7a913c6b820
Revises: c8f21d4e9b70
"""

import sqlalchemy as sa
from alembic import op

revision: str = "f7a913c6b820"
down_revision: str = "c8f21d4e9b70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receivedcapture",
        sa.Column("object_key", sa.Text(), primary_key=True),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_receivedcapture_expires_at", "receivedcapture", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_receivedcapture_expires_at", table_name="receivedcapture")
    op.drop_table("receivedcapture")
