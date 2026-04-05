"""
Pre- and post-call validators for AI engine calls.

PreValidator  — checks inputs before the engine call
PostValidator — checks outputs after the engine call returns

Both raise ValidationError (subclass of ValueError) when a check fails.
Guards are deliberately conservative: they emit warnings rather than
hard-failures unless the condition is clearly dangerous.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class ValidationError(ValueError):
    """Raised by pre/post validators when a hard check fails."""
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


# ── Shared constants ──────────────────────────────────────────────────────────

# Minimum word count in the user prompt before we'll submit to the engine
_MIN_PROMPT_WORDS = 3
_MAX_PROMPT_CHARS = 60_000

# Patterns that suggest PII in prompts (rough heuristics only)
_PII_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),          # US SSN
    re.compile(r"\b\d{16}\b"),                       # credit card-ish
    re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"),  # email
]

# Phrases that indicate clinical decision-making — require disclaimer
_CLINICAL_DECISION_PHRASES = [
    "prescribe", "dosage for patient", "should i give", "can i administer",
    "treatment plan for", "diagnose", "my patient has",
]

_WARNING_KEYWORDS = ["hallucin", "made up", "fabricat", "invent"]


# ── PreValidator ─────────────────────────────────────────────────────────────

class PreValidator:
    """
    Validates the inputs to an AI engine call.

    Usage:
        pv = PreValidator()
        warnings = pv.validate(endpoint="summarise", prompt="...", context={})
        # warnings is a list of non-fatal advisory strings
        # raises ValidationError for hard failures
    """

    def validate(
        self,
        *,
        endpoint: str,
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        warnings: List[str] = []

        # Hard: empty / too short prompt
        word_count = len(prompt.split())
        if word_count < _MIN_PROMPT_WORDS:
            raise ValidationError(
                "prompt_too_short",
                f"Prompt has only {word_count} words (minimum {_MIN_PROMPT_WORDS}).",
            )

        # Hard: prompt exceeds context window budget
        if len(prompt) > _MAX_PROMPT_CHARS:
            raise ValidationError(
                "prompt_too_long",
                f"Prompt is {len(prompt)} characters (maximum {_MAX_PROMPT_CHARS}).",
            )

        # Advisory: PII detection
        for pat in _PII_PATTERNS:
            if pat.search(prompt):
                warnings.append("Possible PII detected in prompt — please anonymise patient data.")
                break

        # Advisory: clinical decision framing
        lower = prompt.lower()
        for phrase in _CLINICAL_DECISION_PHRASES:
            if phrase in lower:
                warnings.append(
                    "Prompt appears to request a clinical decision. "
                    "AI output must be reviewed by a qualified clinician before acting on it."
                )
                break

        return warnings


# ── PostValidator ─────────────────────────────────────────────────────────────

class PostValidator:
    """
    Validates the output from an AI engine call.

    Usage:
        pov = PostValidator()
        result = pov.validate(output="...", endpoint="summarise", context={})
        # result["warnings"]  — advisory list
        # result["flagged"]   — bool
        # result["flag_reason"] — str | None
    """

    def validate(
        self,
        *,
        output: str,
        endpoint: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        warnings: List[str] = []
        flagged = False
        flag_reason: Optional[str] = None

        if not output or not output.strip():
            flagged = True
            flag_reason = "empty_output"
            return {"warnings": warnings, "flagged": flagged, "flag_reason": flag_reason}

        lower = output.lower()

        # Flag: model self-reports hallucination
        for kw in _WARNING_KEYWORDS:
            if kw in lower:
                flagged = True
                flag_reason = "model_self_reported_hallucination"
                warnings.append("Model output contains self-reported uncertainty keywords.")
                break

        # Advisory: output is very short
        if len(output.strip().split()) < 10:
            warnings.append("Output is very short — consider prompting for more detail.")

        # Advisory: output contains a disclaimer about clinical use
        if any(d in lower for d in ["not medical advice", "consult a doctor", "seek professional"]):
            warnings.append(
                "Output includes a clinical disclaimer — ensure users see this text."
            )

        # Advisory: output is suspiciously long (possible runaway generation)
        if len(output) > 40_000:
            warnings.append("Output exceeds 40 000 characters — check for repeated content.")

        return {
            "warnings": warnings,
            "flagged": flagged,
            "flag_reason": flag_reason,
        }
