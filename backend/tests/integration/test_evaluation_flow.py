"""评估闭环修复验证测试。

验证前置修复：
1. generate_test_dataset: ground_truth 由 _generate_ground_truth 独立生成（≠ chunk 原文）
2. generate_test_dataset: contexts 由 retriever.retrieve() 真实检索（≠ chunk 本身）
3. EvaluationRun 记录 prompt_version/retriever_top_k/rerank_top_k/trigger_source
4. aggregate_metrics 返回分布字典（mean/p50/p95/min/max/std）

fixture 适配：
  e2e conftest 的 base_url/admin_headers/kb_with_doc 是 session 级 HTTP fixture，
  integration 测试中不可用（clean_db 每个测试清空表）。此处定义 function 级
  本地版本，使用 async client (ASGITransport) + sync session 直接操作 DB。
"""

import asyncio
import os
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy import update as sa_update

from app.core.evaluation import aggregate_metrics
from app.db.document_chunk import DocumentChunk
from app.db.user import User
from app.services.evaluation_service import generate_test_dataset
from app.tasks.document_task import parse_document_task

# ============ 本地 fixtures ============


@pytest.fixture
async def admin_headers(client):
    """注册用户并提升为 admin（clean_db 清空 users 表后每个测试重建）。

    返回 {"Authorization": "Bearer <token>"} headers dict。
    """
    username = f"eval_admin_{uuid.uuid4().hex[:8]}"
    email = f"{username}@test.com"
    password = "Test@123456"

    r = await client.post(
        "/api/v1/auth/register",
        json={
            "username": username,
            "email": email,
            "password": password,
        },
    )
    assert r.status_code == 200, f"Register failed: {r.text}"
    user_id = r.json()["data"]["id"]

    # sync session 直接更新 role → admin
    from app.db.sync_session import get_sync_session

    session = get_sync_session()
    try:
        session.execute(sa_update(User).where(User.id == user_id).values(role="admin"))
        session.commit()
    finally:
        session.close()

    r2 = await client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": password,
        },
    )
    assert r2.status_code == 200, f"Login failed: {r2.text}"
    token = r2.json()["data"]["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def kb_with_doc(client, admin_headers):
    """创建 KB + 上传文档 + 同步解析（生成 chunks + embeddings）。

    不依赖 Celery worker：mock parse_document_task.delay 防止异步派发，
    然后调用 parse_document_task.apply 同步执行解析。
    """
    kb_r = await client.post(
        "/api/v1/knowledge-bases",
        json={
            "name": f"EvalTest_KB_{uuid.uuid4().hex[:8]}",
            "description": "评估闭环测试知识库",
        },
        headers=admin_headers,
    )
    assert kb_r.status_code == 200, f"Create KB failed: {kb_r.text}"
    kb_id = kb_r.json()["data"]["id"]

    test_doc_path = os.path.join(os.path.dirname(__file__), "test_doc.txt")
    with patch(
        "app.tasks.document_task.parse_document_task.delay",
        return_value=MagicMock(id="test-task-id"),
    ):
        with open(test_doc_path, "rb") as f:
            upload_r = await client.post(
                "/api/v1/documents/upload",
                files={"file": ("test_doc.txt", f, "text/plain")},
                data={"kb_id": str(kb_id)},
                headers=admin_headers,
            )
    assert upload_r.status_code == 200, f"Upload failed: {upload_r.text}"
    doc_id = upload_r.json()["data"]["document_id"]

    # 同步执行解析（parse_document_task 内部创建独立 event loop）
    # 保存/恢复当前 event loop，避免影响 pytest-asyncio 的 loop
    try:
        saved_loop = asyncio.get_event_loop()
    except RuntimeError:
        saved_loop = None
    try:
        parse_document_task.apply(args=[doc_id])
    finally:
        if saved_loop is not None:
            asyncio.set_event_loop(saved_loop)

    progress_r = await client.get(f"/api/v1/documents/{doc_id}/progress", headers=admin_headers)
    assert progress_r.status_code == 200
    progress_data = progress_r.json()["data"]
    assert progress_data["status"] == "done", (
        f"Doc parse failed: status={progress_data.get('status')}, "
        f"error={progress_data.get('error_message')}"
    )
    assert progress_data.get("chunk_count", 0) > 0, "No chunks created"

    return {"kb_id": kb_id, "doc_id": doc_id, "headers": admin_headers}


# ============ 测试用例 ============


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ground_truth_not_equal_chunk_content(client, kb_with_doc):
    """测试 1: ground_truth 由 _generate_ground_truth 独立生成，≠ chunk 原文。

    前置修复: evaluation_service.generate_test_dataset 中 ground_truth
    由 _generate_ground_truth(question, kb_description) 独立生成，
    不再 fallback 到 chunk.content。
    """
    kb_id = kb_with_doc["kb_id"]

    # 运行时导入 async_session，获取 _rebuild_async_engine 重建后的 session maker
    from app.database import async_session

    async with async_session() as db:
        dataset = await generate_test_dataset(kb_id, db, num_questions=3)

    assert len(dataset) > 0, "generate_test_dataset returned empty dataset"

    # 查询 KB 下所有 chunk 内容用于对比
    async with async_session() as db:
        result = await db.execute(select(DocumentChunk.content).where(DocumentChunk.kb_id == kb_id))
        chunk_contents = [row[0] for row in result.fetchall()]

    for entry in dataset:
        ground_truth = entry["ground_truth"]
        # ground_truth 非空且长度合理（> 10 字符）
        assert ground_truth is not None, "ground_truth is None"
        assert len(ground_truth) > 10, (
            f"ground_truth too short ({len(ground_truth)} chars): " f"{ground_truth[:50]}"
        )
        # ground_truth 不等于任何 chunk 原文（由 LLM 独立生成）
        for chunk_content in chunk_contents:
            assert ground_truth != chunk_content, (
                "ground_truth equals chunk content " "(should be independently generated)"
            )


@pytest.mark.asyncio
@pytest.mark.integration
async def test_contexts_from_real_retrieval(client, kb_with_doc):
    """测试 2: contexts 由 retriever.retrieve() 真实检索，≠ [chunk_content]。

    前置修复: evaluation_service.generate_test_dataset 中 contexts
    由 retriever.retrieve(question, kb_id) 真实检索得到，
    不再直接使用 [chunk.content]。
    """
    kb_id = kb_with_doc["kb_id"]

    from app.database import async_session

    async with async_session() as db:
        dataset = await generate_test_dataset(kb_id, db, num_questions=3)

    assert len(dataset) > 0, "generate_test_dataset returned empty dataset"

    async with async_session() as db:
        result = await db.execute(select(DocumentChunk.content).where(DocumentChunk.kb_id == kb_id))
        chunk_contents = [row[0] for row in result.fetchall()]

    for entry in dataset:
        contexts = entry["contexts"]
        # contexts 是列表且非空
        assert isinstance(contexts, list), f"contexts is not a list: {type(contexts)}"
        assert len(contexts) > 0, "contexts is empty"
        # contexts 不恒等于全部 chunk 列表（来自真实检索，非 chunk 本身）
        assert (
            contexts != chunk_contents
        ), "contexts equals all chunk contents (should be from real retrieval)"
        for ctx in contexts:
            assert isinstance(ctx, str), f"context item is not str: {type(ctx)}"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.slow
async def test_evaluation_run_records_params(client, kb_with_doc):
    """测试 3: EvaluationRun 记录 retriever_top_k/rerank_top_k/trigger_source。

    通过 API POST /evaluation/runs 触发评估，轮询直到完成，
    验证响应包含参数快照字段且 trigger_source='manual'。

    标记 @pytest.mark.slow: 真实评估涉及 LLM + RAGAS，可能很慢。
    """
    kb_id = kb_with_doc["kb_id"]
    headers = kb_with_doc["headers"]

    # Mock Celery delay 防止异步派发，后续手动同步执行评估
    with patch(
        "app.tasks.evaluation_task.run_evaluation_task.delay",
        return_value=MagicMock(id="test-eval-task-id"),
    ):
        trigger_r = await client.post(
            "/api/v1/evaluation/runs",
            params={"kb_id": kb_id, "num_questions": 3},
            headers=headers,
        )
    assert trigger_r.status_code == 200, f"Trigger eval failed: {trigger_r.text}"
    run_id = trigger_r.json()["data"]["run_id"]

    # 直接调用 async 评估函数（避免 Celery task 创建独立 event loop 的冲突）
    from app.tasks.evaluation_task import _run_evaluation_async

    await _run_evaluation_async(run_id)

    # 轮询直到 completed/failed，超时 5 分钟
    deadline = time.time() + 300
    final_status = None
    while time.time() < deadline:
        r = await client.get(f"/api/v1/evaluation/runs/{run_id}", headers=headers)
        assert r.status_code == 200, f"Get run failed: {r.text}"
        final_status = r.json()["data"]["status"]
        if final_status in ("completed", "failed"):
            break
        await asyncio.sleep(3)

    assert final_status == "completed", f"Evaluation did not complete: status={final_status}"

    # GET /evaluation/runs/{id} 检查响应字段
    r = await client.get(f"/api/v1/evaluation/runs/{run_id}", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]

    # 断言响应包含参数快照字段
    assert "retriever_top_k" in data, "Missing retriever_top_k field"
    assert "rerank_top_k" in data, "Missing rerank_top_k field"
    assert "trigger_source" in data, "Missing trigger_source field"

    # 断言 trigger_source == 'manual'（API 触发）
    assert (
        data["trigger_source"] == "manual"
    ), f"trigger_source={data['trigger_source']}, expected 'manual'"
    assert data["retriever_top_k"] is not None, "retriever_top_k is None"
    assert data["rerank_top_k"] is not None, "rerank_top_k is None"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_metrics_have_distribution():
    """测试 4: aggregate_metrics 返回分布字典（mean/p50/p95/min/max/std）。

    前置修复: aggregate_metrics 返回
    {"metric": {"mean":..., "p50":..., "p95":..., "min":..., "max":..., "std":...}}
    """
    results = [
        {"faithfulness": 0.8, "answer_relevancy": 0.7},
        {"faithfulness": 0.6, "answer_relevancy": 0.9},
        {"faithfulness": 0.9, "answer_relevancy": 0.8},
    ]
    aggregated = aggregate_metrics(results)

    expected_keys = {"mean", "p50", "p95", "min", "max", "std"}
    for metric_name in ["faithfulness", "answer_relevancy"]:
        assert metric_name in aggregated, f"Missing metric: {metric_name}"
        assert isinstance(
            aggregated[metric_name], dict
        ), f"{metric_name} is not a dict: {type(aggregated[metric_name])}"
        assert set(aggregated[metric_name].keys()) == expected_keys, (
            f"{metric_name} keys mismatch: "
            f"{set(aggregated[metric_name].keys())} != {expected_keys}"
        )

    # faithfulness 的 mean 应在 0.6-0.9 之间
    faith = aggregated["faithfulness"]
    assert 0.6 <= faith["mean"] <= 0.9, f"faithfulness.mean={faith['mean']}, expected in [0.6, 0.9]"
    # min/max 精确匹配
    assert faith["min"] == 0.6, f"faithfulness.min={faith['min']}, expected 0.6"
    assert faith["max"] == 0.9, f"faithfulness.max={faith['max']}, expected 0.9"
