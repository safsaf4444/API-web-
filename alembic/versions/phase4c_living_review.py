"""Phase 4c: Living Review — add extraction fields to Study and text_offsets to AIResult

Revision ID: phase4c_living_review
Revises: phase4b_sysrev
Create Date: 2026-03-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase4c_living_review'
down_revision: Union[str, Sequence[str], None] = 'phase4b_sysrev'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Study: structured extraction fields ───────────────────────────────────
    conn.execute(sa.text("ALTER TABLE study ADD COLUMN IF NOT EXISTS extracted_outcome_value FLOAT"))
    conn.execute(sa.text("ALTER TABLE study ADD COLUMN IF NOT EXISTS extracted_sample_size INTEGER"))
    conn.execute(sa.text("ALTER TABLE study ADD COLUMN IF NOT EXISTS extracted_bias_score INTEGER"))
    conn.execute(sa.text("ALTER TABLE study ADD COLUMN IF NOT EXISTS grade_criteria JSON"))

    # ── AIResult: source-grounded text offsets ────────────────────────────────
    conn.execute(sa.text("ALTER TABLE airesult ADD COLUMN IF NOT EXISTS text_offsets JSON"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE study DROP COLUMN IF EXISTS extracted_outcome_value"))
    conn.execute(sa.text("ALTER TABLE study DROP COLUMN IF EXISTS extracted_sample_size"))
    conn.execute(sa.text("ALTER TABLE study DROP COLUMN IF EXISTS extracted_bias_score"))
    conn.execute(sa.text("ALTER TABLE study DROP COLUMN IF EXISTS grade_criteria"))
    conn.execute(sa.text("ALTER TABLE airesult DROP COLUMN IF EXISTS text_offsets"))
