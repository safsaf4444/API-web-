"""phase3_intelligence

Revision ID: f7b5aa4c8050
Revises: 
Create Date: 2026-03-17
"""
from __future__ import annotations
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = 'f7b5aa4c8050'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE study ADD COLUMN IF NOT EXISTS reading_status VARCHAR NOT NULL DEFAULT 'unread'")
    op.execute("ALTER TABLE studymetrics ADD COLUMN IF NOT EXISTS evidence_strength INTEGER")
    op.execute("ALTER TABLE studymetrics ADD COLUMN IF NOT EXISTS risk_of_bias VARCHAR")
    op.execute("ALTER TABLE studymetrics ADD COLUMN IF NOT EXISTS pico_data JSONB")
    op.execute("ALTER TABLE studymetrics ADD COLUMN IF NOT EXISTS statistical_data JSONB")
    op.execute("ALTER TABLE airesult ADD COLUMN IF NOT EXISTS patient_summary TEXT")
    op.execute("ALTER TABLE airesult ADD COLUMN IF NOT EXISTS clinician_summary TEXT")
    op.execute("ALTER TABLE airesult ADD COLUMN IF NOT EXISTS student_summary TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE airesult DROP COLUMN IF EXISTS student_summary")
    op.execute("ALTER TABLE airesult DROP COLUMN IF EXISTS clinician_summary")
    op.execute("ALTER TABLE airesult DROP COLUMN IF EXISTS patient_summary")
    op.execute("ALTER TABLE studymetrics DROP COLUMN IF EXISTS statistical_data")
    op.execute("ALTER TABLE studymetrics DROP COLUMN IF EXISTS pico_data")
    op.execute("ALTER TABLE studymetrics DROP COLUMN IF EXISTS risk_of_bias")
    op.execute("ALTER TABLE studymetrics DROP COLUMN IF EXISTS evidence_strength")
    op.execute("ALTER TABLE study DROP COLUMN IF EXISTS reading_status")