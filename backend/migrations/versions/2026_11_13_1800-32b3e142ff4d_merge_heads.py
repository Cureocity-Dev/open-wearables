"""merge heads

Revision ID: 32b3e142ff4d
Revises: 5aaff4551af6, a39e12db7801

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '32b3e142ff4d'
down_revision: Union[str, None] = ('5aaff4551af6', 'a39e12db7801')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
