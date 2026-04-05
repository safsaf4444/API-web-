"""Unit tests for backend/services/guardrail.py"""
import pytest
from backend.services.guardrail import GuardrailBlocked, PolicyEngine


@pytest.fixture
def engine():
    return PolicyEngine()


class TestPolicyEngine:
    def test_pass_on_clean_output(self, engine):
        ctx = {
            "endpoint": "summarise",
            "prompt": "Summarise this paper.",
            "output": "This RCT found that metformin reduced HbA1c by 1.2% over 24 weeks.",
            "flagged": False,
            "flag_reason": None,
            "evidence_basis": "rct",
            "confidence": 0.80,
            "pre_validation_failed": False,
        }
        result = engine.evaluate(ctx)
        assert result.action == "pass"

    def test_block_on_pre_validation_failure(self, engine):
        ctx = {
            "endpoint": "summarise",
            "prompt": "",
            "output": "something",
            "flagged": False,
            "flag_reason": None,
            "evidence_basis": "unknown",
            "confidence": 0.5,
            "pre_validation_failed": True,
        }
        with pytest.raises(GuardrailBlocked) as exc_info:
            engine.evaluate(ctx)
        assert exc_info.value.policy_name == "block_pre_validation_failure"

    def test_degrade_on_empty_output(self, engine):
        ctx = {
            "endpoint": "summarise",
            "prompt": "Summarise this.",
            "output": "",
            "flagged": False,
            "flag_reason": None,
            "evidence_basis": "unknown",
            "confidence": 0.5,
            "pre_validation_failed": False,
        }
        result = engine.evaluate(ctx)
        assert result.action == "degrade"
        assert result.degraded_response is not None

    def test_require_review_on_flagged(self, engine):
        ctx = {
            "endpoint": "summarise",
            "prompt": "Summarise.",
            "output": "Some output.",
            "flagged": True,
            "flag_reason": "model_self_reported_hallucination",
            "evidence_basis": "cohort",
            "confidence": 0.6,
            "pre_validation_failed": False,
        }
        result = engine.evaluate(ctx)
        assert result.action == "require_review"

    def test_require_review_high_confidence_weak_evidence(self, engine):
        ctx = {
            "endpoint": "summarise",
            "prompt": "Summarise.",
            "output": "Very confident output.",
            "flagged": False,
            "flag_reason": None,
            "evidence_basis": "expert_opinion",
            "confidence": 0.90,
            "pre_validation_failed": False,
        }
        result = engine.evaluate(ctx)
        assert result.action == "require_review"
        assert result.policy_name == "require_review_high_confidence_weak_evidence"
