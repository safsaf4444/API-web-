"""Batch 3: add citation_count and is_retracted to study

Revision ID: 2bfbcfca1aaa
Revises: 4237a8a714ce
Create Date: 2026-03-23 01:42:42.341902

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2bfbcfca1aaa'
down_revision: Union[str, Sequence[str], None] = '4237a8a714ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('study', sa.Column('citation_count', sa.Integer(), nullable=True))
    op.add_column('study', sa.Column('is_retracted', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('study', 'is_retracted')
    op.drop_column('study', 'citation_count')