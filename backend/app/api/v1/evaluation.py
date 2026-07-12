"""Evaluation API - RAGAS evaluation endpoints."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.database import get_db
from app.api.deps import get_admin_user
from app.db.user import User
from app.db.evaluation import EvaluationRun, EvaluationResult, EvaluationStatus
from app.schemas.common import ok, paginated_ok
from app.core.exceptions import NotFoundError
from loguru import logger

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("/runs")
async def trigger_evaluation(
    kb_id: int = Query(..., description="Knowledge base ID"),
    num_questions: int = Query(50, ge=5, le=200, description="Number of evaluation questions"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Trigger a new evaluation run for a knowledge base (admin only).

    Dispatches a Celery task to run evaluation asynchronously.
    Returns immediately with run_id; poll GET /runs/{run_id} for status.
    """
    # Verify KB exists
    from app.db.knowledge_base import KnowledgeBase
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    if not kb_result.scalar_one_or_none():
        raise NotFoundError("Knowledge base not found")

    # Create evaluation run with PENDING status
    run = EvaluationRun(
        knowledge_base_id=kb_id,
        status=EvaluationStatus.PENDING,
        total_questions=num_questions,
        created_by=admin.id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # Dispatch async Celery task
    from app.tasks.evaluation_task import run_evaluation_task
    task = run_evaluation_task.delay(run.id)
    logger.info(f"Evaluation run {run.id} dispatched: task_id={task.id} kb={kb_id} questions={num_questions}")

    return ok(data={
        "run_id": run.id,
        "status": "pending",
        "task_id": task.id,
        "message": "Evaluation has been queued. Poll GET /evaluation/runs/{run_id} for status.",
    })


@router.get("/runs")
async def list_evaluation_runs(
    kb_id: int | None = Query(None, description="Filter by knowledge base ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """List evaluation run history (admin only)."""
    query = select(EvaluationRun)
    count_query = select(func.count()).select_from(EvaluationRun)

    if kb_id is not None:
        query = query.where(EvaluationRun.knowledge_base_id == kb_id)
        count_query = count_query.where(EvaluationRun.knowledge_base_id == kb_id)

    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    result = await db.execute(
        query
        .order_by(EvaluationRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    runs = result.scalars().all()

    items = [
        {
            "id": run.id,
            "knowledge_base_id": run.knowledge_base_id,
            "status": run.status or "pending",
            "metrics": run.metrics,
            "total_questions": run.total_questions,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "error_message": run.error_message,
        }
        for run in runs
    ]

    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/runs/{run_id}")
async def get_evaluation_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Get single evaluation run details (admin only)."""
    result = await db.execute(select(EvaluationRun).where(EvaluationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Evaluation run not found")

    return ok(data={
        "id": run.id,
        "knowledge_base_id": run.knowledge_base_id,
        "status": run.status or "pending",
        "metrics": run.metrics,
        "total_questions": run.total_questions,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "error_message": run.error_message,
    })


@router.get("/runs/{run_id}/results")
async def get_evaluation_results(
    run_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Get per-question results for an evaluation run (admin only)."""
    result = await db.execute(select(EvaluationRun).where(EvaluationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Evaluation run not found")

    count_result = await db.execute(
        select(func.count()).select_from(EvaluationResult).where(EvaluationResult.run_id == run_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(EvaluationResult)
        .where(EvaluationResult.run_id == run_id)
        .order_by(EvaluationResult.id.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    results = result.scalars().all()

    items = [
        {
            "id": r.id,
            "question": r.question,
            "ground_truth": r.ground_truth,
            "generated_answer": r.generated_answer,
            "contexts": r.contexts,
            "faithfulness": r.faithfulness,
            "answer_relevancy": r.answer_relevancy,
            "context_precision": r.context_precision,
            "context_recall": r.context_recall,
        }
        for r in results
    ]

    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.delete("/runs/{run_id}")
async def delete_evaluation_run(
    run_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Delete an evaluation run and its results (admin only)."""
    result = await db.execute(select(EvaluationRun).where(EvaluationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Evaluation run not found")

    # Delete associated results first (CASCADE should handle this, but be explicit)
    from sqlalchemy import delete
    await db.execute(delete(EvaluationResult).where(EvaluationResult.run_id == run_id))
    await db.delete(run)
    await db.commit()

    return ok(data={"deleted": True})