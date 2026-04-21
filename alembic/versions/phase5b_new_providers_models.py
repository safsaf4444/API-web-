"""Phase 5b: new providers, Study extended fields, SavedSearch, SearchHistory, ReadingQueue

Revision ID: phase5b_new_providers_models
Revises: phase6_trust_tables
Create Date: 2026-04-21
"""

from alembic import op

# revision identifiers
revision = "phase5b_new_providers_models"
down_revision = "phase6_trust_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Study: extended fields ────────────────────────────────────────────────
    op.execute("ALTER TABLE study ADD COLUMN IF NOT EXISTS publication_type TEXT")
    op.execute("ALTER TABLE study ADD COLUMN IF NOT EXISTS full_text_url TEXT")
    op.execute("ALTER TABLE study ADD COLUMN IF NOT EXISTS is_predatory_journal BOOLEAN NOT NULL DEFAULT FALSE")

    # ── SavedSearch ───────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS savedsearch (
            id             SERIAL PRIMARY KEY,
            owner_username TEXT NOT NULL,
            query          TEXT NOT NULL,
            provider       TEXT NOT NULL DEFAULT 'europepmc',
            filters        TEXT,
            last_run       TIMESTAMPTZ,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_savedsearch_owner_username ON savedsearch (owner_username)")

    # ── SearchHistory ─────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS searchhistory (
            id             SERIAL PRIMARY KEY,
            owner_username TEXT NOT NULL,
            query          TEXT NOT NULL,
            provider       TEXT NOT NULL DEFAULT 'europepmc',
            result_count   INT NOT NULL DEFAULT 0,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_searchhistory_owner_username ON searchhistory (owner_username)")

    # ── ReadingQueue ──────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS readingqueue (
            id             SERIAL PRIMARY KEY,
            owner_username TEXT NOT NULL,
            study_id       INT NOT NULL REFERENCES study(id) ON DELETE CASCADE,
            position       INT NOT NULL DEFAULT 0,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_readingqueue_owner_study UNIQUE (owner_username, study_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_readingqueue_owner_username ON readingqueue (owner_username)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS readingqueue")
    op.execute("DROP TABLE IF EXISTS searchhistory")
    op.execute("DROP TABLE IF EXISTS savedsearch")
    op.execute("ALTER TABLE study DROP COLUMN IF EXISTS is_predatory_journal")
    op.execute("ALTER TABLE study DROP COLUMN IF EXISTS full_text_url")
    op.execute("ALTER TABLE study DROP COLUMN IF EXISTS publication_type")
