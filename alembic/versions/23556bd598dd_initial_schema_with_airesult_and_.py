"""initial schema - full create from scratch

Revision ID: 23556bd598dd
Revises: 
Create Date: 2026-03-10 00:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


revision: str = '23556bd598dd'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('user',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('hashed_password', sa.String(), nullable=False),
        sa.Column('ai_key_enc', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username'),
    )
    op.create_index('ix_user_username', 'user', ['username'])
    op.create_index('ix_user_email', 'user', ['email'])

    op.create_table('folder',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_username', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_username', 'name', name='uq_folder_owner_name'),
    )
    op.create_index('ix_folder_owner_username', 'folder', ['owner_username'])
    op.create_index('ix_folder_name', 'folder', ['name'])

    op.create_table('study',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_username', sa.String(), nullable=False),
        sa.Column('folder_id', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('venue', sa.String(), nullable=True),
        sa.Column('authors', sa.String(), nullable=True),
        sa.Column('doi', sa.String(), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('abstract', sa.String(), nullable=True),
        sa.Column('pmid', sa.String(), nullable=True),
        sa.Column('pmcid', sa.String(), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('study_type', sa.String(), nullable=True),
        sa.Column('tags', sa.String(), nullable=True),
        sa.Column('ai_summary', sa.String(), nullable=True),
        sa.Column('ai_summary_updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['folder_id'], ['folder.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_username', 'source', 'source_id', name='uq_study_owner_source_id'),
    )
    op.create_index('ix_study_owner_username', 'study', ['owner_username'])
    op.create_index('ix_study_source', 'study', ['source'])
    op.create_index('ix_study_source_id', 'study', ['source_id'])
    op.create_index('ix_study_doi', 'study', ['doi'])
    op.create_index('ix_study_pmid', 'study', ['pmid'])
    op.create_index('ix_study_pmcid', 'study', ['pmcid'])
    op.create_index('ix_study_year', 'study', ['year'])

    op.create_table('studyexternalref',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_username', sa.String(), nullable=False),
        sa.Column('study_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('source_id', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['study_id'], ['study.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_username', 'source', 'source_id', name='uq_studyext_owner_source_sourceid'),
        sa.UniqueConstraint('study_id', 'source', name='uq_studyext_study_source'),
    )
    op.create_index('ix_studyexternalref_owner_username', 'studyexternalref', ['owner_username'])
    op.create_index('ix_studyexternalref_study_id', 'studyexternalref', ['study_id'])
    op.create_index('ix_studyexternalref_source', 'studyexternalref', ['source'])
    op.create_index('ix_studyexternalref_source_id', 'studyexternalref', ['source_id'])
    op.create_index('ix_studyexternalref_created_at', 'studyexternalref', ['created_at'])

    op.create_table('studymetrics',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_username', sa.String(), nullable=False),
        sa.Column('study_id', sa.Integer(), nullable=False),
        sa.Column('study_type', sa.String(), nullable=True),
        sa.Column('evidence_strength', sa.Integer(), nullable=True),
        sa.Column('risk_of_bias', sa.Integer(), nullable=True),
        sa.Column('sample_size', sa.Integer(), nullable=True),
        sa.Column('save_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('folder_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('comment_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ai_runs', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('last_accessed', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['study_id'], ['study.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_studymetrics_owner_username', 'studymetrics', ['owner_username'])
    op.create_index('ix_studymetrics_study_id', 'studymetrics', ['study_id'])
    op.create_index('ix_studymetrics_study_type', 'studymetrics', ['study_type'])

    op.create_table('airesult',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_username', sa.String(), nullable=False),
        sa.Column('cache_key', sa.String(), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('model_used', sa.String(), nullable=False),
        sa.Column('question', sa.String(), nullable=True),
        sa.Column('summary', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('owner_username', 'cache_key', 'kind', name='uq_airesult_owner_key_kind'),
    )
    op.create_index('ix_airesult_owner_username', 'airesult', ['owner_username'])
    op.create_index('ix_airesult_cache_key', 'airesult', ['cache_key'])
    op.create_index('ix_airesult_kind', 'airesult', ['kind'])

    op.create_table('comment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('study_id', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('author', sa.String(), nullable=False),
        sa.Column('body', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['study_id'], ['study.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_comment_study_id', 'comment', ['study_id'])
    op.create_index('ix_comment_parent_id', 'comment', ['parent_id'])
    op.create_index('ix_comment_author', 'comment', ['author'])


def downgrade() -> None:
    op.drop_table('comment')
    op.drop_table('airesult')
    op.drop_table('studymetrics')
    op.drop_table('studyexternalref')
    op.drop_table('study')
    op.drop_table('folder')
    op.drop_table('user')