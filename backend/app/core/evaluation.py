"""RAGAS evaluation engine.

Encapsulates RAGAS evaluate() call, loads evaluation datasets,
runs RAG pipeline for each question, computes four metrics,
and persists results to the database.
"""

import asyncio
import json
import re
import statistics
from typing import cast

from loguru import logger
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.evaluation import EvaluationResult, EvaluationRun, EvaluationStatus
from app.services.evaluation_service import get_rag_answer

# Task 1.7: 问题生成公共常量与函数（消除 evaluation_task / evaluation_service 重复）
_QUESTION_PREFIXES = ["问题：", "Question:", "Q:", "问："]


def build_question_prompt(content: str) -> str:
    """构建从文本生成问题的 LLM prompt（公共函数，消除复制粘贴）。

    Task 1.5: prompt 改为要求 LLM 返回 JSON，同时打标 question_type 和 difficulty。
    """
    return (
        "你是一个问答数据集生成助手。请根据以下文本内容，生成一个可以用该文本回答的问题。\n\n"
        "请返回 JSON 格式，包含以下字段：\n"
        '- "question": 问题内容（中文，具体明确，答案可直接从文本中找到）\n'
        '- "question_type": 问题类型，可选值 "factual"（事实型）/"reasoning"（推理型）/"multi_hop"（多跳型）\n'
        '- "difficulty": 难度，可选值 "easy"/"medium"/"hard"\n\n'
        "规则：\n"
        "1. 只返回 JSON，不要添加任何其他内容\n"
        "2. 问题应该用中文\n\n"
        f"文本内容：\n{content[:1500]}\n\n"
        "JSON："
    )


def sanitize_question(q: str) -> str | None:
    """清理 LLM 生成的问题：去除常见前缀，过短返回 None。"""
    question = (q or "").strip()
    for prefix in _QUESTION_PREFIXES:
        if question.startswith(prefix):
            question = question[len(prefix) :].strip()
    if len(question) < 5:
        return None
    return question


def parse_question_response(response: str) -> dict | None:
    """解析 LLM 返回的 JSON，提取 question/question_type/difficulty。

    Task 1.5: 配合 build_question_prompt 的 JSON 输出格式。

    JSON 解析失败时 fallback 到 question_type="factual", difficulty="medium"。
    返回 dict: {"question": str, "question_type": str, "difficulty": str}，
    问题为空或过短返回 None。
    """
    if not response or not response.strip():
        return None

    text = response.strip()
    # 去除可能的 markdown 代码块包裹
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        data = json.loads(text)
        question = sanitize_question(data.get("question") or "")
        if question is None:
            return None

        question_type = data.get("question_type", "factual")
        difficulty = data.get("difficulty", "medium")
        # 校验枚举值，非法值 fallback
        if question_type not in ("factual", "reasoning", "multi_hop"):
            question_type = "factual"
        if difficulty not in ("easy", "medium", "hard"):
            difficulty = "medium"

        return {
            "question": question,
            "question_type": question_type,
            "difficulty": difficulty,
        }
    except (json.JSONDecodeError, ValueError, TypeError):
        # JSON 解析失败：尝试用旧方式提取问题，fallback 标签
        question = sanitize_question(response)
        if question is None:
            return None
        return {
            "question": question,
            "question_type": "factual",
            "difficulty": "medium",
        }


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

        logger.info(
            f"Evaluated question {idx + 1}/{len(dataset)}: "
            f"success={r['success']}, "
            f"faithfulness={metrics.get('faithfulness')}, "
            f"answer_relevancy={metrics.get('answer_relevancy')}"
        )

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

    Requires the ragas library to be installed; ImportError propagates.
    """
    from datasets import Dataset

    # Build a single-row dataset
    ds = Dataset.from_dict(
        {
            "question": [question],
            "answer": [answer],
            "contexts": [contexts],
            "ground_truth": [ground_truth],
        }
    )

    result = evaluate(
        ds,
        metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
    )

    metrics = {}
    for key in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        val = result.get(key)
        if val is not None:
            try:
                metrics[key] = float(val[0]) if hasattr(val, "__getitem__") else float(val)
            except (TypeError, ValueError, IndexError):
                metrics[key] = None

    return metrics


def _percentile(values: list[float], p: float) -> float:
    """计算百分位数（纯 Python 实现，不依赖 numpy）。

    使用线性插值法：排序后取 k = (n-1) * p/100 的位置，
    在相邻两个值之间做线性插值。
    """
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < len(sorted_vals) else f
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def aggregate_metrics(results: list[dict]) -> dict[str, dict[str, float]]:
    """Aggregate individual metrics into distribution statistics.

    返回每个指标的分布统计：mean / p50 / p95 / min / max / std。
    空列表返回全 0 的分布字典。

    Shared by both the async :func:`run_evaluation` pipeline and the
    synchronous Celery task :mod:`app.tasks.evaluation_task`.
    """
    keys = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]
    aggregated = {}

    for key in keys:
        # mypy: r.get(key) 推断为 Any | None，列表推导式不会因 if 条件收窄类型，
        # 用 cast 显式声明为 list[float]（运行时已过滤 None）。
        values = cast(list[float], [r.get(key) for r in results if r.get(key) is not None])
        if values:
            aggregated[key] = {
                "mean": round(statistics.mean(values), 4),
                "p50": round(statistics.median(values), 4),
                "p95": round(_percentile(values, 95), 4),
                "min": round(min(values), 4),
                "max": round(max(values), 4),
                "std": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
            }
        else:
            aggregated[key] = {
                "mean": 0.0,
                "p50": 0.0,
                "p95": 0.0,
                "min": 0.0,
                "max": 0.0,
                "std": 0.0,
            }

    return aggregated
