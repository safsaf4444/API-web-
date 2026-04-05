"""Phase 6: Trust & Validity System — 13 new tables + feature flags seed

Revision ID: phase6_trust_tables
Revises: phase5_research_lifecycle
Create Date: 2026-04-04
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "phase6_trust_tables"
down_revision: Union[str, None] = "phase5_research_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── promptversion ─────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS promptversion (
            id               SERIAL PRIMARY KEY,
            endpoint         VARCHAR NOT NULL,
            version          VARCHAR NOT NULL,
            system_template  TEXT    NOT NULL,
            user_template    TEXT    NOT NULL,
            notes            VARCHAR,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            is_active        BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_promptversion_endpoint ON promptversion(endpoint)"))

    # ── airun ─────────────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS airun (
            id                  SERIAL PRIMARY KEY,
            owner_username      VARCHAR NOT NULL,
            study_id            INTEGER REFERENCES study(id) ON DELETE SET NULL,
            review_id           INTEGER REFERENCES systematicreview(id) ON DELETE SET NULL,
            endpoint            VARCHAR NOT NULL,
            provider            VARCHAR NOT NULL,
            model               VARCHAR NOT NULL,
            prompt_version_id   INTEGER REFERENCES promptversion(id) ON DELETE SET NULL,
            input_tokens        INTEGER,
            output_tokens       INTEGER,
            latency_ms          INTEGER,
            status              VARCHAR NOT NULL DEFAULT 'running',
            error_message       VARCHAR,
            trust_score         FLOAT,
            confidence_ceiling  FLOAT,
            flagged             BOOLEAN NOT NULL DEFAULT FALSE,
            flag_reason         VARCHAR,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at        TIMESTAMPTZ
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_airun_owner ON airun(owner_username)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_airun_study ON airun(study_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_airun_review ON airun(review_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_airun_status ON airun(status)"))

    # ── evidencespan ──────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS evidencespan (
            id          SERIAL PRIMARY KEY,
            ai_run_id   INTEGER NOT NULL REFERENCES airun(id) ON DELETE CASCADE,
            study_id    INTEGER REFERENCES study(id) ON DELETE SET NULL,
            source_text TEXT    NOT NULL,
            claim_text  TEXT    NOT NULL,
            basis       VARCHAR NOT NULL DEFAULT 'unknown',
            span_start  INTEGER,
            span_end    INTEGER,
            confidence  FLOAT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_evidencespan_run ON evidencespan(ai_run_id)"))

    # ── claim ─────────────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS claim (
            id                  SERIAL PRIMARY KEY,
            ai_run_id           INTEGER NOT NULL REFERENCES airun(id) ON DELETE CASCADE,
            study_id            INTEGER REFERENCES study(id) ON DELETE SET NULL,
            review_id           INTEGER REFERENCES systematicreview(id) ON DELETE SET NULL,
            claim_type          VARCHAR NOT NULL DEFAULT 'factual',
            text                TEXT    NOT NULL,
            evidence_span_id    INTEGER REFERENCES evidencespan(id) ON DELETE SET NULL,
            confidence          FLOAT,
            verification_state  VARCHAR NOT NULL DEFAULT 'pending',
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_claim_run ON claim(ai_run_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_claim_state ON claim(verification_state)"))

    # ── verificationrecord ────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS verificationrecord (
            id                     SERIAL PRIMARY KEY,
            claim_id               INTEGER NOT NULL REFERENCES claim(id) ON DELETE CASCADE,
            verifier_username      VARCHAR NOT NULL,
            decision               VARCHAR NOT NULL,
            notes                  TEXT,
            prompt_version_locked  VARCHAR,
            created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_verif_claim ON verificationrecord(claim_id)"))

    # ── audit_logs ────────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            id               SERIAL PRIMARY KEY,
            event            VARCHAR NOT NULL,
            actor            VARCHAR NOT NULL,
            study_id         INTEGER,
            ai_run_id        INTEGER,
            review_id        INTEGER,
            claim_id         INTEGER,
            verification_id  INTEGER,
            detail           TEXT,
            ip_address       VARCHAR,
            user_agent       VARCHAR,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_auditlog_event  ON audit_logs(event)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_auditlog_actor  ON audit_logs(actor)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_auditlog_study  ON audit_logs(study_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_auditlog_run    ON audit_logs(ai_run_id)"))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_auditlog_ts     ON audit_logs(created_at)"))

    # Prevent accidental UPDATE/DELETE on audit_logs via trigger
    conn.execute(sa.text("""
        CREATE OR REPLACE FUNCTION audit_log_immutable()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs rows are immutable';
        END;
        $$
    """))
    conn.execute(sa.text("""
        DROP TRIGGER IF EXISTS trg_audit_log_immutable ON audit_logs
    """))
    conn.execute(sa.text("""
        CREATE TRIGGER trg_audit_log_immutable
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()
    """))

    # ── benchmarkdataset ──────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS benchmarkdataset (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR NOT NULL UNIQUE,
            task_type   VARCHAR NOT NULL,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # ── benchmarkitem ─────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS benchmarkitem (
            id               SERIAL PRIMARY KEY,
            dataset_id       INTEGER NOT NULL REFERENCES benchmarkdataset(id) ON DELETE CASCADE,
            input_text       TEXT    NOT NULL,
            expected_output  TEXT    NOT NULL,
            metadata_json    TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_benchmarkitem_ds ON benchmarkitem(dataset_id)"))

    # ── evalrun ───────────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS evalrun (
            id                SERIAL PRIMARY KEY,
            dataset_id        INTEGER NOT NULL REFERENCES benchmarkdataset(id),
            triggered_by      VARCHAR NOT NULL,
            provider          VARCHAR NOT NULL,
            model             VARCHAR NOT NULL,
            prompt_version_id INTEGER REFERENCES promptversion(id) ON DELETE SET NULL,
            status            VARCHAR NOT NULL DEFAULT 'pending',
            error_message     VARCHAR,
            started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at      TIMESTAMPTZ
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_evalrun_ds ON evalrun(dataset_id)"))

    # ── evalmetric ────────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS evalmetric (
            id           SERIAL PRIMARY KEY,
            eval_run_id  INTEGER NOT NULL REFERENCES evalrun(id) ON DELETE CASCADE,
            metric_name  VARCHAR NOT NULL,
            metric_value FLOAT   NOT NULL,
            threshold    FLOAT,
            passed       BOOLEAN
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_evalmetric_run ON evalmetric(eval_run_id)"))

    # ── trustalert ────────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS trustalert (
            id              SERIAL PRIMARY KEY,
            owner_username  VARCHAR NOT NULL,
            ai_run_id       INTEGER REFERENCES airun(id) ON DELETE SET NULL,
            alert_type      VARCHAR NOT NULL,
            severity        VARCHAR NOT NULL DEFAULT 'medium',
            message         TEXT    NOT NULL,
            is_dismissed    BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_trustalert_owner ON trustalert(owner_username)"))

    # ── featureflag ───────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS featureflag (
            id          SERIAL PRIMARY KEY,
            name        VARCHAR NOT NULL UNIQUE,
            is_enabled  BOOLEAN NOT NULL DEFAULT FALSE,
            description TEXT,
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))

    # ── userrole ──────────────────────────────────────────────────────────────
    conn.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS userrole (
            id          SERIAL PRIMARY KEY,
            username    VARCHAR NOT NULL,
            role        VARCHAR NOT NULL,
            granted_by  VARCHAR NOT NULL,
            granted_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE(username, role)
        )
    """))
    conn.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_userrole_username ON userrole(username)"))

    # ── Seed feature flags (all OFF by default) ───────────────────────────────
    flags = [
        ("trust_guardrails",      "Master switch — enable all guardrail checks"),
        ("claim_extraction",      "Extract structured claims from engine output"),
        ("evidence_spans",        "Record source-to-claim evidence spans"),
        ("confidence_ceilings",   "Apply evidence-basis confidence ceilings"),
        ("audit_log",             "Write append-only audit log for every AI call"),
        ("auto_alerts",           "Auto-create TrustAlert for flagged outputs"),
        ("eval_runner",           "Allow background benchmark eval runs"),
        ("require_verification",  "Block unverified claims from downstream use"),
    ]
    for name, desc in flags:
        conn.execute(sa.text(
            "INSERT INTO featureflag (name, is_enabled, description) "
            "VALUES (:n, FALSE, :d) ON CONFLICT (name) DO NOTHING"
        ), {"n": name, "d": desc})


def downgrade() -> None:
    conn = op.get_bind()
    for table in [
        "userrole", "featureflag", "trustalert",
        "evalmetric", "evalrun", "benchmarkitem", "benchmarkdataset",
        "audit_logs", "verificationrecord", "claim", "evidencespan",
        "airun", "promptversion",
    ]:
        conn.execute(sa.text(f"DROP TABLE IF EXISTS {table} CASCADE"))

    conn.execute(sa.text("DROP FUNCTION IF EXISTS audit_log_immutable() CASCADE"))
