"""RAGAS evaluation engine.

Encapsulates RAGAS evaluate() call, loads evaluation datasets,
runs RAG pipeline for each question, computes four metrics,
and persists results to the database.
"""
import asyncio
from typing import Any
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.evaluation import EvaluationRun, EvaluationResult, EvaluationStatus
from app.services.evaluation_service import get_rag_answer
from app.core.exceptions import NotFoundError


async def run_evaluation(
    run_id: int,
    dataset: list[dict],
    kb_id: int,
    db: AsyncSession,
) -> dict:
    """Execute the full RAGAS evaluation pipeline.

    Args:
        run_id: The EvaluationRun ID
        dataset: List of {question, ground_truth, contexts}
        kb_id: The knowledge base ID
        db: Async database session

    Returns:
        dict with aggregated metrics: {faithfulness, answer_relevancy,
        context_precision, context_recall}
    """
    results = []

    for idx, item in enumerate(dataset):
        question = item["question"]
        ground_truth = item["ground_truth"]
        reference_contexts = item.get("contexts", [])

        try:
            # Run RAG pipeline to get answer and contexts
            answer, retrieved_contexts = await get_rag_answer(question, kb_id)

            # Compute individual metrics using RAGAS
            metrics = await _compute_ragas_metrics(
                question=question,
                answer=answer,
                contexts=retrieved_contexts,
                ground_truth=ground_truth,
            )

            # Save individual result
            result = EvaluationResult(
                run_id=run_id,
                question=question,
                ground_truth=ground_truth,
                generated_answer=answer,
                contexts=retrieved_contexts,
                faithfulness=metrics.get("faithfulness"),
                answer_relevancy=metrics.get("answer_relevancy"),
                context_precision=metrics.get("context_precision"),
                context_recall=metrics.get("context_recall"),
            )
            db.add(result)
            results.append(metrics)

            logger.info(f"Evaluated question {idx + 1}/{len(dataset)}: "
                        f"faithfulness={metrics.get('faithfulness')}, "
                        f"answer_relevancy={metrics.get('answer_relevancy')}")

        except Exception as e:
            logger.error(f"Failed to evaluate question {idx + 1}: {e}")
            # Save failed result with null metrics
            result = EvaluationResult(
                run_id=run_id,
                question=question,
                ground_truth=ground_truth,
                generated_answer=f"ERROR: {str(e)}",
                contexts=reference_contexts,
            )
            db.add(result)

        # 增量提交: 每 10 个问题提交一次, 避免全部结果丢失
        if (idx + 1) % 10 == 0:
            await db.commit()

    # 提交剩余结果
    await db.commit()

    # Aggregate metrics
    aggregated = _aggregate_metrics(results)

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
        from ragas import evaluate
        from ragas.metrics import (
            faithfulness,
            answer_relevancy,
            context_precision,
            context_recall,
        )
        from datasets import Dataset

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