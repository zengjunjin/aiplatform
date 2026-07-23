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

    # 并发生成问题（Semaphore 限制并发度，避免打爆 LLM 服务）
    sem = asyncio.Semaphore(settings.EVAL_CONCURRENCY)

    async def _gen(chunk):
        async with sem:
            return await _generate_question_from_chunk(chunk.content)

    questions = await asyncio.gather(*[_gen(c) for c in sample_chunks], return_exceptions=True)

    dataset = []
    for chunk, question in zip(sample_chunks, questions):
        if isinstance(question, Exception) or not question:
            continue
        dataset.append({
            "question": question,
            "ground_truth": chunk.content,
            "contexts": [chunk.content],
        })

    logger.info(f"Generated {len(dataset)} questions for KB {kb_id}")
    return dataset


async def _generate_question_from_chunk(chunk_content: str) -> str | None:
    """Use LLM to generate a question that can be answered by the chunk."""
    try:
        from app.core.evaluation import build_question_prompt, sanitize_question
        from app.models.factory import ModelFactory
        llm = ModelFactory.create_llm()

        prompt = build_question_prompt(chunk_content)

        # Use non-streaming chat (BaseLLMProvider 标准接口，generate 方法不存在)
        response = await llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
        )

        return sanitize_question(response)
    except Exception as e:
        logger.warning(f"Failed to generate question from chunk: {e}")
        return None


async def get_rag_answer(query: str, kb_id: int) -> tuple[str, list[str]]:
    """Run the RAG pipeline to get an answer and retrieved contexts."""
    try:
        from app.models.factory import ModelFactory
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

        # Generate answer
        llm = ModelFactory.create_llm()
        answer = await llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        answer = answer or ""

        return answer, contexts

    except Exception as e:
        # 记录原始异常堆栈（脱敏返回值前保留排查信息）
        logger.exception(f"RAG pipeline error for query '{query[:50]}...'")
        return "评估失败，请稍后重试", []


async def trigger_evaluation(
    kb_id: int,
    num_questions: int,
    user_id: int,
    db: AsyncSession,
) -> tuple[EvaluationRun, object]:
    """触发新的评估运行 (admin only)。

    业务流程：
    1. 通过 kb_service.get_kb_for_read 校验 KB 读权限
    2. 创建 EvaluationRun (PENDING)
    3. 派发 Celery 异步任务

    Returns:
        (run, task) 元组，task 为 Celery AsyncResult。
    """
    # 1. KB 读权限校验
    await kb_service.get_kb_for_read(kb_id, user_id, db)

    # 2. 创建评估运行记录
    run = EvaluationRun(
        knowledge_base_id=kb_id,
        status=EvaluationStatus.PENDING,
        total_questions=num_questions,
        created_by=user_id,
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
        run.status = EvaluationStatus.FAILED
        try:
            await db.commit()
        except Exception:
            await db.rollback()
        raise
    logger.info(
        f"Evaluation run {run.id} dispatched: task_id={task.id} "
        f"kb={kb_id} questions={num_questions}"
    )
    return run, task


async def list_evaluation_runs(
    user_id: int,
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
        query
        .order_by(EvaluationRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    runs = result.scalars().all()
    return runs, total


async def get_evaluation_run(
    run_id: int, user_id: int, db: AsyncSession
) -> EvaluationRun:
    """获取单个评估运行详情 (admin only)。

    run 不存在抛 NotFoundError。
    """
    result = await db.execute(select(EvaluationRun).where(EvaluationRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise NotFoundError("Evaluation run not found")
    return run


async def delete_evaluation_run(
    run_id: int, user_id: int, db: AsyncSession
) -> None:
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
        select(func.count())
        .select_from(EvaluationResult)
        .where(EvaluationResult.run_id == run_id)
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
