"""Phase 3: Add share_token and reading_status

Revision ID: 4237a8a714ce
Revises: 1a3528eeacab
Create Date: 2026-03-23 01:23:29.402961

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4237a8a714ce'
down_revision: Union[str, Sequence[str], None] = '1a3528eeacab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index(op.f('ix_airesult_share_token'), 'airesult', ['share_token'], unique=False)
    op.alter_column('study', 'reading_status',
               existing_type=postgresql.ENUM('unread', 'reading', 'done', 'flagged', name='readingstatus'),
               type_=sa.String(),
               existing_nullable=False,
               existing_server_default=sa.text("'unread'::readingstatus"))


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('study', 'reading_status',
               existing_type=sa.String(),
               type_=postgresql.ENUM('unread', 'reading', 'done', 'flagged', name='readingstatus'),
               existing_nullable=False,
               existing_server_default=sa.text("'unread'::readingstatus"))
    op.drop_index(op.f('ix_airesult_share_token'), table_name='airesult')