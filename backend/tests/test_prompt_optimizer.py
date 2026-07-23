"""Tests for app.core.prompt_optimizer.generate_optimization_suggestions"""
import pytest

from app.core.prompt_optimizer import generate_optimization_suggestions


def _make_feedback_data(patterns: dict | None = None, **kwargs) -> dict:
    """构造 analyze_feedback() 返回格式的测试数据"""
    default_patterns = {
        "context_insufficient": 0,
        "retrieval_bias": 0,
        "faithfulness_issue": 0,
        "incompleteness": 0,
        "irrelevance": 0,
        "verbosity": 0,
    }
    if patterns:
        default_patterns.update(patterns)
    return {
        "stats": kwargs.get("stats", {
            "total_feedback": kwargs.get("total_feedback", 10),
            "positive_rate": kwargs.get("positive_rate", 0.6),
            "negative_rate": kwargs.get("negative_rate", 0.4),
        }),
        "failure_patterns": default_patterns,
        "low_rated_samples": kwargs.get("low_rated_samples", []),
        "suggestions": kwargs.get("suggestions", []),
    }


class TestFaithfulnessIssueSuggestions:
    @pytest.mark.asyncio
    async def test_faithfulness_issue_suggestions(self):
        """failure_patterns['faithfulness_issue'] > 0 生成忠实度约束建议"""
        data = _make_feedback_data(
            patterns={"faithfulness_issue": 3},
            total_feedback=20,
            negative_rate=0.5,
        )
        result = await generate_optimization_suggestions(data)

        suggestions = result["suggestions"]
        assert len(suggestions) == 1
        assert suggestions[0]["rule"] == "增强忠实度约束"
        assert "3" in suggestions[0]["reason"]
        assert suggestions[0]["severity"] == "high"

        # 应生成对应的 prompt 约束
        constraints = result["prompt_constraints"]
        assert len(constraints) == 1
        assert "上下文" in constraints[0]

        # summary 应包含反馈数
        assert "20" in result["summary"]
        assert "1 个优化方向" in result["summary"]


class TestContextInsufficientSuggestions:
    @pytest.mark.asyncio
    async def test_context_insufficient_suggestions(self):
        """failure_patterns['context_insufficient'] > 0 生成上下文覆盖检查建议"""
        data = _make_feedback_data(patterns={"context_insufficient": 5})
        result = await generate_optimization_suggestions(data)

        suggestions = result["suggestions"]
        assert len(suggestions) == 1
        assert suggestions[0]["rule"] == "增强上下文覆盖检查"
        assert "5" in suggestions[0]["reason"]
        assert suggestions[0]["severity"] == "high"

        constraints = result["prompt_constraints"]
        assert len(constraints) == 1
        assert "上下文" in constraints[0]


class TestIncompletenessSuggestions:
    @pytest.mark.asyncio
    async def test_incompleteness_suggestions(self):
        """failure_patterns['incompleteness'] > 0 生成完整性要求建议"""
        data = _make_feedback_data(patterns={"incompleteness": 2})
        result = await generate_optimization_suggestions(data)

        suggestions = result["suggestions"]
        assert len(suggestions) == 1
        assert suggestions[0]["rule"] == "增强完整性要求"
        assert "2" in suggestions[0]["reason"]
        assert suggestions[0]["severity"] == "medium"

        constraints = result["prompt_constraints"]
        assert len(constraints) == 1
        assert "关键信息" in constraints[0]


class TestIrrelevanceSuggestions:
    @pytest.mark.asyncio
    async def test_irrelevance_suggestions(self):
        """failure_patterns['irrelevance'] > 0 生成相关性过滤建议"""
        data = _make_feedback_data(patterns={"irrelevance": 4})
        result = await generate_optimization_suggestions(data)

        suggestions = result["suggestions"]
        assert len(suggestions) == 1
        assert suggestions[0]["rule"] == "增强相关性过滤"
        assert "4" in suggestions[0]["reason"]
        assert suggestions[0]["severity"] == "medium"

        constraints = result["prompt_constraints"]
        assert len(constraints) == 1
        assert "相关" in constraints[0]


class TestVerbositySuggestions:
    @pytest.mark.asyncio
    async def test_verbosity_suggestions(self):
        """failure_patterns['verbosity'] > 0 生成长度控制建议"""
        data = _make_feedback_data(patterns={"verbosity": 1})
        result = await generate_optimization_suggestions(data)

        suggestions = result["suggestions"]
        assert len(suggestions) == 1
        assert suggestions[0]["rule"] == "优化回答长度控制"
        assert "1" in suggestions[0]["reason"]
        assert suggestions[0]["severity"] == "low"

        constraints = result["prompt_constraints"]
        assert len(constraints) == 1
        assert "长度" in constraints[0]


class TestMixedPatterns:
    @pytest.mark.asyncio
    async def test_mixed_patterns(self):
        """多 pattern 混合时生成多个建议，顺序与代码检查顺序一致"""
        data = _make_feedback_data(patterns={
            "faithfulness_issue": 2,
            "context_insufficient": 3,
            "incompleteness": 1,
            "irrelevance": 1,
            "verbosity": 1,
        })
        result = await generate_optimization_suggestions(data)

        suggestions = result["suggestions"]
        # 5 个 pattern 都 > 0 → 5 个建议
        assert len(suggestions) == 5
        # 验证顺序: faithfulness → context_insufficient → incompleteness → irrelevance → verbosity
        rules = [s["rule"] for s in suggestions]
        assert rules == [
            "增强忠实度约束",
            "增强上下文覆盖检查",
            "增强完整性要求",
            "增强相关性过滤",
            "优化回答长度控制",
        ]
        # severity 对应: high, high, medium, medium, low
        severities = [s["severity"] for s in suggestions]
        assert severities == ["high", "high", "medium", "medium", "low"]

        # 5 个 prompt 约束
        assert len(result["prompt_constraints"]) == 5

        # summary 包含 5 个优化方向
        assert "5 个优化方向" in result["summary"]


class TestEmptyPatterns:
    @pytest.mark.asyncio
    async def test_empty_patterns(self):
        """无 pattern 返回空列表"""
        data = _make_feedback_data(patterns={}, total_feedback=5, negative_rate=0.0)
        result = await generate_optimization_suggestions(data)

        assert result["suggestions"] == []
        assert result["prompt_constraints"] == []
        # summary 仍包含反馈统计
        assert "5" in result["summary"]
        # 无优化方向时不追加方向描述
        assert "优化方向" not in result["summary"]

    @pytest.mark.asyncio
    async def test_all_zero_patterns(self):
        """所有 pattern 为 0 时返回空列表"""
        data = _make_feedback_data()
        result = await generate_optimization_suggestions(data)

        assert result["suggestions"] == []
        assert result["prompt_constraints"] == []

    @pytest.mark.asyncio
    async def test_sample_insights_extracted(self):
        """low_rated_samples 中的 comment 被提取到 sample_insights"""
        data = _make_feedback_data(
            low_rated_samples=[
                {"question": "q1", "answer": "a1", "comment": "太长了"},
                {"question": "q2", "answer": "a2", "comment": "不准确"},
                {"question": "q3", "answer": "a3"},  # 无 comment
            ],
        )
        result = await generate_optimization_suggestions(data)

        # 只提取有 comment 的样本，且最多 5 条
        assert len(result["sample_insights"]) == 2
        assert "太长了" in result["sample_insights"][0]
        assert "不准确" in result["sample_insights"][1]

    @pytest.mark.asyncio
    async def test_original_suggestions_passed_through(self):
        """原始 suggestions 透传到 original_suggestions"""
        data = _make_feedback_data(suggestions=["建议1", "建议2"])
        result = await generate_optimization_suggestions(data)

        assert result["original_suggestions"] == ["建议1", "建议2"]
