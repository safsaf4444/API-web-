"""Phase 4: Add synthesis_result table

Revision ID: phase4_synthesis
Revises: 2bfbcfca1aaa
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase4_synthesis'
down_revision: Union[str, Sequence[str], None] = '2bfbcfca1aaa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create synthesis_result table."""
    op.create_table(
        'synthesisresult',
        sa.Column('id',                    sa.Integer(),    nullable=False),
        sa.Column('owner_username',        sa.String(),     nullable=False),
        sa.Column('cache_key',             sa.String(),     nullable=False),
        sa.Column('study_ids',             sa.String(),     nullable=False, server_default='[]'),
        sa.Column('mode',                  sa.String(),     nullable=False, server_default='multi_paper'),
        sa.Column('query',                 sa.String(),     nullable=True),
        sa.Column('synthesis_narrative',   sa.Text(),       nullable=True),
        sa.Column('consensus_points',      sa.Text(),       nullable=True),
        sa.Column('contradictions',        sa.Text(),       nullable=True),
        sa.Column('gap_analysis',          sa.Text(),       nullable=True),
        sa.Column('weighted_conclusion',   sa.Text(),       nullable=True),
        sa.Column('steel_man',             sa.Text(),       nullable=True),
        sa.Column('comparative_methodology', sa.Text(),     nullable=True),
        sa.Column('weighting_breakdown',   sa.Text(),       nullable=True),
        sa.Column('prompt_version',        sa.String(),     nullable=False, server_default='4.0'),
        sa.Column('model_used',            sa.String(),     nullable=False, server_default='unknown'),
        sa.Column('paper_count',           sa.Integer(),    nullable=False, server_default='0'),
        sa.Column('created_at',            sa.DateTime(),   nullable=False),
        sa.Column('updated_at',            sa.DateTime(),   nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_synthesisresult_owner_username', 'synthesisresult', ['owner_username'])
    op.create_index('ix_synthesisresult_cache_key',      'synthesisresult', ['cache_key'])
    op.create_index('ix_synthesisresult_mode',           'synthesisresult', ['mode'])


def downgrade() -> None:
    """Drop synthesis_result table."""
    op.drop_index('ix_synthesisresult_mode',           table_name='synthesisresult')
    op.drop_index('ix_synthesisresult_cache_key',      table_name='synthesisresult')
    op.drop_index('ix_synthesisresult_owner_username', table_name='synthesisresult')
    op.drop_table('synthesisresult')