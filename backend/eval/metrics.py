"""
Metric computation functions for benchmark evaluation.

All functions accept (predicted: str, expected: str) and return a float in [0, 1].
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Dict


def exact_match(predicted: str, expected: str) -> float:
    return 1.0 if predicted.strip().lower() == expected.strip().lower() else 0.0


def token_f1(predicted: str, expected: str) -> float:
    """Token-level F1 (bag of words), standard SQuAD-style."""
    pred_tokens = _tokenize(predicted)
    gold_tokens = _tokenize(expected)
    if not pred_tokens or not gold_tokens:
        return 0.0

    common = Counter(pred_tokens) & Counter(gold_tokens)
    num_common = sum(common.values())
    if num_common == 0:
        return 0.0

    precision = num_common / len(pred_tokens)
    recall = num_common / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def rouge_l(predicted: str, expected: str) -> float:
    """ROUGE-L based on longest common subsequence."""
    pred_tokens = _tokenize(predicted)
    gold_tokens = _tokenize(expected)
    if not pred_tokens or not gold_tokens:
        return 0.0

    lcs_len = _lcs_length(pred_tokens, gold_tokens)
    precision = lcs_len / len(pred_tokens)
    recall = lcs_len / len(gold_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def accuracy(predicted: str, expected: str) -> float:
    return exact_match(predicted, expected)


# ---------------------------------------------------------------------------
# Registry — map metric name → function
# ---------------------------------------------------------------------------

METRIC_REGISTRY: Dict[str, callable] = {
    "exact_match": exact_match,
    "f1":          token_f1,
    "rouge_l":     rouge_l,
    "accuracy":    accuracy,
    "precision":   None,   # computed during eval loop, not item-level
    "recall":      None,
}


def compute_for_task(task_type: str, predicted: str, expected: str) -> Dict[str, float]:
    """Return {metric_name: score} for all metrics relevant to a task type."""
    from backend.eval.thresholds import THRESHOLDS

    task_metrics = list(THRESHOLDS.get(task_type, THRESHOLDS["default"]).keys())
    results: Dict[str, float] = {}
    for name in task_metrics:
        fn = METRIC_REGISTRY.get(name)
        if fn is not None:
            try:
                results[name] = fn(predicted, expected)
            except Exception:
                results[name] = 0.0
    return results


# ── helpers ───────────────────────────────────────────────────────────────────

def _tokenize(text: str):
    return re.findall(r"\w+", text.lower())


def _lcs_length(a: list, b: list) -> int:
    m, n = len(a), len(b)
    # Space-optimised O(n) LCS
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(curr[j - 1], prev[j])
        prev = curr
    return prev[n]
