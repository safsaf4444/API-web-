"""Phase 4b: Add systematic review, screening, and reminder tables

Revision ID: phase4b_sysrev
Revises: phase4_synthesis
Create Date: 2026-03-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'phase4b_sysrev'
down_revision: Union[str, Sequence[str], None] = 'phase4_synthesis'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── systematicreview ──────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS systematicreview (
            id                   SERIAL PRIMARY KEY,
            owner_username       VARCHAR NOT NULL,
            title                VARCHAR NOT NULL DEFAULT 'Untitled Review',
            description          TEXT,
            phase                VARCHAR NOT NULL DEFAULT 'search',
            search_query         TEXT,
            search_source        VARCHAR NOT NULL DEFAULT 'europepmc',
            search_results_count INTEGER NOT NULL DEFAULT 0,
            inclusion_criteria   JSON,
            exclusion_criteria   JSON,
            filters              JSON,
            audit_log            JSON,
            synthesis_id         INTEGER REFERENCES synthesisresult(id),
            created_at           TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at           TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_systematicreview_owner_username ON systematicreview (owner_username)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_systematicreview_phase ON systematicreview (phase)"
    ))

    # ── reviewscreening ───────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS reviewscreening (
            id                  SERIAL PRIMARY KEY,
            review_id           INTEGER NOT NULL REFERENCES systematicreview(id),
            owner_username      VARCHAR NOT NULL,
            study_id            INTEGER REFERENCES study(id),
            external_title      TEXT,
            external_doi        VARCHAR,
            external_abstract   TEXT,
            external_source     VARCHAR,
            external_source_id  VARCHAR,
            external_year       INTEGER,
            decision            VARCHAR NOT NULL DEFAULT 'pending',
            exclusion_reason    TEXT,
            screener_notes      TEXT,
            created_at          TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_reviewscreening_review_id ON reviewscreening (review_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_reviewscreening_owner_username ON reviewscreening (owner_username)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_reviewscreening_study_id ON reviewscreening (study_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_reviewscreening_decision ON reviewscreening (decision)"
    ))

    # ── paperreminder ─────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS paperreminder (
            id              SERIAL PRIMARY KEY,
            owner_username  VARCHAR NOT NULL,
            study_id        INTEGER NOT NULL REFERENCES study(id),
            remind_at       TIMESTAMP NOT NULL,
            reason          TEXT,
            is_dismissed    BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_paperreminder_owner_username ON paperreminder (owner_username)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_paperreminder_study_id ON paperreminder (study_id)"
    ))
    conn.execute(sa.text(
        "CREATE INDEX IF NOT EXISTS ix_paperreminder_remind_at ON paperreminder (remind_at)"
    ))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DROP TABLE IF EXISTS paperreminder"))
    conn.execute(sa.text("DROP TABLE IF EXISTS reviewscreening"))
    conn.execute(sa.text("DROP TABLE IF EXISTS systematicreview"))
