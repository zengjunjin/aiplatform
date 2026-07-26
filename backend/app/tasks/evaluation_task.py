"""Celery task: run RAGAS evaluation asynchronously.

Uses synchronous SQLAlchemy session (psycopg2) for Celery worker.

Task 5:  幂等性检查（run_id 维度去重，乐观锁抢占）
Task 8:  串行评估改并发（asyncio.gather + Semaphore）
Task 9:  sync session 用 asyncio.to_thread 包装
Task 11: run_evaluation_task 拆分为子函数（主函数 ≤ 50 行）
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.core.evaluation import aggregate_metrics
from app.db.document_chunk import DocumentChunk
from app.db.evaluation import EvaluationResult, EvaluationRun, EvaluationStatus
from app.db.sync_session import get_sync_session
from app.tasks.celery_app import celery_app


@celery_app.task(
    bind=True,
    max_retries=settings.TASK_MAX_RETRIES_EVALUATION,
    name="app.tasks.evaluation_task.run_evaluation",
    # H4: RAGAS 评估需要多次 LLM 调用（4 指标 * N 问题），qwen2.5:1.5b 响应较慢，
    # 默认 300s/240s 不够。放宽到 1800s/1500s（30/25 分钟）。
    time_limit=1800,
    soft_time_limit=1500,
)
def run_evaluation_task(self, run_id: int):
    """Run evaluation asynchronously in Celery worker.

    Sync Celery entry point — creates an event loop and delegates to
    the async orchestrator ``_run_evaluation_async``.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run_evaluation_async(run_id))
    finally:
        loop.close()


async def _run_evaluation_async(run_id: int) -> dict:
    """主函数 (Task 11: ≤ 50 行) — 编排子函数完成评估流程。

    Steps:
    1. Task 5: 幂等性抢占 run
    2. Task 9: 准备数据集 (sync session wrapped in asyncio.to_thread)
    3. Task 8: 并发执行评估
    4. 计算并持久化指标
    """
    session = get_sync_session()
    try:
        run = await _claim_run(session, run_id)
        if run is None:
            logger.info(f"Evaluation run {run_id} already in progress or completed")
            return {"error": "already in progress or completed"}

        kb_id = run.knowledge_base_id
        dataset = await _prepare_dataset(session, run)
        if not dataset:
            await _update_run_status(
                session,
                run_id,
                EvaluationStatus.FAILED,
                "No chunks available to generate test dataset",
            )
            return {"error": "No chunks available"}

        results = await _run_evaluations(kb_id, dataset)
        return await _compute_and_persist_metrics(session, run_id, results)
    except Exception:
        logger.exception(f"Evaluation run {run_id} failed")
        if session.is_active:
            try:
                session.rollback()
            except Exception as re:
                logger.debug(f"Evaluation first rollback failed: {re}")
        try:
            await _update_run_status(session, run_id, EvaluationStatus.FAILED, "评估失败")
        except Exception as commit_err:
            logger.error(f"Failed to update evaluation run status: {commit_err}")
            if session.is_active:
                try:
                    session.rollback()
                except Exception as re:
                    logger.debug(f"Evaluation second rollback failed: {re}")
        return {"error": "评估失败"}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Task 5: 幂等性检查（乐观锁抢占 run）
# ---------------------------------------------------------------------------


async def _claim_run(session: Session, run_id: int) -> EvaluationRun | None:
    """Task 5: 幂等性 - 乐观锁抢占 run。

    仅当 status=pending 时原子更新为 running，避免并发重复执行。
    返回 None 表示 run 不存在或已被其他 worker 抢占。
    """

    def _sync_claim():
        result = session.execute(
            update(EvaluationRun)
            .where(
                EvaluationRun.id == run_id,
                EvaluationRun.status == EvaluationStatus.PENDING.value,
            )
            .values(
                status=EvaluationStatus.RUNNING.value,
                started_at=datetime.now(UTC),
            )
            .returning(EvaluationRun.id)
        )
        claimed = result.scalar_one_or_none()
        session.commit()
        if claimed is None:
            return None
        return session.get(EvaluationRun, run_id)

    return await asyncio.to_thread(_sync_claim)


async def _update_run_status(
    session: Session,
    run_id: int,
    status: EvaluationStatus,
    error_message: str | None = None,
) -> None:
    """更新 run 状态 (sync session 用 asyncio.to_thread 包装)。"""

    def _sync_update():
        run = session.get(EvaluationRun, run_id)
        if run:
            run.status = status
            run.error_message = error_message
            run.completed_at = datetime.now(UTC)
        session.commit()

    await asyncio.to_thread(_sync_update)


# ---------------------------------------------------------------------------
# Task 9: sync session 用 asyncio.to_thread 包装
# ---------------------------------------------------------------------------


async def _prepare_dataset(session: Session, run: EvaluationRun) -> list[dict]:
    """Task 9: 准备评估数据集。

    sync session 查询用 asyncio.to_thread 包装，避免阻塞事件循环。
    LLM 问题生成保持 async（内部已有 Semaphore 并发控制）。
    """

    def _sync_fetch_chunks():
        result = session.execute(
            select(DocumentChunk)
            .where(DocumentChunk.kb_id == run.knowledge_base_id)
            .order_by(func.random())
            .limit(run.total_questions)
        )
        return result.scalars().all()

    chunks = await asyncio.to_thread(_sync_fetch_chunks)
    if not chunks:
        return []

    def _sync_update_count():
        run.total_questions = len(chunks)
        session.commit()

    await asyncio.to_thread(_sync_update_count)

    return await _generate_dataset_async(chunks)


async def _generate_dataset_async(chunks: list) -> list[dict]:
    """Async dataset generation: 并发用 LLM Provider 生成问题。

    Task 14.3: 移除 requests.post 同步调用，改用 OllamaLLMProvider.chat() 异步调用。
    Task 8 风格: 用 asyncio.gather + Semaphore(8) 限制并发度。
    Task 1.5: 数据集条目包含 question_type/difficulty。
    """
    from app.models.ollama_provider import OllamaLLMProvider

    target_chunks = chunks
    # Task 14.3: 创建独立 OllamaLLMProvider 实例（避免 ModelFactory 单例的 event loop 绑定问题）
    llm = OllamaLLMProvider()
    semaphore = asyncio.Semaphore(settings.EVAL_CONCURRENCY)

    async def _gen_with_sem(idx: int, chunk_content: str) -> dict | None:
        async with semaphore:
            question_data = await _generate_question_async(chunk_content, llm)
            if question_data:
                return {
                    "question": question_data["question"],
                    "ground_truth": target_chunks[idx].content,
                    "contexts": [target_chunks[idx].content],
                    "question_type": question_data["question_type"],
                    "difficulty": question_data["difficulty"],
                }
            return None

    try:
        tasks = [_gen_with_sem(idx, chunk.content) for idx, chunk in enumerate(target_chunks)]
        dataset = await asyncio.gather(*tasks, return_exceptions=False)
    finally:
        await llm.close()

    # 过滤掉 None（生成失败的）
    return [d for d in dataset if d is not None]


async def _generate_question_async(chunk_content: str, llm: Any) -> dict | None:
    """Generate a question from chunk content using async LLM Provider.

    Task 14.3: 用 llm.chat() 替代 requests.post 同步调用。
    Task 1.7: prompt 与清理逻辑改用 core/evaluation.py 公共函数。
    Task 1.5: 返回 dict 包含 question/question_type/difficulty。
    llm: BaseLLMProvider 实例（如 OllamaLLMProvider）。
    """
    from app.core.evaluation import build_question_prompt, parse_question_response

    prompt = build_question_prompt(chunk_content)

    try:
        response = await llm.chat([{"role": "user", "content": prompt}], temperature=0.7)
        return parse_question_response(response)
    except Exception as e:
        logger.warning(f"Failed to generate question: {e}")
        return None


# ---------------------------------------------------------------------------
# Task 8: 串行评估改并发（asyncio.gather + Semaphore）
# ---------------------------------------------------------------------------


async def _run_evaluations(kb_id: int, dataset: list[dict]) -> list[dict]:
    """Task 8: 并发执行评估。

    用 asyncio.gather + Semaphore 替代串行 for 循环，
    Semaphore 复用 settings.EVAL_CONCURRENCY 限制并发度。
    """
    semaphore = asyncio.Semaphore(settings.EVAL_CONCURRENCY)

    async def _eval_single(item: dict) -> dict:
        async with semaphore:
            return await _run_single_evaluation(kb_id, item)

    results = await asyncio.gather(
        *[_eval_single(item) for item in dataset],
        return_exceptions=True,
    )

    # 将异常转换为错误条目（保留原有异常处理语义）
    processed = []
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error(f"Failed question {i + 1}/{len(dataset)}: {r}")
            processed.append(
                {
                    "question": dataset[i]["question"],
                    "ground_truth": dataset[i]["ground_truth"],
                    "answer": "评估失败，请稍后重试",
                    "contexts": dataset[i].get("contexts", []),
                }
            )
        else:
            processed.append(r)
    return processed


async def _run_single_evaluation(kb_id: int, item: dict) -> dict:
    """对单个问题执行 RAG 检索 + RAGAS 指标计算。"""
    from app.core.evaluation import _compute_ragas_metrics
    from app.services.evaluation_service import get_rag_answer

    question = item["question"]
    ground_truth = item["ground_truth"]

    answer, contexts = await get_rag_answer(question, kb_id)
    metrics = await _compute_ragas_metrics(
        question=question,
        answer=answer,
        contexts=contexts,
        ground_truth=ground_truth,
    )
    logger.info(
        f"Evaluated: faith={metrics.get('faithfulness')}, " f"rel={metrics.get('answer_relevancy')}"
    )
    return {
        "question": question,
        "ground_truth": ground_truth,
        "answer": answer,
        "contexts": contexts,
        **metrics,
    }


# ---------------------------------------------------------------------------
# Task 11: 计算并持久化指标
# ---------------------------------------------------------------------------


async def _compute_and_persist_metrics(
    session: Session,
    run_id: int,
    results: list[dict],
) -> dict:
    """计算 RAGAS 聚合指标并持久化结果 (sync session 用 asyncio.to_thread 包装)。"""
    aggregated = aggregate_metrics(results)

    def _sync_persist():
        result_records = [
            EvaluationResult(
                run_id=run_id,
                question=r["question"],
                ground_truth=r["ground_truth"],
                generated_answer=r["answer"],
                contexts=r["contexts"],
                faithfulness=r.get("faithfulness"),
                answer_relevancy=r.get("answer_relevancy"),
                context_precision=r.get("context_precision"),
                context_recall=r.get("context_recall"),
                question_type=r.get("question_type"),
                difficulty=r.get("difficulty"),
                latency_ms=r.get("latency_ms"),
                token_count=r.get("token_count"),
            )
            for r in results
        ]
        session.add_all(result_records)

        run = session.get(EvaluationRun, run_id)
        if run:
            run.metrics = aggregated
            run.status = EvaluationStatus.COMPLETED
            run.completed_at = datetime.now(UTC)
        session.commit()

    await asyncio.to_thread(_sync_persist)
    logger.info(f"Evaluation run {run_id} completed: {aggregated}")
    return {"run_id": run_id, "status": "completed", "metrics": aggregated}
