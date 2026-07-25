"""Task 15: RAG 质量回归测试 (Golden QA Suite)

本测试集用于 RAG 管线质量回归监控，确保 prompt/retriever/context_manager 等改动
不会显著降低回答质量。

设计要点：
1. 15 条 golden QA（query + expected_answer_keywords + expected_context_keywords）
2. 每条 QA 通过 evaluation_service.get_rag_answer() 跑完整 RAG 管线
3. 用真实 ragas.evaluate 计算 faithfulness / context_recall 等指标
   - 强制依赖 ragas：ImportError 时测试自然 fail（不再 skip）
4. 断言 faithfulness > 0.7、context_recall > 0.6
5. 标记 @pytest.mark.e2e，与 e2e 测试一致（默认跳过，-m e2e 显式运行）

运行方式：
    # 默认跳过 e2e 测试（CI 默认）
    pytest tests/ -m "not e2e"

    # 显式运行 RAG 质量回归
    pytest tests/rag/test_rag_quality_regression.py -m e2e

前置条件：
    - LLM / Embedding / Qdrant / Redis 服务可达（rag_test_kb fixture 自动创建临时 KB）
    - ragas 已安装（未安装则 ImportError，测试 fail）
"""

import contextlib
import os
import time
import uuid

import pytest
import requests
from ragas import evaluate
from ragas.metrics import (
    answer_relevancy,
    context_precision,
    context_recall,
    faithfulness,
)

# ---------- 测试文档路径（复用 integration 的测试文档）----------

TEST_DOC_PATH = os.path.join(os.path.dirname(__file__), "..", "integration", "test_doc.txt")

# 文档解析等待超时（秒）
DOC_WAIT_TIMEOUT = 60


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


# ---------- Fixtures ----------


@pytest.fixture(scope="session")
def base_url():
    """API 基础地址，复用 e2e 约定（E2E_BASE_URL 环境变量）。"""
    return os.getenv("E2E_BASE_URL", "http://localhost:8000/api/v1")


@pytest.fixture(scope="session")
def admin_token(base_url):
    """登录 admin 获取 token。

    admin 密码通过环境变量 E2E_ADMIN_PASSWORD 注入（CI secret），
    默认值 "admin123" 仅用于本地开发环境。
    """
    admin_password = os.getenv("E2E_ADMIN_PASSWORD", "admin123")
    r = requests.post(
        f"{base_url}/auth/login",
        json={
            "username": "admin",
            "password": admin_password,
        },
        timeout=10,
    )
    assert r.status_code == 200, f"Admin login failed: {r.text}"
    body = r.json()
    return body.get("data", body) if isinstance(body, dict) else body


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    """带 admin JWT 的请求头。"""
    return {"Authorization": f"Bearer {admin_token['access_token']}"}


@pytest.fixture(scope="module")
def rag_test_kb(base_url, admin_headers):
    """自动创建临时 KB + 上传测试文档 + 等待解析完成。

    module scope：整个模块共享一个 KB，模块结束时清理（DELETE /knowledge-bases/{id}）。
    创建 KB 失败时 skip（环境问题允许 skip）。
    """
    # 1. 创建临时 KB
    kb_name = f"RAG_REGRESSION_{uuid.uuid4().hex[:8]}"
    try:
        r = requests.post(
            f"{base_url}/knowledge-bases",
            json={
                "name": kb_name,
                "description": "RAG 质量回归测试临时知识库",
            },
            headers=admin_headers,
            timeout=10,
        )
    except Exception as e:
        pytest.skip(f"无法创建测试 KB: {e}")
    if r.status_code != 200:
        pytest.skip(f"无法创建测试 KB: {r.text}")
    body = r.json()
    kb = body.get("data", body) if isinstance(body, dict) else body

    # 2. 上传测试文档
    try:
        with open(TEST_DOC_PATH, "rb") as f:
            files = {"file": ("test_doc.txt", f, "text/plain")}
            data = {"kb_id": str(kb["id"])}
            r2 = requests.post(
                f"{base_url}/documents/upload",
                files=files,
                data=data,
                headers=admin_headers,
                timeout=60,
            )
    except Exception as e:
        _cleanup_kb(base_url, admin_headers, kb["id"])
        pytest.skip(f"无法上传测试文档: {e}")
    if r2.status_code == 429:
        _cleanup_kb(base_url, admin_headers, kb["id"])
        pytest.skip(f"上传文档被限流 (429): {r2.text}")
    if r2.status_code != 200:
        _cleanup_kb(base_url, admin_headers, kb["id"])
        pytest.skip(f"无法上传测试文档: {r2.text}")

    upload_resp = r2.json()
    upload_data = (
        upload_resp.get("data", upload_resp) if isinstance(upload_resp, dict) else upload_resp
    )
    doc_id = upload_data["document_id"]

    # 3. 轮询 GET /documents/{doc_id} 直到 status == done
    deadline = time.time() + DOC_WAIT_TIMEOUT
    doc = None
    while time.time() < deadline:
        r3 = requests.get(
            f"{base_url}/documents/{doc_id}",
            headers=admin_headers,
            timeout=10,
        )
        if r3.status_code == 200:
            cur_body = r3.json()
            cur = cur_body.get("data", cur_body) if isinstance(cur_body, dict) else cur_body
            if cur.get("status") == "done":
                doc = cur
                break
            if cur.get("status") == "failed":
                _cleanup_kb(base_url, admin_headers, kb["id"])
                pytest.skip(f"文档解析失败: {cur.get('error_message')}")
        time.sleep(2)

    if doc is None:
        _cleanup_kb(base_url, admin_headers, kb["id"])
        pytest.skip("文档解析超时")

    yield kb

    # 4. 模块结束清理
    _cleanup_kb(base_url, admin_headers, kb["id"])


def _cleanup_kb(base_url: str, headers: dict, kb_id: int) -> None:
    """清理临时 KB（best-effort）。"""
    with contextlib.suppress(Exception):
        requests.delete(
            f"{base_url}/knowledge-bases/{kb_id}",
            headers=headers,
            timeout=5,
        )


# ---------- RAGAS 指标计算 ----------


async def _compute_ragas_metrics(
    question: str,
    answer: str,
    contexts: list[str],
    ground_truth: str,
) -> dict[str, float | None]:
    """调用真实 ragas.evaluate 计算指标。

    参考 app.core.evaluation._compute_ragas_metrics 的调用方式。
    ragas 未安装时 ImportError 向上传播，测试 fail（不再 skip）。
    """
    from datasets import Dataset

    # 构建单行数据集
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

    metrics: dict[str, float | None] = {}
    for key in ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]:
        val = result.get(key)
        if val is not None:
            try:
                metrics[key] = float(val[0]) if hasattr(val, "__getitem__") else float(val)
            except (TypeError, ValueError, IndexError):
                metrics[key] = None
        else:
            metrics[key] = None
    return metrics


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


@pytest.mark.e2e
class TestRAGQualityRegression:
    """RAG 质量回归测试套件。

    通过 golden QA 集对完整 RAG 管线进行端到端质量评估，
    确保检索/生成改动不引入质量退化。
    使用真实 RAGAS 指标（faithfulness / context_recall 等）。
    """

    @pytest.mark.asyncio
    async def test_rag_services_available(self, rag_test_kb):
        """前置检查：RAG 服务可达。不可达则跳过整个测试类。"""
        available = await _check_rag_services_available(rag_test_kb["id"])
        if not available:
            pytest.skip("RAG 依赖服务（Qdrant/LLM/Redis）不可达，跳过质量回归测试")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("qa", GOLDEN_QA_DATASET)
    async def test_golden_qa_faithfulness(self, qa: dict, rag_test_kb):
        """每条 golden QA 的 faithfulness > 0.7（真实 RAGAS）"""
        from app.services.evaluation_service import get_rag_answer

        answer, contexts = await get_rag_answer(qa["query"], rag_test_kb["id"])
        ground_truth = " ".join(qa["expected_answer_keywords"])
        metrics = await _compute_ragas_metrics(
            question=qa["query"],
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
        )
        faith = metrics.get("faithfulness")
        assert faith is not None, f"faithfulness 未返回 for query: '{qa['query'][:40]}...'"
        assert faith > FAITHFULNESS_THRESHOLD, (
            f"faithfulness={faith:.3f} 低于阈值 {FAITHFULNESS_THRESHOLD} "
            f"for query: '{qa['query'][:40]}...' | answer: '{answer[:80]}...'"
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("qa", GOLDEN_QA_DATASET)
    async def test_golden_qa_context_recall(self, qa: dict, rag_test_kb):
        """每条 golden QA 的 context_recall > 0.6（真实 RAGAS）"""
        from app.services.evaluation_service import get_rag_answer

        answer, contexts = await get_rag_answer(qa["query"], rag_test_kb["id"])
        ground_truth = " ".join(qa["expected_answer_keywords"])
        metrics = await _compute_ragas_metrics(
            question=qa["query"],
            answer=answer,
            contexts=contexts,
            ground_truth=ground_truth,
        )
        recall = metrics.get("context_recall")
        assert recall is not None, f"context_recall 未返回 for query: '{qa['query'][:40]}...'"
        assert recall > CONTEXT_RECALL_THRESHOLD, (
            f"context_recall={recall:.3f} 低于阈值 {CONTEXT_RECALL_THRESHOLD} "
            f"for query: '{qa['query'][:40]}...'"
        )

    @pytest.mark.asyncio
    async def test_aggregate_quality(self, rag_test_kb):
        """聚合质量：所有 golden QA 的平均 faithfulness/recall 达标。

        这是整体回归门槛，单条 QA 的退化会被聚合稀释，
        但若整体低于阈值说明管线存在系统性问题。
        """
        from app.services.evaluation_service import get_rag_answer

        faith_scores: list[float] = []
        recall_scores: list[float] = []
        for qa in GOLDEN_QA_DATASET:
            answer, contexts = await get_rag_answer(qa["query"], rag_test_kb["id"])
            ground_truth = " ".join(qa["expected_answer_keywords"])
            metrics = await _compute_ragas_metrics(
                question=qa["query"],
                answer=answer,
                contexts=contexts,
                ground_truth=ground_truth,
            )
            if metrics.get("faithfulness") is not None:
                faith_scores.append(metrics["faithfulness"])
            if metrics.get("context_recall") is not None:
                recall_scores.append(metrics["context_recall"])

        avg_faith = sum(faith_scores) / len(faith_scores) if faith_scores else 0.0
        avg_recall = sum(recall_scores) / len(recall_scores) if recall_scores else 0.0

        assert (
            avg_faith > FAITHFULNESS_THRESHOLD
        ), f"平均 faithfulness={avg_faith:.3f} 低于阈值 {FAITHFULNESS_THRESHOLD}"
        assert (
            avg_recall > CONTEXT_RECALL_THRESHOLD
        ), f"平均 context_recall={avg_recall:.3f} 低于阈值 {CONTEXT_RECALL_THRESHOLD}"


class TestGoldenQADatasetIntegrity:
    """Golden QA 数据集完整性校验（快速测试，不需 RAG 服务，非 e2e）。"""

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
            assert (
                "expected_context_keywords" in qa
            ), f"Entry {i} missing 'expected_context_keywords'"
            assert (
                isinstance(qa["expected_answer_keywords"], list) and qa["expected_answer_keywords"]
            ), f"Entry {i} has empty expected_answer_keywords"
            assert (
                isinstance(qa["expected_context_keywords"], list)
                and qa["expected_context_keywords"]
            ), f"Entry {i} has empty expected_context_keywords"

    def test_queries_are_unique(self):
        """所有 query 唯一（避免重复测试）"""
        queries = [qa["query"] for qa in GOLDEN_QA_DATASET]
        assert len(queries) == len(set(queries)), "存在重复的 query"

    def test_thresholds_are_reasonable(self):
        """阈值在合理范围"""
        assert 0.0 < FAITHFULNESS_THRESHOLD < 1.0
        assert 0.0 < CONTEXT_RECALL_THRESHOLD < 1.0
