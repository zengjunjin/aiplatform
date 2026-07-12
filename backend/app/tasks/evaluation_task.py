"""Celery task: run RAGAS evaluation asynchronously.

Uses synchronous SQLAlchemy session (psycopg2) for Celery worker.
"""
import logging
from datetime import datetime, timezone
from app.tasks.celery_app import celery_app
from app.db.sync_session import get_sync_session
from app.db.evaluation import EvaluationRun, EvaluationResult, EvaluationStatus
from app.db.document_chunk import DocumentChunk
from app.db.knowledge_base import KnowledgeBase

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=1,
                 name="app.tasks.evaluation_task.run_evaluation")
def run_evaluation_task(self, run_id: int):
    """Run evaluation asynchronously in Celery worker.

    Steps:
    1. Update status to running
    2. Generate test dataset
    3. Run RAG pipeline for each question
    4. Compute RAGAS metrics
    5. Persist results
    6. Update status to completed/failed
    """
    session = get_sync_session()
    try:
        # 1. Load run record
        run = session.get(EvaluationRun, run_id)
        if not run:
            logger.error(f"Evaluation run {run_id} not found")
            return {"error": "Run not found"}

        run.status = EvaluationStatus.RUNNING
        run.started_at = datetime.now(timezone.utc)
        session.commit()

        kb_id = run.knowledge_base_id

        # 2. Generate test dataset
        logger.info(f"Generating dataset for KB {kb_id}, num_questions={run.total_questions}")
        dataset = _generate_dataset_sync(session, kb_id, run.total_questions)

        if not dataset:
            run.status = EvaluationStatus.FAILED
            run.error_message = "No chunks available to generate test dataset"
            run.completed_at = datetime.now(timezone.utc)
            session.commit()
            return {"error": "No chunks available"}

        run.total_questions = len(dataset)
        session.commit()

        # 3. Run evaluation
        logger.info(f"Running evaluation for run {run_id} with {len(dataset)} questions")
        results = _run_evaluation_sync(kb_id, dataset)

        # 4. Save individual results
        for r in results:
            result = EvaluationResult(
                run_id=run_id,
                question=r["question"],
                ground_truth=r["ground_truth"],
                generated_answer=r["answer"],
                contexts=r["contexts"],
                faithfulness=r.get("faithfulness"),
                answer_relevancy=r.get("answer_relevancy"),
                context_precision=r.get("context_precision"),
                context_recall=r.get("context_recall"),
            )
            session.add(result)

        # 5. Aggregate metrics
        aggregated = _aggregate_metrics(results)
        run.metrics = aggregated
        run.status = EvaluationStatus.COMPLETED
        run.completed_at = datetime.now(timezone.utc)
        session.commit()

        logger.info(f"Evaluation run {run_id} completed: {aggregated}")
        return {"run_id": run_id, "status": "completed", "metrics": aggregated}

    except Exception as e:
        logger.exception(f"Evaluation run {run_id} failed")
        try:
            session.rollback()
        except Exception:
            pass
        try:
            # 重新获取 run 对象 (当前 session 可能处于无效状态)
            run = session.get(EvaluationRun, run_id)
            if run:
                run.status = EvaluationStatus.FAILED
                run.error_message = str(e)
                run.completed_at = datetime.now(timezone.utc)
                session.commit()
        except Exception as commit_err:
            logger.error(f"Failed to update evaluation run status: {commit_err}")
            try:
                session.rollback()
            except Exception:
                pass
        return {"error": str(e)}
    finally:
        session.close()


def _generate_dataset_sync(session, kb_id: int, num_questions: int) -> list[dict]:
    """Synchronously generate test dataset from KB chunks.

    使用 ThreadPoolExecutor 并发生成问题（每个 LLM 调用是 I/O 密集型）。
    """
    from sqlalchemy import func, select
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Get chunks
    result = session.execute(
        select(DocumentChunk)
        .where(DocumentChunk.kb_id == kb_id)
        .order_by(func.random())
        .limit(num_questions)
    )
    chunks = result.scalars().all()

    if not chunks:
        return []

    # 并发生成问题（max_workers=8 限制并发度）
    target_chunks = chunks[:num_questions]
    dataset = [None] * len(target_chunks)  # 预分配保持顺序

    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_idx = {
            executor.submit(_generate_question_sync, chunk.content): idx
            for idx, chunk in enumerate(target_chunks)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            question = future.result()
            if question:
                dataset[idx] = {
                    "question": question,
                    "ground_truth": target_chunks[idx].content,
                    "contexts": [target_chunks[idx].content],
                }

    # 过滤掉 None（生成失败的）
    return [d for d in dataset if d is not None]


def _generate_question_sync(chunk_content: str) -> str | None:
    """Generate a question from chunk content using sync LLM call."""
    import requests
    from app.config import settings

    prompt = (
        "你是一个问答数据集生成助手。请根据以下文本内容，生成一个可以用该文本回答的问题。\n\n"
        "规则：\n"
        "1. 问题应该具体、明确，答案可以直接从文本中找到\n"
        "2. 只返回问题本身，不要添加任何其他内容\n"
        "3. 问题应该用中文\n\n"
        f"文本内容：\n{chunk_content[:1500]}\n\n"
        "问题："
    )

    try:
        resp = requests.post(
            f"{settings.OLLAMA_HOST}/api/generate",
            json={
                "model": settings.LLM_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 200},
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        question = data.get("response", "").strip()

        for prefix in ["问题：", "Question:", "Q:", "问："]:
            if question.startswith(prefix):
                question = question[len(prefix):].strip()

        if len(question) < 5:
            return None

        return question
    except Exception as e:
        logger.warning(f"Failed to generate question: {e}")
        return None


def _run_evaluation_sync(kb_id: int, dataset: list[dict]) -> list[dict]:
    """Run RAG pipeline and compute metrics for each question."""
    import asyncio

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(_run_evaluation_async(kb_id, dataset))
    finally:
        loop.close()


async def _run_evaluation_async(kb_id: int, dataset: list[dict]) -> list[dict]:
    """Async evaluation runner."""
    from app.services.evaluation_service import get_rag_answer
    from app.core.evaluation import _compute_ragas_metrics

    results = []
    for idx, item in enumerate(dataset):
        question = item["question"]
        ground_truth = item["ground_truth"]

        try:
            answer, contexts = await get_rag_answer(question, kb_id)
            metrics = await _compute_ragas_metrics(
                question=question,
                answer=answer,
                contexts=contexts,
                ground_truth=ground_truth,
            )
            results.append({
                "question": question,
                "ground_truth": ground_truth,
                "answer": answer,
                "contexts": contexts,
                **metrics,
            })
            logger.info(f"Evaluated {idx + 1}/{len(dataset)}: "
                        f"faith={metrics.get('faithfulness')}, "
                        f"rel={metrics.get('answer_relevancy')}")
        except Exception as e:
            logger.error(f"Failed question {idx + 1}: {e}")
            results.append({
                "question": question,
                "ground_truth": ground_truth,
                "answer": f"ERROR: {e}",
                "contexts": item.get("contexts", []),
            })

    return results


def _aggregate_metrics(results: list[dict]) -> dict[str, float]:
    """Aggregate individual metrics into averages."""
    keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    aggregated = {}
    for key in keys:
        values = [r.get(key) for r in results if r.get(key) is not None]
        if values:
            aggregated[key] = round(sum(values) / len(values), 4)
        else:
            aggregated[key] = 0.0
    return aggregated