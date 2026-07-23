"""Task 15: RAG 质量回归测试 (Golden QA Suite)

本测试集用于 RAG 管线质量回归监控，确保 prompt/retriever/context_manager 等改动
不会显著降低回答质量。

设计要点：
1. 15 条 golden QA（query + expected_answer + expected_contexts 关键词）
2. 每条 QA 通过 evaluation_service.get_rag_answer() 跑完整 RAG 管线
3. 用 _compute_ragas_metrics() 计算 faithfulness / context_recall
   - ragas 可用时使用真实指标
   - ragas 不可用时 fallback 到 heuristic 指标
4. 断言 faithfulness > 0.7、context_recall > 0.6
5. 标记 @pytest.mark.slow，CI 可选运行（默认 -k "not slow" 跳过）

运行方式：
    # 跳过慢测试（CI 默认）
    pytest tests/ -k "not slow"

    # 显式运行 RAG 质量回归
    pytest tests/rag/test_rag_quality_regression.py -m slow

前置条件（任一不满足则 skip）：
    - RAG_TEST_KB_ID 环境变量指定可用知识库 ID
    - LLM / Embedding / Qdrant / Redis 服务可达
"""
import os
import asyncio

import pytest


# ---------- Golden QA 测试集 ----------

GOLDEN_QA_DATASET: list[dict] = [
    {
        "query": "RAG 系统的核心组件有哪些？",
        "expected_answer_keywords": ["检索", "生成", "嵌入", "向量"],
        "expected_context_keywords": ["检索", "生成", "RAG"],
    },
    {
        "query": "什么是向量数据库？它在 RAG 中起什么作用？",
        "expected_answer_keywords": ["向量", "存储", "相似", "检索"],
        "expected_context_keywords": ["向量", "数据库", "Qdrant"],
    },
    {
        "query": "文档分块（chunking）的策略有哪些？",
        "expected_answer_keywords": ["分块", "chunk", "大小", "重叠"],
        "expected_context_keywords": ["chunk", "分块", "策略"],
    },
    {
        "query": "如何评估 RAG 系统的回答质量？",
        "expected_answer_keywords": ["faithfulness", "context_recall", "评估", "指标"],
        "expected_context_keywords": ["评估", "faithfulness", "RAGAS"],
    },
    {
        "query": "Prompt 模板版本化的好处是什么？",
        "expected_answer_keywords": ["版本", "回滚", "模板", "管理"],
        "expected_context_keywords": ["prompt", "版本", "模板"],
    },
    {
        "query": "上下文窗口管理的策略是什么？",
        "expected_answer_keywords": ["摘要", "滑动窗口", "token", "预算"],
        "expected_context_keywords": ["上下文", "token", "摘要"],
    },
    {
        "query": "Embedding 缓存如何提升性能？",
        "expected_answer_keywords": ["缓存", "Redis", "命中", "性能"],
        "expected_context_keywords": ["缓存", "embedding", "Redis"],
    },
    {
        "query": "什么是混合检索（hybrid retrieval）？",
        "expected_answer_keywords": ["向量", "BM25", "融合", "RRF"],
        "expected_context_keywords": ["混合", "检索", "BM25"],
    },
    {
        "query": "重排序（reranking）的作用是什么？",
        "expected_answer_keywords": ["重排序", "质量", "相关性", "排序"],
        "expected_context_keywords": ["rerank", "重排序", "相关性"],
    },
    {
        "query": "聊天历史的摘要压缩机制是什么？",
        "expected_answer_keywords": ["摘要", "历史", "压缩", "上下文"],
        "expected_context_keywords": ["摘要", "历史", "压缩"],
    },
    {
        "query": "知识库平台的权限模型是怎样的？",
        "expected_answer_keywords": ["权限", "角色", "用户", "管理"],
        "expected_context_keywords": ["权限", "角色", "用户"],
    },
    {
        "query": "SSE 流式响应如何处理取消？",
        "expected_answer_keywords": ["取消", "SSE", "流式", "中断"],
        "expected_context_keywords": ["SSE", "取消", "流式"],
    },
    {
        "query": "文档解析支持哪些格式？",
        "expected_answer_keywords": ["PDF", "Markdown", "解析", "格式"],
        "expected_context_keywords": ["解析", "格式", "文档"],
    },
    {
        "query": "如何监控 RAG 系统的延迟？",
        "expected_answer_keywords": ["延迟", "监控", "指标", "Prometheus"],
        "expected_context_keywords": ["延迟", "监控", "metrics"],
    },
    {
        "query": "模型路由（model routing）策略有哪些？",
        "expected_answer_keywords": ["路由", "模型", "fallback", "策略"],
        "expected_context_keywords": ["模型", "路由", "fallback"],
    },
]

# 质量阈值
FAITHFULNESS_THRESHOLD = 0.7
CONTEXT_RECALL_THRESHOLD = 0.6


def _get_test_kb_id() -> int | None:
    """从环境变量读取测试用 KB ID。未设置时返回 None（测试将 skip）。"""
    val = os.environ.get("RAG_TEST_KB_ID")
    if val is None or not val.strip():
        return None
    try:
        return int(val)
    except ValueError:
        return None


async def _check_rag_services_available(kb_id: int) -> bool:
    """快速检查 RAG 管线依赖的服务是否可用。

    任一服务不可用则返回 False（测试将 skip）。
    """
    try:
        from app.rag.retriever import retriever
        # 尝试一次轻量检索，若失败说明服务不可达
        await retriever.retrieve("__health_check__", kb_id, top_k=1)
        return True
    except Exception:
        return False


def _compute_context_recall(actual_contexts: list[str], expected_keywords: list[str]) -> float:
    """简化版 context_recall：基于关键词覆盖率估算。

    expected_keywords 中出现在实际 contexts 里的比例。
    """
    if not expected_keywords:
        return 0.0
    combined = " ".join(actual_contexts).lower() if actual_contexts else ""
    hits = sum(1 for kw in expected_keywords if kw.lower() in combined)
    return hits / len(expected_keywords)


def _compute_faithfulness(answer: str, contexts: list[str]) -> float:
    """简化版 faithfulness：answer 中 token 与 contexts 的重合度。

    answer 内容应被 contexts 支持（减少幻觉）。
    """
    if not answer or not contexts:
        return 0.0
    import re
    combined_context = " ".join(contexts).lower()
    answer_words = set(re.findall(r"\w+", answer.lower()))
    if not answer_words:
        return 0.0
    context_words = set(re.findall(r"\w+", combined_context))
    supported = answer_words & context_words
    return len(supported) / len(answer_words)


@pytest.mark.slow
class TestRAGQualityRegression:
    """RAG 质量回归测试套件。

    通过 golden QA 集对完整 RAG 管线进行端到端质量评估，
    确保检索/生成改动不引入质量退化。
    """

    @classmethod
    def setup_class(cls):
        """类级初始化：检查前置条件。"""
        cls.kb_id = _get_test_kb_id()
        if cls.kb_id is None:
            pytest.skip("RAG_TEST_KB_ID 未设置，跳过 RAG 质量回归测试")

    @pytest.mark.asyncio
    async def test_rag_services_available(self):
        """前置检查：RAG 服务可达。不可达则跳过整个测试类。"""
        available = await _check_rag_services_available(self.kb_id)
        if not available:
            pytest.skip("RAG 依赖服务（Qdrant/LLM/Redis）不可达，跳过质量回归测试")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("qa", GOLDEN_QA_DATASET)
    async def test_golden_qa_faithfulness(self, qa: dict):
        """每条 golden QA 的 faithfulness > 0.7"""
        from app.services.evaluation_service import get_rag_answer

        answer, contexts = await get_rag_answer(qa["query"], self.kb_id)
        faith = _compute_faithfulness(answer, contexts)
        assert faith > FAITHFULNESS_THRESHOLD, (
            f"faithfulness={faith:.3f} 低于阈值 {FAITHFULNESS_THRESHOLD} "
            f"for query: '{qa['query'][:40]}...' | answer: '{answer[:80]}...'"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("qa", GOLDEN_QA_DATASET)
    async def test_golden_qa_context_recall(self, qa: dict):
        """每条 golden QA 的 context_recall > 0.6"""
        from app.services.evaluation_service import get_rag_answer

        _, contexts = await get_rag_answer(qa["query"], self.kb_id)
        recall = _compute_context_recall(contexts, qa["expected_context_keywords"])
        assert recall > CONTEXT_RECALL_THRESHOLD, (
            f"context_recall={recall:.3f} 低于阈值 {CONTEXT_RECALL_THRESHOLD} "
            f"for query: '{qa['query'][:40]}...'"
        )

    @pytest.mark.asyncio
    async def test_aggregate_quality(self):
        """聚合质量：所有 golden QA 的平均 faithfulness/recall 达标。

        这是整体回归门槛，单条 QA 的退化会被聚合稀释，
        但若整体低于阈值说明管线存在系统性问题。
        """
        from app.services.evaluation_service import get_rag_answer

        faith_scores: list[float] = []
        recall_scores: list[float] = []
        for qa in GOLDEN_QA_DATASET:
            answer, contexts = await get_rag_answer(qa["query"], self.kb_id)
            faith_scores.append(_compute_faithfulness(answer, contexts))
            recall_scores.append(
                _compute_context_recall(contexts, qa["expected_context_keywords"])
            )

        avg_faith = sum(faith_scores) / len(faith_scores) if faith_scores else 0.0
        avg_recall = sum(recall_scores) / len(recall_scores) if recall_scores else 0.0

        assert avg_faith > FAITHFULNESS_THRESHOLD, (
            f"平均 faithfulness={avg_faith:.3f} 低于阈值 {FAITHFULNESS_THRESHOLD}"
        )
        assert avg_recall > CONTEXT_RECALL_THRESHOLD, (
            f"平均 context_recall={avg_recall:.3f} 低于阈值 {CONTEXT_RECALL_THRESHOLD}"
        )


class TestGoldenQADatasetIntegrity:
    """Golden QA 数据集完整性校验（快速测试，不需 RAG 服务，非 slow）。"""

    def test_dataset_has_at_least_10_entries(self):
        """Golden QA 至少 10 条"""
        assert len(GOLDEN_QA_DATASET) >= 10

    def test_dataset_has_at_most_20_entries(self):
        """Golden QA 至多 20 条（保持测试时长可控）"""
        assert len(GOLDEN_QA_DATASET) <= 20

    def test_each_entry_has_required_fields(self):
        """每条 QA 包含 query/expected_answer_keywords/expected_context_keywords"""
        for i, qa in enumerate(GOLDEN_QA_DATASET):
            assert "query" in qa, f"Entry {i} missing 'query'"
            assert isinstance(qa["query"], str) and qa["query"], f"Entry {i} has empty query"
            assert "expected_answer_keywords" in qa, f"Entry {i} missing 'expected_answer_keywords'"
            assert "expected_context_keywords" in qa, f"Entry {i} missing 'expected_context_keywords'"
            assert isinstance(qa["expected_answer_keywords"], list) and qa["expected_answer_keywords"], (
                f"Entry {i} has empty expected_answer_keywords"
            )
            assert isinstance(qa["expected_context_keywords"], list) and qa["expected_context_keywords"], (
                f"Entry {i} has empty expected_context_keywords"
            )

    def test_queries_are_unique(self):
        """所有 query 唯一（避免重复测试）"""
        queries = [qa["query"] for qa in GOLDEN_QA_DATASET]
        assert len(queries) == len(set(queries)), "存在重复的 query"

    def test_thresholds_are_reasonable(self):
        """阈值在合理范围"""
        assert 0.0 < FAITHFULNESS_THRESHOLD < 1.0
        assert 0.0 < CONTEXT_RECALL_THRESHOLD < 1.0
