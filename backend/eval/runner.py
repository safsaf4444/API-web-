"""
Benchmark eval runner — executes an EvalRun row end-to-end.

Called by eval_router.py as a BackgroundTask.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlmodel import Session

from backend.eval.benchmark_loader import get_task_type, load_from_db
from backend.eval.metrics import compute_for_task
from backend.eval.thresholds import get_threshold
from backend.models_trust import EvalMetric, EvalRun
from backend.services import audit_service

logger = logging.getLogger(__name__)


def execute_eval_run(session: Session, run_id: int) -> None:
    """
    Load items for the EvalRun's dataset, call the engine for each item,
    compute metrics, compare to thresholds, and write EvalMetric rows.
    """
    run = session.get(EvalRun, run_id)
    if run is None:
        logger.error("execute_eval_run: EvalRun %s not found", run_id)
        return

    _mark_started(session, run)

    try:
        task_type = get_task_type(session, run.dataset_id)
        items = load_from_db(session, run.dataset_id)

        if not items:
            _mark_failed(session, run, "No benchmark items found for dataset.")
            return

        # Gather engine function
        engine_fn = _resolve_engine(run.provider, run.model)
        if engine_fn is None:
            _mark_failed(session, run, f"No engine available for provider={run.provider}")
            return

        # Run each item through the engine and collect per-item scores
        per_metric: Dict[str, List[float]] = defaultdict(list)

        for item in items:
            try:
                predicted = engine_fn(item["input_text"])
            except Exception as exc:
                logger.warning("Eval item %s engine call failed: %s", item.get("id"), exc)
                predicted = ""

            scores = compute_for_task(task_type, predicted, item["expected_output"])
            for metric_name, score in scores.items():
                per_metric[metric_name].append(score)

        # Aggregate (mean) and persist
        for metric_name, scores in per_metric.items():
            mean_val = sum(scores) / len(scores) if scores else 0.0
            threshold = get_threshold(task_type, metric_name)
            passed = (mean_val >= threshold) if threshold is not None else None

            metric_row = EvalMetric(
                eval_run_id=run_id,
                metric_name=metric_name,
                metric_value=round(mean_val, 4),
                threshold=threshold,
                passed=passed,
            )
            session.add(metric_row)

        run.status = "completed"
        run.completed_at = datetime.now(timezone.utc)
        session.add(run)
        session.commit()

        audit_service.log(
            session,
            event="eval.run_completed",
            actor=run.triggered_by,
            detail=f"run_id={run_id} items={len(items)} task_type={task_type}",
        )

    except Exception as exc:
        logger.error("execute_eval_run %s crashed: %s", run_id, exc)
        _mark_failed(session, run, str(exc)[:500])


# ── helpers ───────────────────────────────────────────────────────────────────

def _mark_started(session: Session, run: EvalRun) -> None:
    run.status = "running"
    session.add(run)
    session.commit()


def _mark_failed(session: Session, run: EvalRun, error: str) -> None:
    run.status = "failed"
    run.error_message = error
    run.completed_at = datetime.now(timezone.utc)
    session.add(run)
    session.commit()


def _resolve_engine(provider: str, model: str):
    """Return a callable(prompt: str) -> str or None if not configured."""
    try:
        import os
        from backend.services.ai_engine import run as engine_run

        provider_lower = provider.lower()

        def call(prompt: str) -> str:
            if provider_lower == "gemini":
                key = os.getenv("GEMINI_API_KEY", "")
                return engine_run(
                    system="You are a precise research assistant.",
                    user=prompt,
                    openai_key="",
                    gemini_key=key,
                    groq_key="",
                    ollama_base="",
                    model=model,
                )
            elif provider_lower == "openai":
                key = os.getenv("OPENAI_API_KEY", "")
                return engine_run(
                    system="You are a precise research assistant.",
                    user=prompt,
                    openai_key=key,
                    gemini_key="",
                    groq_key="",
                    ollama_base="",
                    model=model,
                )
            else:
                return ""

        return call
    except Exception as exc:
        logger.error("_resolve_engine failed: %s", exc)
        return None
