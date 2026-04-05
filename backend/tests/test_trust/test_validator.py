"""Unit tests for backend/services/validator.py"""
import pytest
from backend.services.validator import PostValidator, PreValidator, ValidationError


class TestPreValidator:
    def setup_method(self):
        self.v = PreValidator()

    def test_passes_normal_prompt(self):
        warnings = self.v.validate(endpoint="summarise", prompt="Summarise this paper about diabetes treatment outcomes.")
        assert isinstance(warnings, list)

    def test_raises_on_empty_prompt(self):
        with pytest.raises(ValidationError) as exc_info:
            self.v.validate(endpoint="summarise", prompt="hi")
        assert exc_info.value.code == "prompt_too_short"

    def test_raises_on_too_long_prompt(self):
        with pytest.raises(ValidationError) as exc_info:
            self.v.validate(endpoint="summarise", prompt="word " * 15000)
        assert exc_info.value.code == "prompt_too_long"

    def test_warns_on_pii(self):
        warnings = self.v.validate(
            endpoint="summarise",
            prompt="Patient John Smith, email john@example.com, has diabetes."
        )
        assert any("PII" in w for w in warnings)

    def test_warns_on_clinical_decision(self):
        warnings = self.v.validate(
            endpoint="clinical",
            prompt="Should I prescribe metformin to this patient with HbA1c 9%?"
        )
        assert any("clinical decision" in w.lower() for w in warnings)


class TestPostValidator:
    def setup_method(self):
        self.v = PostValidator()

    def test_passes_normal_output(self):
        result = self.v.validate(
            output="This study found that metformin significantly reduced HbA1c in type 2 diabetes patients.",
            endpoint="summarise",
        )
        assert result["flagged"] is False
        assert result["flag_reason"] is None

    def test_flags_empty_output(self):
        result = self.v.validate(output="", endpoint="summarise")
        assert result["flagged"] is True
        assert result["flag_reason"] == "empty_output"

    def test_flags_hallucination_keywords(self):
        result = self.v.validate(
            output="Note: I may have hallucinated some of these statistics.",
            endpoint="summarise",
        )
        assert result["flagged"] is True
        assert result["flag_reason"] == "model_self_reported_hallucination"

    def test_warns_on_short_output(self):
        result = self.v.validate(output="Too short.", endpoint="summarise")
        assert any("short" in w.lower() for w in result["warnings"])

    def test_warns_on_clinical_disclaimer(self):
        result = self.v.validate(
            output="Based on the evidence... This is not medical advice. Consult a doctor.",
            endpoint="summarise",
        )
        assert any("disclaimer" in w.lower() for w in result["warnings"])
