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
    # 修复（v0.4.0）：添加重试退避策略
    retry_backoff=60,
    retry_backoff_max=300,
    retry_jitter=True,
)
def run_evaluation_task(self, run_id: int):
    """Run evaluation asynchronously in Celery worker.

    Sync Celery entry point — creates an event loop and delegates to
    the async orchestrator ``_run_evaluation_async``.

    修复（v0.4.0）：失败时调用 self.retry() 触发自动重试。
    之前装饰器声明 max_retries=2 但函数体从未调用 self.retry()，配置形同虚设。
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run_evaluation_async(run_id))
    except Exception as exc:
        # 修复（v0.4.0）：瞬时故障自动重试，重试次数用尽后标记 FAILED
        if self.request.retries < settings.TASK_MAX_RETRIES_EVALUATION:
            logger.warning(
                f"Evaluation run {run_id} failed (attempt {self.request.retries + 1}), "
                f"retrying in 60s: {exc}"
            )
            raise self.retry(exc=exc)
        # 重试次数用尽，标记 FAILED
        loop.run_until_complete(
            _mark_run_failed(run_id, f"评估失败（重试 {self.request.retries} 次后仍失败）: {exc}")
        )
        raise
    finally:
        loop.close()


async def _mark_run_failed(run_id: int, error: str):
    """重试次数用尽时标记 run 为 FAILED。"""
    session = get_sync_session()
    try:
        await _update_run_status(session, run_id, EvaluationStatus.FAILED, error)
    except Exception as e:
        logger.error(f"Failed to mark run {run_id} as FAILED: {e}")
    finally:
        session.close()


async def _run_evaluation_async(run_id: int) -> dict:
    """主函数 (Task 11: ≤ 50 行) — 编排子函数完成评估流程。

    Steps:
    1. Task 5: 幂等性抢占 run
    2. Task 9: 准备数据集 (sync session wrapped in asyncio.to_thread)
    3. Task 8: 并发执行评估
    4. 计算并持久化指标

    修复（v0.4.0）：except 中根据是否还有重试次数决定 raise retry 还是标记 FAILED。
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
    except Exception as exc:
        logger.exception(f"Evaluation run {run_id} failed")
        if session.is_active:
            try:
                session.rollback()
            except Exception as re:
                logger.debug(f"Evaluation first rollback failed: {re}")
        # 修复（v0.4.0）：瞬时故障自动重试（max_retries 由装饰器配置）
        # 通过 raise 让 Celery 捕获并按 retry_backoff 策略重试
        raise
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

    设计原则（与 evaluation_service.generate_test_dataset 一致）：
    - ground_truth 由 LLM 仅依据 question + kb_description 独立生成，不看 chunk 内容
    - contexts 由 retriever 对 question 重新检索得到，与 ground_truth 不同源
    - 避免 RAGAS 指标循环验证、虚高
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

    # 获取 KB 描述用于独立生成 ground_truth
    def _sync_fetch_kb():
        from app.db.knowledge_base import KnowledgeBase

        return session.get(KnowledgeBase, run.knowledge_base_id)

    kb = await asyncio.to_thread(_sync_fetch_kb)
    kb_description = (kb.description or kb.name) if kb else ""

    return await _generate_dataset_async(chunks, kb_description, run.knowledge_base_id)


async def _generate_dataset_async(
    chunks: list, kb_description: str, kb_id: int
) -> list[dict]:
    """Async dataset generation: 并发用 LLM Provider 生成问题。

    Task 14.3: 移除 requests.post 同步调用，改用 OllamaLLMProvider.chat() 异步调用。
    Task 8 风格: 用 asyncio.gather + Semaphore(8) 限制并发度。
    Task 1.5: 数据集条目包含 question_type/difficulty。

    修复（v0.4.0）：ground_truth 与 contexts 不再同源。
    - ground_truth：LLM 仅依据 question + kb_description 独立生成
    - contexts：retriever 对 question 重新检索得到
    """
    from app.models.ollama_provider import OllamaLLMProvider
    from app.rag.retriever import retriever

    target_chunks = chunks
    # Task 14.3: 创建独立 OllamaLLMProvider 实例（避免 ModelFactory 单例的 event loop 绑定问题）
    llm = OllamaLLMProvider()
    semaphore = asyncio.Semaphore(settings.EVAL_CONCURRENCY)

    async def _gen_with_sem(idx: int, chunk_content: str) -> dict | None:
        async with semaphore:
            question_data = await _generate_question_async(chunk_content, llm)
            if not question_data:
                return None
            question = question_data["question"]
            # 独立生成 ground_truth：LLM 不看 chunk 内容，避免与 contexts 同源
            ground_truth = await _generate_ground_truth_async(llm, question, kb_description)
            # contexts 由 retriever 对 question 重新检索得到
            try:
                retrieved = await retriever.retrieve(
                    question, kb_id, top_k=settings.RETRIEVAL_TOP_K
                )
                contexts = [c.get("content", "") for c in retrieved]
            except Exception as e:
                logger.warning(f"Failed to retrieve contexts for question {idx}: {e}")
                contexts = []
            return {
                "question": question,
                "ground_truth": ground_truth,
                "contexts": contexts,
                "question_type": question_data["question_type"],
                "difficulty": question_data["difficulty"],
            }

    try:
        tasks = [_gen_with_sem(idx, chunk.content) for idx, chunk in enumerate(target_chunks)]
        dataset = await asyncio.gather(*tasks, return_exceptions=False)
    finally:
        await llm.close()

    # 过滤掉 None（生成失败的）
    return [d for d in dataset if d is not None]


async def _generate_ground_truth_async(
    llm, question: str, kb_description: str
) -> str:
    """由 LLM 仅依据 question 和 kb_description 独立生成参考答案。

    LLM 不看 chunk 内容，避免与 contexts 同源导致 RAGAS 指标循环验证、虚高。
    生成失败时 raise，不 fallback 到 chunk.content。
    """
    prompt = (
        "你是一个领域专家。请针对以下问题给出一个准确、简洁的参考答案。\n\n"
        f"知识库描述：{kb_description}\n"
        f"问题：{question}\n"
        "参考答案："
    )
    response = await llm.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    if not response or not response.strip():
        raise RuntimeError("LLM returned empty ground_truth")
    return response.strip()


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
