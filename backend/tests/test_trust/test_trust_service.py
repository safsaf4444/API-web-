"""Unit tests for backend/services/trust_service.py"""
import pytest
from sqlmodel import select

from backend.models_trust import AIRun, Claim, EvidenceSpan, VerificationState
from backend.services import trust_service

# session fixture provided by conftest.py


class TestAIRunLifecycle:
    def test_create_ai_run(self, session):
        run = trust_service.create_ai_run(
            session,
            owner_username="testuser",
            endpoint="summarise",
            provider="gemini",
            model="gemini-1.5-flash",
        )
        assert run.id is not None
        assert run.status == "running"
        assert run.task_kind == "summarise"

    def test_complete_ai_run(self, session):
        run = trust_service.create_ai_run(
            session,
            owner_username="testuser",
            endpoint="summarise",
            provider="gemini",
            model="gemini-1.5-flash",
        )
        completed = trust_service.complete_ai_run(
            session,
            run,
            latency_ms=250,
            evidence_basis="rct",
        )
        assert completed.status == "completed"
        assert completed.evidence_basis == "rct"
        assert completed.latency_ms == 250

    def test_fail_ai_run(self, session):
        run = trust_service.create_ai_run(
            session,
            owner_username="testuser",
            endpoint="summarise",
            provider="gemini",
            model="gemini-1.5-flash",
        )
        failed = trust_service.fail_ai_run(session, run, error_message="Connection timeout")
        assert failed.status == "failed"
        assert "timeout" in failed.failure_reason.lower()

    def test_confidence_ceiling_applied_to_calibrated_conf(self, session):
        """Confidence is capped to the ceiling for expert_opinion (0.55)."""
        run = trust_service.create_ai_run(
            session,
            owner_username="u",
            endpoint="summarise",
            provider="gemini",
            model="gemini-1.5-flash",
        )
        spans = [{
            "source_text": "Expert says X.",
            "claim_text": "X is true.",
            "basis": "expert_opinion",
            "confidence": 0.99,   # raw — should be capped to 0.55
            "claim_type": "extracted",
        }]
        claims = trust_service.record_claims(session, run, spans=spans)
        assert claims[0].calibrated_conf <= 0.55

    def test_study_id_stored_in_json(self, session):
        run = trust_service.create_ai_run(
            session,
            owner_username="u",
            endpoint="clinical",
            provider="gemini",
            model="gemini-1.5-flash",
            study_id=42,
        )
        import json
        assert json.loads(run.study_ids_json) == [42]


class TestRecordClaims:
    def test_record_creates_spans_and_claims(self, session):
        run = trust_service.create_ai_run(
            session,
            owner_username="testuser",
            endpoint="summarise",
            provider="gemini",
            model="gemini-1.5-flash",
        )
        spans = [
            {
                "source_text": "RCT showed metformin reduces HbA1c.",
                "claim_text": "Metformin reduces HbA1c.",
                "basis": "rct",
                "confidence": 0.90,
                "claim_type": "extracted",
            }
        ]
        claims = trust_service.record_claims(session, run, spans=spans)
        assert len(claims) == 1
        assert claims[0].verification_state == VerificationState.DRAFT

        db_spans = list(session.exec(select(EvidenceSpan)).all())
        assert len(db_spans) == 1
        assert db_spans[0].span_text == "RCT showed metformin reduces HbA1c."

    def test_record_multiple_claims(self, session):
        run = trust_service.create_ai_run(
            session,
            owner_username="testuser",
            endpoint="synthesise",
            provider="gemini",
            model="gemini-1.5-flash",
        )
        spans = [
            {"source_text": "Source A.", "claim_text": "Claim A.", "basis": "rct", "confidence": 0.8, "claim_type": "extracted"},
            {"source_text": "Source B.", "claim_text": "Claim B.", "basis": "cohort", "confidence": 0.7, "claim_type": "interpreted"},
        ]
        claims = trust_service.record_claims(session, run, spans=spans)
        assert len(claims) == 2
        db_spans = list(session.exec(select(EvidenceSpan)).all())
        assert len(db_spans) == 2

    def test_confidence_calibrated_on_record(self, session):
        run = trust_service.create_ai_run(
            session,
            owner_username="testuser",
            endpoint="summarise",
            provider="gemini",
            model="gemini-1.5-flash",
        )
        # Cohort ceiling = 0.80; raw 0.95 should become ≤ 0.80
        spans = [{"source_text": "s", "claim_text": "c", "basis": "cohort", "confidence": 0.95, "claim_type": "extracted"}]
        claims = trust_service.record_claims(session, run, spans=spans)
        assert claims[0].calibrated_conf <= 0.80
        assert claims[0].model_confidence == 0.95

    def test_has_grounding_set(self, session):
        run = trust_service.create_ai_run(
            session, owner_username="u", endpoint="summarise", provider="gemini", model="gemini-1.5-flash"
        )
        spans = [{"source_text": "src", "claim_text": "claim", "basis": "rct", "confidence": 0.8, "claim_type": "extracted"}]
        claims = trust_service.record_claims(session, run, spans=spans)
        assert claims[0].has_grounding is True


class TestVerifyClaim:
    def test_verify_claim_approved(self, session):
        run = trust_service.create_ai_run(
            session, owner_username="u", endpoint="summarise", provider="gemini", model="gemini-1.5-flash"
        )
        claims = trust_service.record_claims(
            session, run, spans=[{
                "source_text": "source text",
                "claim_text": "claim text",
                "basis": "rct",
                "confidence": 0.8,
                "claim_type": "extracted",
            }]
        )
        result = trust_service.verify_claim(
            session,
            claim_id=claims[0].id,
            verifier_username="reviewer1",
            decision="approved",
        )
        assert result.decision == "approved"
        assert result.verifier_username == "reviewer1"

        # Claim in DB should be updated
        claim = session.get(Claim, claims[0].id)
        assert claim.verification_state == VerificationState.VERIFIED
        assert claim.verified_by == "reviewer1"

    def test_verify_claim_rejected(self, session):
        run = trust_service.create_ai_run(
            session, owner_username="u", endpoint="summarise", provider="gemini", model="gemini-1.5-flash"
        )
        claims = trust_service.record_claims(
            session, run, spans=[{"source_text": "s", "claim_text": "c", "basis": "rct", "confidence": 0.8, "claim_type": "extracted"}]
        )
        result = trust_service.verify_claim(
            session,
            claim_id=claims[0].id,
            verifier_username="reviewer1",
            decision="rejected",
            notes="Insufficient evidence cited",
        )
        assert result.decision == "rejected"
        claim = session.get(Claim, claims[0].id)
        assert claim.verification_state == VerificationState.REJECTED

    def test_verify_claim_invalid_decision(self, session):
        run = trust_service.create_ai_run(
            session, owner_username="u", endpoint="summarise", provider="gemini", model="gemini-1.5-flash"
        )
        claims = trust_service.record_claims(
            session, run, spans=[{"source_text": "s", "claim_text": "c", "basis": "rct", "confidence": 0.8, "claim_type": "extracted"}]
        )
        with pytest.raises(ValueError, match="Invalid decision"):
            trust_service.verify_claim(
                session,
                claim_id=claims[0].id,
                verifier_username="reviewer1",
                decision="wrong_value",
            )

    def test_verify_nonexistent_claim_raises(self, session):
        with pytest.raises(ValueError, match="not found"):
            trust_service.verify_claim(
                session,
                claim_id=99999,
                verifier_username="reviewer1",
                decision="approved",
            )
