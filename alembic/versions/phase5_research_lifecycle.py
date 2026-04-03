"""Phase 5: Research Lifecycle, OSF/Kaggle URLs, Spreadsheet, Attachments

Revision ID: phase5_research_lifecycle
Revises: phase4d_extraction
Create Date: 2026-04-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase5_research_lifecycle'
down_revision: Union[str, Sequence[str], None] = 'phase4d_extraction'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Study Updates (Data URIs) ─────────────────────────────────────────────
    conn.execute(sa.text("ALTER TABLE study ADD COLUMN IF NOT EXISTS kaggle_url VARCHAR"))
    conn.execute(sa.text("ALTER TABLE study ADD COLUMN IF NOT EXISTS github_url VARCHAR"))
    conn.execute(sa.text("ALTER TABLE study ADD COLUMN IF NOT EXISTS osf_url VARCHAR"))
    conn.execute(sa.text("ALTER TABLE study ADD COLUMN IF NOT EXISTS zenodo_url VARCHAR"))

    # ── SpreadsheetData ───────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS spreadsheetdata (
            id             SERIAL  PRIMARY KEY,
            owner_username VARCHAR NOT NULL,
            study_id       INTEGER REFERENCES study(id),
            name           VARCHAR NOT NULL DEFAULT 'Untitled Spreadsheet',
            data_json      TEXT,
            created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """))

    # ── Attachment ────────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS attachment (
            id             SERIAL  PRIMARY KEY,
            study_id       INTEGER NOT NULL REFERENCES study(id),
            owner_username VARCHAR NOT NULL,
            filename       VARCHAR NOT NULL,
            file_type      VARCHAR NOT NULL,
            content_base64 TEXT    NOT NULL,
            created_at     TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """))

    # ── ResearchQuestion ──────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS researchquestion (
            id                SERIAL  PRIMARY KEY,
            owner_username    VARCHAR NOT NULL,
            question_text     VARCHAR NOT NULL,
            pico_json         JSONB,
            finer_scores_json JSONB,
            hypothesis_null   VARCHAR,
            hypothesis_alt    VARCHAR,
            objectives_json   JSONB,
            novelty_score     INTEGER,
            novelty_notes     VARCHAR,
            created_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS researchquestion CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS attachment CASCADE"))
    conn.execute(sa.text("DROP TABLE IF EXISTS spreadsheetdata CASCADE"))
    
    conn.execute(sa.text("ALTER TABLE study DROP COLUMN IF EXISTS kaggle_url"))
    conn.execute(sa.text("ALTER TABLE study DROP COLUMN IF EXISTS github_url"))
    conn.execute(sa.text("ALTER TABLE study DROP COLUMN IF EXISTS osf_url"))
    conn.execute(sa.text("ALTER TABLE study DROP COLUMN IF EXISTS zenodo_url"))
