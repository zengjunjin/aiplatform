"""Tests for app.core.evaluation Task 15 并发改造.

覆盖:
  - _eval_single_question 成功路径
  - _eval_single_question 失败隔离（异常被捕获，返回 success=False）
  - run_evaluation 并发执行所有问题（asyncio.gather）
  - 单题失败不阻断整体（其他题目结果正常保存）
  - aggregate_metrics 仅聚合成功题目的 metrics
  - DB 增量提交（每 10 题一次）
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core import evaluation


def _make_dataset(n=3):
    return [
        {
            "question": f"question-{i}",
            "ground_truth": f"truth-{i}",
            "contexts": [f"ctx-{i}"],
        }
        for i in range(n)
    ]


class TestEvalSingleQuestionSuccess:
    @pytest.mark.asyncio
    async def test_success_returns_metrics_and_success_true(self):
        """正常路径：返回 metrics dict + success=True。"""
        item = {"question": "q1", "ground_truth": "g1", "contexts": ["c1"]}
        semaphore = asyncio.Semaphore(8)
        fake_metrics = {"faithfulness": 0.9, "answer_relevancy": 0.8}

        with (
            patch(
                "app.core.evaluation.get_rag_answer",
                new=AsyncMock(return_value=("answer", ["retrieved"])),
            ),
            patch(
                "app.core.evaluation._compute_ragas_metrics",
                new=AsyncMock(return_value=fake_metrics),
            ),
        ):
            result = await evaluation._eval_single_question(item, kb_id=1, semaphore=semaphore)

        assert result["success"] is True
        assert result["question"] == "q1"
        assert result["ground_truth"] == "g1"
        assert result["answer"] == "answer"
        assert result["contexts"] == ["retrieved"]
        assert result["metrics"] == fake_metrics


class TestEvalSingleQuestionFailure:
    @pytest.mark.asyncio
    async def test_get_rag_answer_failure_isolates_exception(self):
        """get_rag_answer 抛异常时应返回 success=False，不阻断整体。"""
        item = {"question": "q1", "ground_truth": "g1", "contexts": ["c1"]}
        semaphore = asyncio.Semaphore(8)

        with patch(
            "app.core.evaluation.get_rag_answer",
            new=AsyncMock(side_effect=RuntimeError("rag down")),
        ):
            result = await evaluation._eval_single_question(item, kb_id=1, semaphore=semaphore)

        assert result["success"] is False
        assert result["question"] == "q1"
        assert "ERROR: rag down" in result["answer"]
        assert result["metrics"] == {}
        # 失败时 contexts 应保留原 reference_contexts
        assert result["contexts"] == ["c1"]

    @pytest.mark.asyncio
    async def test_compute_metrics_failure_isolates_exception(self):
        """_compute_ragas_metrics 抛异常时应返回 success=False。"""
        item = {"question": "q1", "ground_truth": "g1", "contexts": ["c1"]}
        semaphore = asyncio.Semaphore(8)

        with (
            patch(
                "app.core.evaluation.get_rag_answer",
                new=AsyncMock(return_value=("answer", ["retrieved"])),
            ),
            patch(
                "app.core.evaluation._compute_ragas_metrics",
                new=AsyncMock(side_effect=RuntimeError("ragas lib error")),
            ),
        ):
            result = await evaluation._eval_single_question(item, kb_id=1, semaphore=semaphore)

        assert result["success"] is False
        assert "ERROR: ragas lib error" in result["answer"]


class TestRunEvaluationConcurrency:
    @pytest.mark.asyncio
    async def test_all_questions_evaluated_concurrently(self):
        """3 个问题都应被评估，db.add 被调用 3 次。"""
        dataset = _make_dataset(n=3)
        db = AsyncMock()
        # db.execute 返回 run（用于最后更新 run.metrics）
        run_result = MagicMock()
        fake_run = MagicMock()
        run_result.scalar_one_or_none.return_value = fake_run
        db.execute = AsyncMock(return_value=run_result)

        fake_metrics = {
            "faithfulness": 0.9,
            "answer_relevancy": 0.8,
            "context_precision": 0.7,
            "context_recall": 0.6,
        }

        with (
            patch(
                "app.core.evaluation.get_rag_answer",
                new=AsyncMock(return_value=("answer", ["ctx"])),
            ),
            patch(
                "app.core.evaluation._compute_ragas_metrics",
                new=AsyncMock(return_value=fake_metrics),
            ),
        ):
            aggregated = await evaluation.run_evaluation(
                run_id=1,
                dataset=dataset,
                kb_id=1,
                db=db,
            )

        # 3 个问题都成功 → db.add 调用 3 次
        assert db.add.call_count == 3
        # run 状态被更新
        assert fake_run.status.value == "completed"  # EvaluationStatus.COMPLETED
        # aggregated 应该是 3 个 fake_metrics 的平均
        assert aggregated["faithfulness"]["mean"] == 0.9

    @pytest.mark.asyncio
    async def test_single_failure_does_not_block_others(self):
        """第 2 题失败不应阻断第 1、3 题，aggregate_metrics 仅用成功题目的 metrics。"""
        dataset = _make_dataset(n=3)
        db = AsyncMock()
        run_result = MagicMock()
        fake_run = MagicMock()
        run_result.scalar_one_or_none.return_value = fake_run
        db.execute = AsyncMock(return_value=run_result)

        # 第 2 题（idx=1）get_rag_answer 抛异常
        async def fake_get_rag_answer(question, kb_id):
            if question == "question-1":
                raise RuntimeError("intentional failure")
            return ("answer", ["ctx"])

        good_metrics = {
            "faithfulness": 0.9,
            "answer_relevancy": 0.8,
            "context_precision": 0.7,
            "context_recall": 0.6,
        }

        with (
            patch("app.core.evaluation.get_rag_answer", new=fake_get_rag_answer),
            patch(
                "app.core.evaluation._compute_ragas_metrics",
                new=AsyncMock(return_value=good_metrics),
            ),
        ):
            aggregated = await evaluation.run_evaluation(
                run_id=1,
                dataset=dataset,
                kb_id=1,
                db=db,
            )

        # 3 个问题都被 db.add（包括失败的，失败的有 null metrics）
        assert db.add.call_count == 3
        # aggregated 仅用 2 个成功题目的 metrics
        assert aggregated["faithfulness"]["mean"] == 0.9

    @pytest.mark.asyncio
    async def test_incremental_commit_every_10_questions(self):
        """15 个问题应触发增量提交：第 10 题一次 + 最后一次。"""
        dataset = _make_dataset(n=15)
        db = AsyncMock()
        run_result = MagicMock()
        fake_run = MagicMock()
        run_result.scalar_one_or_none.return_value = fake_run
        db.execute = AsyncMock(return_value=run_result)

        # commit 调用计数（增量 + 最后 + run 更新）
        # 注意：run_evaluation 最后还有一次 db.commit() 提交剩余 + 一次 db.commit() 更新 run
        # 所以总 commit 次数 = 增量次数(1) + 最后提交(1) + run更新(1) = 3
        fake_metrics = {"faithfulness": 0.5}

        with (
            patch("app.core.evaluation.get_rag_answer", new=AsyncMock(return_value=("a", ["c"]))),
            patch(
                "app.core.evaluation._compute_ragas_metrics",
                new=AsyncMock(return_value=fake_metrics),
            ),
        ):
            await evaluation.run_evaluation(
                run_id=1,
                dataset=dataset,
                kb_id=1,
                db=db,
            )

        # 15 题 → 第 10 题增量提交 1 次 + 最后提交 1 次 + run 更新 1 次 = 3 次
        # （注意 db.add 调用 15 次）
        assert db.add.call_count == 15
        assert db.commit.await_count >= 3

    @pytest.mark.asyncio
    async def test_empty_dataset_returns_zero_aggregate(self):
        """空 dataset 应返回全 0 的 aggregated metrics，db.add 不被调用。"""
        db = AsyncMock()
        run_result = MagicMock()
        fake_run = MagicMock()
        run_result.scalar_one_or_none.return_value = fake_run
        db.execute = AsyncMock(return_value=run_result)

        aggregated = await evaluation.run_evaluation(
            run_id=1,
            dataset=[],
            kb_id=1,
            db=db,
        )

        # 空数据集 → aggregate_metrics([]) 返回全 0
        assert aggregated["faithfulness"]["mean"] == 0.0
        assert db.add.call_count == 0
