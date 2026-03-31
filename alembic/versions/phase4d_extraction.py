"""Phase 4d: Extraction templates, extraction records, evidence_notes on review

Revision ID: phase4d_extraction
Revises: phase4c_living_review
Create Date: 2026-03-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase4d_extraction'
down_revision: Union[str, Sequence[str], None] = 'phase4c_living_review'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── ExtractionTemplate ────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS extractiontemplate (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            owner_username TEXT    NOT NULL,
            name           TEXT    NOT NULL,
            fields         JSON,
            is_global      BOOLEAN NOT NULL DEFAULT 0,
            created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # ── ExtractionRecord ──────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS extractionrecord (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id      INTEGER NOT NULL REFERENCES systematicreview(id),
            screening_id   INTEGER NOT NULL REFERENCES reviewscreening(id),
            template_id    INTEGER REFERENCES extractiontemplate(id),
            owner_username TEXT    NOT NULL,
            data           JSON,
            ai_extracted   BOOLEAN NOT NULL DEFAULT 0,
            created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """))

    # ── SystematicReview: evidence_notes ─────────────────────────────────────
    conn.execute(sa.text(
        "ALTER TABLE systematicreview ADD COLUMN IF NOT EXISTS evidence_notes TEXT"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS extractionrecord"))
    conn.execute(sa.text("DROP TABLE IF EXISTS extractiontemplate"))
    conn.execute(sa.text("ALTER TABLE systematicreview DROP COLUMN IF EXISTS evidence_notes"))
