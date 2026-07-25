"""Tests for app.tasks.feedback_analysis_task"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.tasks import feedback_analysis_task
from app.tasks.feedback_analysis_task import (
    _cleanup_old_reports,
    _generate_markdown_report,
    run_feedback_analysis,
)


def _fake_analysis() -> dict:
    """构造 analyze_feedback() 返回格式的测试数据"""
    return {
        "stats": {
            "total_feedback": 10,
            "positive_rate": 0.6,
            "negative_rate": 0.4,
            "by_type": {"hallucination": 2, "incomplete": 1, "not_accurate": 1},
        },
        "failure_patterns": {
            "context_insufficient": 1,
            "retrieval_bias": 0,
            "faithfulness_issue": 2,
            "incompleteness": 1,
            "irrelevance": 0,
            "verbosity": 0,
        },
        "suggestions": ["增加上下文覆盖", "提升回答准确性"],
        "low_rated_samples": [
            {
                "question": "什么是 RAG？",
                "answer": "RAG 是一种检索增强生成技术",
                "feedback_type": "hallucination",
                "comment": "回答有幻觉",
            },
        ],
    }


def _make_mock_async_session():
    """构造 mock async_session，支持 `async with async_session() as db:`"""
    mock_db = AsyncMock()
    mock_async_session = MagicMock()
    mock_async_session.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_async_session.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_async_session


class TestReportGenerated:
    def test_report_generated(self, tmp_path):
        """验证报告文件生成"""
        mock_session = _make_mock_async_session()

        with (
            patch.object(feedback_analysis_task, "async_session", mock_session),
            patch.object(
                feedback_analysis_task,
                "analyze_feedback",
                new=AsyncMock(return_value=_fake_analysis()),
            ),
            patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)),
        ):
            result = run_feedback_analysis()

        # 返回值包含报告路径和统计信息
        assert "report_path" in result
        assert result["total_feedback"] == 10
        assert result["negative_rate"] == 0.4
        assert result["suggestions_count"] > 0

        # 报告文件已生成
        report_path = result["report_path"]
        assert os.path.exists(report_path)
        assert report_path.endswith(".md")

    def test_report_generated_in_specified_dir(self, tmp_path):
        """报告生成在 REPORT_DIR 指定目录"""
        mock_session = _make_mock_async_session()

        with (
            patch.object(feedback_analysis_task, "async_session", mock_session),
            patch.object(
                feedback_analysis_task,
                "analyze_feedback",
                new=AsyncMock(return_value=_fake_analysis()),
            ),
            patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)),
        ):
            result = run_feedback_analysis()

        report_path = result["report_path"]
        # 报告在 tmp_path 目录下
        assert os.path.dirname(report_path) == str(tmp_path)


class TestReportContentFormat:
    def test_report_content_contains_stats(self, tmp_path):
        """验证报告包含统计信息"""
        mock_session = _make_mock_async_session()
        analysis = _fake_analysis()

        with (
            patch.object(feedback_analysis_task, "async_session", mock_session),
            patch.object(
                feedback_analysis_task, "analyze_feedback", new=AsyncMock(return_value=analysis)
            ),
            patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)),
        ):
            result = run_feedback_analysis()

        with open(result["report_path"], encoding="utf-8") as f:
            content = f.read()

        # 包含标题
        assert "# 反馈分析报告" in content
        # 包含统计概览
        assert "## 概览" in content
        assert "总反馈数" in content
        assert "10" in content
        assert "正向率" in content
        assert "负向率" in content
        # 包含反馈类型分布
        assert "反馈类型分布" in content
        assert "hallucination" in content

    def test_report_content_contains_failure_patterns(self, tmp_path):
        """验证报告包含失败模式分析"""
        mock_session = _make_mock_async_session()

        with (
            patch.object(feedback_analysis_task, "async_session", mock_session),
            patch.object(
                feedback_analysis_task,
                "analyze_feedback",
                new=AsyncMock(return_value=_fake_analysis()),
            ),
            patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)),
        ):
            result = run_feedback_analysis()

        with open(result["report_path"], encoding="utf-8") as f:
            content = f.read()

        # 包含失败模式分析
        assert "## 失败模式分析" in content
        assert "忠实度问题" in content
        assert "完整性不足" in content
        assert "上下文覆盖不足" in content

    def test_report_content_contains_suggestions(self, tmp_path):
        """验证报告包含优化建议"""
        mock_session = _make_mock_async_session()

        with (
            patch.object(feedback_analysis_task, "async_session", mock_session),
            patch.object(
                feedback_analysis_task,
                "analyze_feedback",
                new=AsyncMock(return_value=_fake_analysis()),
            ),
            patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)),
        ):
            result = run_feedback_analysis()

        with open(result["report_path"], encoding="utf-8") as f:
            content = f.read()

        # 包含优化建议
        assert "## 优化建议" in content
        assert "增加上下文覆盖" in content
        # 包含 Prompt 约束建议（由 generate_optimization_suggestions 生成）
        assert "Prompt 约束建议" in content
        # 包含优化规则表格
        assert "优化规则" in content
        assert "增强忠实度约束" in content

    def test_report_content_contains_samples(self, tmp_path):
        """验证报告包含低分样本"""
        mock_session = _make_mock_async_session()

        with (
            patch.object(feedback_analysis_task, "async_session", mock_session),
            patch.object(
                feedback_analysis_task,
                "analyze_feedback",
                new=AsyncMock(return_value=_fake_analysis()),
            ),
            patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)),
        ):
            result = run_feedback_analysis()

        with open(result["report_path"], encoding="utf-8") as f:
            content = f.read()

        assert "## 低分样本" in content
        assert "什么是 RAG" in content
        assert "回答有幻觉" in content


class TestCleanupOldReports:
    def _create_reports(self, dir_path: str, count: int) -> list[str]:
        """创建 count 个测试报告文件，日期递增"""
        os.makedirs(dir_path, exist_ok=True)
        base_date = datetime(2025, 1, 1, tzinfo=UTC)
        filenames = []
        for i in range(count):
            start = base_date + timedelta(weeks=i)
            end = start + timedelta(days=6)
            fname = f"feedback_report_{start.strftime('%Y%m%d')}_{end.strftime('%Y%m%d')}.md"
            path = os.path.join(dir_path, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"report week {i}")
            filenames.append(fname)
        return filenames

    def test_cleanup_old_reports_keeps_12(self, tmp_path):
        """生成 15 个报告，验证保留 12 个（keep=12）"""
        self._create_reports(str(tmp_path), 15)

        with patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)):
            _cleanup_old_reports(keep=12)

        remaining = [f for f in os.listdir(str(tmp_path)) if f.endswith(".md")]
        assert len(remaining) == 12

    def test_cleanup_keeps_latest(self, tmp_path):
        """验证保留的是最新的报告"""
        self._create_reports(str(tmp_path), 15)

        with patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)):
            _cleanup_old_reports(keep=12)

        remaining = sorted(
            [f for f in os.listdir(str(tmp_path)) if f.endswith(".md")],
            reverse=True,
        )
        # 保留的 12 个应该是最新的（i=3 到 i=14）
        # 最新的（i=14）应存在
        base_date = datetime(2025, 1, 1, tzinfo=UTC)
        newest_start = base_date + timedelta(weeks=14)
        newest_end = newest_start + timedelta(days=6)
        newest_name = (
            f"feedback_report_{newest_start.strftime('%Y%m%d')}_{newest_end.strftime('%Y%m%d')}.md"
        )
        assert newest_name in remaining

        # 最旧的 3 个（i=0,1,2）应被删除
        oldest_start = base_date
        oldest_end = oldest_start + timedelta(days=6)
        oldest_name = (
            f"feedback_report_{oldest_start.strftime('%Y%m%d')}_{oldest_end.strftime('%Y%m%d')}.md"
        )
        assert oldest_name not in remaining

    def test_cleanup_fewer_than_keep_does_nothing(self, tmp_path):
        """报告数 < keep 时不删除任何文件"""
        self._create_reports(str(tmp_path), 5)

        with patch.object(feedback_analysis_task, "_get_report_dir", return_value=str(tmp_path)):
            _cleanup_old_reports(keep=12)

        remaining = [f for f in os.listdir(str(tmp_path)) if f.endswith(".md")]
        assert len(remaining) == 5

    def test_cleanup_nonexistent_dir_no_error(self, tmp_path):
        """目录不存在时不报错"""
        nonexistent = str(tmp_path / "nonexistent")
        with patch.object(feedback_analysis_task, "_get_report_dir", return_value=nonexistent):
            # 不应抛异常
            _cleanup_old_reports(keep=12)


class TestGenerateMarkdownReport:
    def test_generate_markdown_report_structure(self):
        """测试 _generate_markdown_report 生成完整报告结构"""
        analysis = _fake_analysis()
        # 使用真实的 generate_optimization_suggestions 生成 optimization
        import asyncio

        from app.core.prompt_optimizer import generate_optimization_suggestions

        optimization = asyncio.new_event_loop().run_until_complete(
            generate_optimization_suggestions(analysis)
        )

        start = datetime(2025, 6, 1, tzinfo=UTC)
        end = datetime(2025, 6, 7, tzinfo=UTC)
        report = _generate_markdown_report(analysis, optimization, start, end)

        assert "# 反馈分析报告" in report
        assert "2025-06-01" in report
        assert "2025-06-07" in report
        assert "## 概览" in report
        assert "## 失败模式分析" in report
        assert "## 优化建议" in report
        assert "## 总结" in report
