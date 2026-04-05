"""
Minimum passing thresholds for each benchmark task type.
An EvalRun "passes" only when ALL its metrics meet or exceed their threshold.
"""
from __future__ import annotations

from typing import Dict, Optional


# {task_type: {metric_name: min_value}}
THRESHOLDS: Dict[str, Dict[str, float]] = {
    "pico_extraction": {
        "exact_match": 0.70,
        "f1":          0.75,
    },
    "screening": {
        "accuracy":  0.85,
        "precision": 0.80,
        "recall":    0.80,
        "f1":        0.80,
    },
    "statistics": {
        "exact_match": 0.75,
        "f1":          0.78,
    },
    "summarisation": {
        "rouge_l": 0.40,
    },
    "default": {
        "f1": 0.70,
    },
}


def get_threshold(task_type: str, metric_name: str) -> Optional[float]:
    task_map = THRESHOLDS.get(task_type, THRESHOLDS["default"])
    return task_map.get(metric_name)
