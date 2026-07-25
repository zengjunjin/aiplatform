"""Evaluation API - RAGAS evaluation endpoints."""

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_admin_user
from app.config import RATE_LIMIT_DEFAULT, RATE_LIMIT_EXTREME
from app.core.middleware import limiter
from app.database import get_db
from app.db.user import User
from app.schemas.common import ok, paginated_ok
from app.services import evaluation_service

router = APIRouter(prefix="/evaluation", tags=["evaluation"])


@router.post("/runs")
@limiter.limit(RATE_LIMIT_EXTREME)
async def trigger_evaluation(
    request: Request,
    kb_id: int = Query(..., description="Knowledge base ID"),
    num_questions: int = Query(50, ge=5, le=200, description="Number of evaluation questions"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Trigger a new evaluation run for a knowledge base (admin only).

    Dispatches a Celery task to run evaluation asynchronously.
    Returns immediately with run_id; poll GET /runs/{run_id} for status.

    业务逻辑（KB 读权限校验 get_kb_for_read、创建 run、Celery 派发）下沉到
    evaluation_service.trigger_evaluation。本层仅做参数绑定与响应格式化。
    """
    run, task = await evaluation_service.trigger_evaluation(kb_id, num_questions, admin.id, db)
    return ok(
        data={
            "run_id": run.id,
            "status": "pending",
            "task_id": task.id,
            "message": "Evaluation has been queued. Poll GET /evaluation/runs/{run_id} for status.",
        }
    )


@router.get("/runs")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def list_evaluation_runs(
    request: Request,
    kb_id: int | None = Query(None, description="Filter by knowledge base ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """List evaluation run history (admin only)."""
    runs, total = await evaluation_service.list_evaluation_runs(db, kb_id, page, page_size)
    items = [
        {
            "id": run.id,
            "knowledge_base_id": run.knowledge_base_id,
            "status": run.status or "pending",
            "metrics": run.metrics,
            "total_questions": run.total_questions,
            "prompt_version": run.prompt_version,
            "retriever_alpha": run.retriever_alpha,
            "retriever_top_k": run.retriever_top_k,
            "rerank_top_k": run.rerank_top_k,
            "trigger_source": run.trigger_source,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "error_message": run.error_message,
        }
        for run in runs
    ]

    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.get("/runs/{run_id}")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_evaluation_run(
    run_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Get single evaluation run details (admin only)."""
    run = await evaluation_service.get_evaluation_run(run_id, admin.id, db)
    return ok(
        data={
            "id": run.id,
            "knowledge_base_id": run.knowledge_base_id,
            "status": run.status or "pending",
            "metrics": run.metrics,
            "total_questions": run.total_questions,
            "prompt_version": run.prompt_version,
            "retriever_alpha": run.retriever_alpha,
            "retriever_top_k": run.retriever_top_k,
            "rerank_top_k": run.rerank_top_k,
            "trigger_source": run.trigger_source,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "error_message": run.error_message,
        }
    )


@router.get("/runs/{run_id}/results")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def get_evaluation_results(
    run_id: int,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Get per-question results for an evaluation run (admin only)."""
    results, total = await evaluation_service.get_evaluation_results(
        run_id, admin.id, db, page, page_size
    )
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
            "question_type": r.question_type,
            "difficulty": r.difficulty,
            "latency_ms": r.latency_ms,
            "token_count": r.token_count,
        }
        for r in results
    ]

    return paginated_ok(items=items, total=total, page=page, page_size=page_size)


@router.delete("/runs/{run_id}")
@limiter.limit(RATE_LIMIT_DEFAULT)
async def delete_evaluation_run(
    run_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    """Delete an evaluation run and its results (admin only).

    业务逻辑（run 查找、KB admin 权限校验 get_kb_for_admin、级联删除）下沉到
    evaluation_service.delete_evaluation_run。本层仅做参数绑定与响应格式化。
    """
    await evaluation_service.delete_evaluation_run(run_id, admin.id, db)
    return ok(data={"deleted": True})
