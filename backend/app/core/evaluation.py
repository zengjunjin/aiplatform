"""RAGAS evaluation engine.

Encapsulates RAGAS evaluate() call, loads evaluation datasets,
runs RAG pipeline for each question, computes four metrics,
and persists results to the database.
"""
import asyncio

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.evaluation import EvaluationResult, EvaluationRun, EvaluationStatus
from app.services.evaluation_service import get_rag_answer


# Task 1.7: 问题生成公共常量与函数（消除 evaluation_task / evaluation_service 重复）
_QUESTION_PREFIXES = ["问题：", "Question:", "Q:", "问："]


def build_question_prompt(content: str) -> str:
    """构建从文本生成问题的 LLM prompt（公共函数，消除复制粘贴）。"""
    return (
        "你是一个问答数据集生成助手。请根据以下文本内容，生成一个可以用该文本回答的问题。\n\n"
        "规则：\n"
        "1. 问题应该具体、明确，答案可以直接从文本中找到\n"
        "2. 只返回问题本身，不要添加任何其他内容\n"
        "3. 问题应该用中文\n\n"
        f"文本内容：\n{content[:1500]}\n\n"
        "问题："
    )


def sanitize_question(q: str) -> str | None:
    """清理 LLM 生成的问题：去除常见前缀，过短返回 None。"""
    question = (q or "").strip()
    for prefix in _QUESTION_PREFIXES:
        if question.startswith(prefix):
            question = question[len(prefix):].strip()
    if len(question) < 5:
        return None
    return question


async def _eval_single_question(
    item: dict,
    kb_id: int,
    semaphore: asyncio.Semaphore,
) -> dict:
    """评估单个问题：RAG 检索 + metrics 计算（不含 db 操作）。

    单题失败隔离：异常被捕获，返回 success=False 的结果，不阻断整体。
    返回 dict:
      - question / ground_truth / answer / contexts
      - metrics: dict (成功时) / {} (失败时)
      - success: bool
    """
    question = item["question"]
    ground_truth = item["ground_truth"]
    reference_contexts = item.get("contexts", [])

    async with semaphore:
        try:
            answer, retrieved_contexts = await get_rag_answer(question, kb_id)
            metrics = await _compute_ragas_metrics(
                question=question,
                answer=answer,
                contexts=retrieved_contexts,
                ground_truth=ground_truth,
            )
            return {
                "question": question,
                "ground_truth": ground_truth,
                "answer": answer,
                "contexts": retrieved_contexts,
                "metrics": metrics,
                "success": True,
            }
        except Exception as e:
            logger.error(f"Failed to evaluate question '{question[:50]}': {e}")
            return {
                "question": question,
                "ground_truth": ground_truth,
                "answer": f"ERROR: {str(e)}",
                "contexts": reference_contexts,
                "metrics": {},
                "success": False,
            }


async def run_evaluation(
    run_id: int,
    dataset: list[dict],
    kb_id: int,
    db: AsyncSession,
) -> dict:
    """Execute the full RAGAS evaluation pipeline.

    Task 15: 改用 asyncio.gather + Semaphore(8) 并发评估，单题失败隔离。

    注意（Task 38）：此函数目前仅被 tests/test_evaluation_concurrency.py 调用，
    生产环境的评估流程走 app.tasks.evaluation_task._run_evaluation_async
    （使用同步 session + Celery worker）。保留此函数用于并发评估逻辑的
    单元测试覆盖，勿在生产代码中直接调用。

    Args:
        run_id: The EvaluationRun ID
        dataset: List of {question, ground_truth, contexts}
        kb_id: The knowledge base ID
        db: Async database session

    Returns:
        dict with aggregated metrics: {faithfulness, answer_relevancy,
        context_precision, context_recall}
    """
    semaphore = asyncio.Semaphore(settings.EVAL_CONCURRENCY)

    # 并发评估所有问题（RAG + metrics 计算），单题失败隔离
    eval_results = await asyncio.gather(
        *[_eval_single_question(item, kb_id, semaphore) for item in dataset]
    )

    # 串行写入 DB（db 操作不能并发），保留增量提交
    successful_metrics: list[dict] = []
    for idx, r in enumerate(eval_results):
        metrics = r["metrics"]
        result = EvaluationResult(
            run_id=run_id,
            question=r["question"],
            ground_truth=r["ground_truth"],
            generated_answer=r["answer"],
            contexts=r["contexts"],
            faithfulness=metrics.get("faithfulness"),
            answer_relevancy=metrics.get("answer_relevancy"),
            context_precision=metrics.get("context_precision"),
            context_recall=metrics.get("context_recall"),
        )
        db.add(result)
        if r["success"]:
            successful_metrics.append(metrics)

        logger.info(f"Evaluated question {idx + 1}/{len(dataset)}: "
                    f"success={r['success']}, "
                    f"faithfulness={metrics.get('faithfulness')}, "
                    f"answer_relevancy={metrics.get('answer_relevancy')}")

        # 增量提交: 每 EVAL_INCREMENTAL_COMMIT_BATCH 个问题提交一次, 避免全部结果丢失
        if (idx + 1) % settings.EVAL_INCREMENTAL_COMMIT_BATCH == 0:
            await db.commit()

    # 提交剩余结果
    await db.commit()

    # Aggregate metrics（仅成功题目的 metrics 参与聚合）
    aggregated = aggregate_metrics(successful_metrics)

    # Update the run with aggregated metrics
    run_result = await db.execute(select(EvaluationRun).where(EvaluationRun.id == run_id))
    run = run_result.scalar_one_or_none()
    if run:
        run.metrics = aggregated
        run.status = EvaluationStatus.COMPLETED
        try:
            await db.commit()
        except Exception as e:
            logger.error(f"Failed to persist aggregated metrics for run {run_id}: {e}")
            await db.rollback()
            # 即使聚合指标保存失败, 逐题结果已保存, 不丢失数据

    return aggregated


async def _compute_ragas_metrics(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str,
) -> dict[str, float | None]:
    """Compute RAGAS metrics for a single question-answer pair.

    Uses the ragas library if available, otherwise falls back to
    heuristic-based scoring.
    """
    try:
        from datasets import Dataset
        from ragas import evaluate
        from ragas.metrics import (
            answer_relevancy,
            context_precision,
            context_recall,
            faithfulness,
        )

        # Build a single-row dataset
        ds = Dataset.from_dict({
            "question": [question],
            "answer": [answer],
            "contexts": [contexts],
            "ground_truth": [ground_truth],
        })

        result = evaluate(
            ds,
            metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
        )

        metrics = {}
        for key in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
            val = result.get(key)
            if val is not None:
                try:
                    metrics[key] = float(val[0]) if hasattr(val, '__getitem__') else float(val)
                except (TypeError, ValueError, IndexError):
                    metrics[key] = None

        return metrics

    except ImportError:
        logger.warning("ragas library not available, using heuristic fallback")
        return _heuristic_metrics(question, answer, contexts, ground_truth)
    except Exception as e:
        logger.warning(f"RAGAS evaluation failed: {e}, using heuristic fallback")
        return _heuristic_metrics(question, answer, contexts, ground_truth)


def _heuristic_metrics(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str,
) -> dict[str, float | None]:
    """Heuristic-based metric computation when RAGAS is unavailable.

    These are approximate scores based on simple text overlap heuristics.
    """
    import re

    def _word_overlap(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        words_a = set(re.findall(r'\w+', a.lower()))
        words_b = set(re.findall(r'\w+', b.lower()))
        if not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_b)

    combined_contexts = " ".join(contexts) if contexts else ""

    # Faithfulness: how much of the answer is supported by contexts
    faith = _word_overlap(answer, combined_contexts) if combined_contexts else None

    # Answer relevancy: how relevant is the answer to the question
    rel = _word_overlap(answer, question) if question else None

    # Context precision: how much of the retrieved contexts is relevant
    cp = _word_overlap(combined_contexts, ground_truth) if combined_contexts and ground_truth else None

    # Context recall: how much of ground_truth is covered by contexts
    cr = _word_overlap(ground_truth, combined_contexts) if combined_contexts and ground_truth else None

    return {
        "faithfulness": round(faith, 4) if faith is not None else None,
        "answer_relevancy": round(rel, 4) if rel is not None else None,
        "context_precision": round(cp, 4) if cp is not None else None,
        "context_recall": round(cr, 4) if cr is not None else None,
    }


def aggregate_metrics(results: list[dict]) -> dict[str, float]:
    """Aggregate individual metrics into averages.

    Shared by both the async :func:`run_evaluation` pipeline and the
    synchronous Celery task :mod:`app.tasks.evaluation_task`.
    """
    keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    aggregated = {}

    for key in keys:
        values = [r.get(key) for r in results if r.get(key) is not None]
        if values:
            aggregated[key] = round(sum(values) / len(values), 4)
        else:
            aggregated[key] = 0.0

    return aggregated
