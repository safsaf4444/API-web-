"""
Load benchmark items from either the database or bundled JSON files.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List

from sqlmodel import Session, select

from backend.models_trust import BenchmarkDataset, BenchmarkItem

_DATASETS_DIR = Path(__file__).parent / "datasets"


def load_from_db(session: Session, dataset_id: int) -> List[Dict[str, Any]]:
    items = list(
        session.exec(select(BenchmarkItem).where(BenchmarkItem.dataset_id == dataset_id)).all()
    )
    return [
        {
            "id": item.id,
            "input_text": item.input_text,
            "expected_output": item.expected_output,
            "metadata": json.loads(item.metadata_json) if item.metadata_json else {},
        }
        for item in items
    ]


def load_from_file(filename: str) -> List[Dict[str, Any]]:
    """Load items from a bundled JSON file in backend/eval/datasets/."""
    path = _DATASETS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Benchmark file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, list) else data.get("items", [])


def get_task_type(session: Session, dataset_id: int) -> str:
    ds = session.get(BenchmarkDataset, dataset_id)
    return ds.task_type if ds else "default"
