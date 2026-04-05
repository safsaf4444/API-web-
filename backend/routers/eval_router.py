"""
Eval / Benchmark REST endpoints.

Requires the "eval_runner" or "admin" role for write operations.
Read operations are accessible to any authenticated user.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlmodel import Session, select

from backend.db import get_session
from backend.deps.auth import get_current_user, require_role
from backend.models import User
from backend.models_trust import BenchmarkDataset, BenchmarkItem, EvalMetric, EvalRun
from backend.schemas_trust import (
    BenchmarkDatasetCreate,
    BenchmarkDatasetRead,
    BenchmarkItemCreate,
    BenchmarkItemRead,
    EvalRunCreate,
    EvalRunDetail,
    EvalRunRead,
    EvalMetricRead,
)
from backend.services import audit_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/eval", tags=["eval"])


# ── Benchmark datasets ────────────────────────────────────────────────────────

@router.get("/datasets", response_model=List[BenchmarkDatasetRead])
def list_datasets(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return list(session.exec(select(BenchmarkDataset)).all())


@router.post("/datasets", response_model=BenchmarkDatasetRead)
def create_dataset(
    payload: BenchmarkDatasetCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("eval_runner")),
):
    ds = BenchmarkDataset(
        name=payload.name,
        task_type=payload.task_type,
        description=payload.description,
    )
    session.add(ds)
    session.commit()
    session.refresh(ds)
    audit_service.log(
        session,
        event="benchmark.dataset_created",
        actor=current_user.username,
        detail=f"name={payload.name} task_type={payload.task_type}",
    )
    return ds


@router.get("/datasets/{dataset_id}", response_model=BenchmarkDatasetRead)
def get_dataset(
    dataset_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    ds = session.get(BenchmarkDataset, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return ds


# ── Benchmark items ───────────────────────────────────────────────────────────

@router.get("/datasets/{dataset_id}/items", response_model=List[BenchmarkItemRead])
def list_items(
    dataset_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return list(
        session.exec(select(BenchmarkItem).where(BenchmarkItem.dataset_id == dataset_id)).all()
    )


@router.post("/datasets/{dataset_id}/items", response_model=BenchmarkItemRead)
def create_item(
    dataset_id: int,
    payload: BenchmarkItemCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("eval_runner")),
):
    ds = session.get(BenchmarkDataset, dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    import json as _json
    item = BenchmarkItem(
        dataset_id=dataset_id,
        input_text=payload.input_text,
        expected_output=payload.expected_output,
        metadata_json=_json.dumps(payload.metadata_json) if payload.metadata_json else None,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


# ── Eval runs ─────────────────────────────────────────────────────────────────

@router.get("/runs", response_model=List[EvalRunRead])
def list_eval_runs(
    dataset_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    stmt = select(EvalRun).order_by(EvalRun.id.desc())
    if dataset_id is not None:
        stmt = stmt.where(EvalRun.dataset_id == dataset_id)
    return list(session.exec(stmt).all())


@router.get("/runs/{run_id}", response_model=EvalRunDetail)
def get_eval_run(
    run_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    run = session.get(EvalRun, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="EvalRun not found")

    metrics = list(session.exec(select(EvalMetric).where(EvalMetric.eval_run_id == run_id)).all())
    data = EvalRunDetail.model_validate(run)
    data.metrics = metrics
    return data


@router.post("/runs", response_model=EvalRunRead)
def trigger_eval_run(
    payload: EvalRunCreate,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User = Depends(require_role("eval_runner")),
):
    """Trigger a benchmark eval run (executes asynchronously in background)."""
    ds = session.get(BenchmarkDataset, payload.dataset_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Dataset not found")

    run = EvalRun(
        dataset_id=payload.dataset_id,
        triggered_by=current_user.username,
        provider=payload.provider,
        model=payload.model,
        prompt_version_id=payload.prompt_version_id,
        status="pending",
    )
    session.add(run)
    session.commit()
    session.refresh(run)

    audit_service.log(
        session,
        event="eval.run_triggered",
        actor=current_user.username,
        detail=f"run_id={run.id} dataset={payload.dataset_id} provider={payload.provider}",
    )

    # Kick off background execution
    background_tasks.add_task(_run_eval_background, run.id)
    return run


def _run_eval_background(run_id: int) -> None:
    """Background task: load runner module lazily to avoid import at startup."""
    try:
        from backend.db import get_engine
        from backend.eval.runner import execute_eval_run
        from sqlmodel import Session as _Session

        engine = get_engine()
        with _Session(engine) as session:
            execute_eval_run(session, run_id)
    except Exception as exc:
        logger.error("Background eval run %s failed: %s", run_id, exc)


# ── Metrics ───────────────────────────────────────────────────────────────────

@router.get("/runs/{run_id}/metrics", response_model=List[EvalMetricRead])
def list_metrics(
    run_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return list(session.exec(select(EvalMetric).where(EvalMetric.eval_run_id == run_id)).all())
