"""Evaluation service: generate test datasets and run RAGAS evaluation."""

import asyncio

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import NotFoundError
from app.db.document_chunk import DocumentChunk
from app.db.evaluation import EvaluationResult, EvaluationRun, EvaluationStatus
from app.db.knowledge_base import KnowledgeBase
from app.rag.retriever import retriever
from app.services import kb_service


async def generate_test_dataset(
    kb_id: int,
    db: AsyncSession,
    num_questions: int = 50,
) -> list[dict]:
    """Generate a test dataset from knowledge base chunks.

    Randomly samples chunks from the KB, then uses the LLM to generate
    a question for each chunk. Returns a list of {question, ground_truth, contexts}.
    """
    # Verify KB exists
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("Knowledge base not found")

    # Get all chunks for this KB
    chunk_result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.kb_id == kb_id)
        .order_by(func.random())
        .limit(num_questions)
    )
    chunks = chunk_result.scalars().all()

    if not chunks:
        logger.warning(f"No chunks found for KB {kb_id}")
        return []

    # Sample up to num_questions chunks
    sample_chunks = chunks[:num_questions]

    # KB 描述用于独立生成 ground_truth（LLM 不看 chunk 内容，避免与 contexts 同源
    # 导致 RAGAS 指标循环验证、虚高）
    kb_description = kb.description or kb.name

    # 并发生成问题（Semaphore 限制并发度，避免打爆 LLM 服务）
    sem = asyncio.Semaphore(settings.EVAL_CONCURRENCY)
    # 延迟 import 避免循环依赖：evaluation_service ↔ ModelFactory
    from app.models.factory import ModelFactory

    shared_llm = ModelFactory.create_llm()

    async def _gen(chunk):
        async with sem:
            # 1. 由 chunk 生成问题（失败返回 None，跳过该条）
            question_data = await generate_question_from_chunk(chunk.content, shared_llm)
            if not question_data:
                return None
            question = question_data["question"]
            # 2. 独立生成 ground_truth：LLM 仅依据 question + kb_description 生成参考答案，
            #    不看 chunk 内容；生成失败时 raise，不 fallback 到 chunk.content
            ground_truth = await generate_ground_truth(shared_llm, question, kb_description)
            # 3. contexts 由 retriever 对 question 重新检索得到，与 ground_truth 不同源
            retrieved = await retriever.retrieve(question, kb_id, top_k=settings.RETRIEVAL_TOP_K)
            contexts = [c.get("content", "") for c in retrieved]
            return {
                "question": question,
                "ground_truth": ground_truth,
                "contexts": contexts,
                "question_type": question_data["question_type"],
                "difficulty": question_data["difficulty"],
            }

    results = await asyncio.gather(*[_gen(c) for c in sample_chunks], return_exceptions=True)

    dataset = []
    for item in results:
        if isinstance(item, Exception):
            # ground_truth 生成或检索失败：记录并跳过，不污染数据集
            logger.warning(f"Failed to generate dataset entry: {item}")
            continue
        if item is None:
            # 问题生成失败：跳过
            continue
        dataset.append(item)

    logger.info(f"Generated {len(dataset)} questions for KB {kb_id}")
    return dataset


async def generate_question_from_chunk(chunk_content: str, llm) -> dict | None:
    """Use LLM to generate a question that can be answered by the chunk.

    Task 1.5: 返回 dict 包含 question/question_type/difficulty。

    P1-6 修复：函数级去重，原 task 内的 `_generate_question_async` 已删除，
    Celery 任务直接调用此公共函数；llm 由调用方传入（task 可注入独立实例
    避免 ModelFactory 单例的 event loop 绑定问题）。
    温度统一为 0.3（与 service 一致，消除原 task 的 0.7 漂移）。
    """
    try:
        from app.core.evaluation import build_question_prompt, parse_question_response

        prompt = build_question_prompt(chunk_content)

        # Use non-streaming chat (BaseLLMProvider 标准接口，generate 方法不存在)
        response = await llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        return parse_question_response(response)
    except Exception as e:
        logger.warning(f"Failed to generate question from chunk: {e}")
        return None


async def generate_ground_truth(llm, question: str, kb_description: str) -> str:
    """由 LLM 仅依据 question 和 kb_description 独立生成参考答案。

    LLM 不看 chunk 内容，避免与 contexts 同源导致 RAGAS 指标循环验证、虚高。
    生成失败时 raise，不 fallback 到 chunk.content。

    P1-6 修复：公共函数，原 task 内 `_generate_ground_truth_async` 逐字重复已删除。
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


async def get_rag_answer(
    query: str, kb_id: int, llm=None
) -> tuple[str, list[str]]:
    """Run the RAG pipeline to get an answer and retrieved contexts.

    修复（v0.4.0）：移除宽泛 except Exception，让异常向上抛出。
    调用方 _run_evaluations 用 asyncio.gather(return_exceptions=True) 捕获异常做失败隔离。
    之前吞异常导致失败题目被记为"成功评估"，错误答案污染聚合结果。

    T8（P3）：llm 参数允许调用方传入已有实例，避免每次评估都创建新 LLM 连接。
    """
    from app.rag.prompt_builder import build_rag_prompt
    from app.rag.retriever import retriever

    # Retrieve relevant chunks
    # Task 9: 使用 settings.RETRIEVAL_TOP_K 保持评估与生产一致，避免评估结果系统性偏低
    chunks = await retriever.retrieve(query, kb_id, top_k=settings.RETRIEVAL_TOP_K)
    contexts = [c.get("content", "") for c in chunks]

    if not contexts:
        return "无法获取相关内容来回答此问题。", []

    # Build prompt
    prompt = build_rag_prompt(query, chunks)

    # Generate answer — 复用传入的 LLM 实例，或按需创建
    if llm is None:
        from app.models.factory import ModelFactory
        llm = ModelFactory.create_llm()
    answer = await llm.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    answer = answer or ""

    return answer, contexts


async def trigger_evaluation(
    kb_id: int,
    num_questions: int,
    user_id: int,
    db: AsyncSession,
    trigger_source: str = "manual",
) -> tuple[EvaluationRun, object]:
    """触发新的评估运行 (admin only)。

    业务流程：
    1. 通过 kb_service.get_kb_for_read 校验 KB 读权限
    2. 创建 EvaluationRun (PENDING)
    3. 派发 Celery 异步任务

    Args:
        trigger_source: 触发来源，'manual'（手动/API）或 'scheduled'（定时任务）。

    Returns:
        (run, task) 元组，task 为 Celery AsyncResult。
    """
    # 1. KB 读权限校验
    await kb_service.get_kb_for_read(kb_id, user_id, db)

    # 2. 创建评估运行记录
    # 记录评估时使用的检索/生成参数快照，便于横向对比不同参数下的效果。
    # retriever_alpha 当前无对应 settings 配置项，保留 None 以待后续配置化。
    try:
        from app.rag.prompt_builder import get_prompt_version

        prompt_version = get_prompt_version()
    except Exception as e:
        logger.debug(f"Failed to get prompt_version, fallback to None: {e}")
        prompt_version = None
    run = EvaluationRun(
        knowledge_base_id=kb_id,
        status=EvaluationStatus.PENDING,
        total_questions=num_questions,
        created_by=user_id,
        prompt_version=prompt_version,
        retriever_alpha=None,
        retriever_top_k=settings.RETRIEVAL_TOP_K,
        rerank_top_k=settings.RERANK_TOP_K,
        trigger_source=trigger_source,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    # 3. 派发 Celery 异步任务
    from app.tasks.evaluation_task import run_evaluation_task

    try:
        task = run_evaluation_task.delay(run.id)
    except Exception:
        # Celery 派发失败：将 run 标记为 FAILED 并提交，避免孤儿 PENDING 记录。
        # 标记失败的提交若自身出错则回滚，但始终重新抛出原始异常以保持异常流程不变
        # （API 层仍走 generic_exception_handler 返回 500）。
        logger.exception(f"Celery evaluation task dispatch failed for run_id={run.id}")
        run.status = EvaluationStatus.FAILED
        try:
            await db.commit()
        except Exception as ce:
            logger.debug(f"Failed to commit run status=FAILED after dispatch failure: {ce}")
            await db.rollback()
        raise
    logger.info(
        f"Evaluation run {run.id} dispatched: task_id={task.id} "
        f"kb={kb_id} questions={num_questions}"
    )
    return run, task


async def list_evaluation_runs(
    db: AsyncSession,
    kb_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EvaluationRun], int]:
    """列出评估运行历史 (admin only)。

    支持按 kb_id 过滤，按 created_at 倒序分页。
    """
    query = select(EvaluationRun)
    count_query = select(func.count()).select_from(EvaluationRun)

    if kb_id is not None:
        query = query.where(EvaluationRun.knowledge_base_id == kb_id)
        count_query = count_query.where(EvaluationRun.knowledge_base_id == kb_id)

    count_result = await db.execute(count_query)
    total = count_result.scalar_one()

    result = await db.execute(
        query.order_by(EvaluationRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    runs = result.scalars().all()
    return runs, total


async def get_evaluation_run(run_id: int, user_id: int, db: AsyncSession) -> EvaluationRun:
    """获取单个评估运行详情 (admin only)。

    run 不存在抛 NotFoundError。
    """
    result = await db.execute(select(EvaluationRun).where(EvaluationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Evaluation run not found")
    return run


async def delete_evaluation_run(run_id: int, user_id: int, db: AsyncSession) -> None:
    """删除评估运行及其结果 (admin only)。

    业务流程：
    1. 查找 run，不存在抛 NotFoundError
    2. 通过 kb_service.get_kb_for_admin 校验 KB admin 权限
    3. 显式删除关联的 EvaluationResult（CASCADE 也会处理，但显式更安全）
    4. 删除 run 并提交事务
    """
    result = await db.execute(select(EvaluationRun).where(EvaluationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Evaluation run not found")

    # KB admin 权限校验
    await kb_service.get_kb_for_admin(run.knowledge_base_id, user_id, db)

    # 显式删除关联结果（CASCADE 也会处理，但显式更安全）
    from sqlalchemy import delete

    await db.execute(delete(EvaluationResult).where(EvaluationResult.run_id == run_id))
    await db.delete(run)
    await db.commit()


async def get_evaluation_results(
    run_id: int,
    user_id: int,
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EvaluationResult], int]:
    """获取评估运行的逐题结果 (admin only)。

    run 不存在抛 NotFoundError。结果按 id 升序分页。
    """
    # 确认 run 存在
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
    return results, total
