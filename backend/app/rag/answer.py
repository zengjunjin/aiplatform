"""RAG 回答生成（Blade 2 Step 2：从 evaluation_service.py 下沉至 rag/answer.py）。

下沉目的：
- 原 evaluation_service.py（services 层）中 get_rag_answer 被 evaluation_engine.py（也迁至 services 层）
  import，但 services 层不应反向 import services 层另一个模块的 RAG 逻辑。
- get_rag_answer 本质是 RAG 检索 + prompt 构建 + LLM 生成，属于 rag 层职责。
- 迁至 rag/answer.py 后，evaluation_engine → rag.answer 方向合规。

依赖方向：services/evaluation_engine → rag/answer → rag/retriever / rag/prompt_builder / models/factory
"""
from __future__ import annotations

from loguru import logger

from app.config import settings


async def get_rag_answer(
    query: str, kb_id: int, llm=None
) -> tuple[str, list[str]]:
    """Run the RAG pipeline to get an answer and retrieved contexts.

    修复（v0.4.0）：移除宽泛 except Exception，让异常向上抛出。
    调用方 _run_evaluations 用 asyncio.gather(return_exceptions=True) 捕获异常做失败隔离。
    之前吞异常导致失败题目被记为"成功评估"，错误答案污染聚合结果。

    T8（P3）：llm 参数允许调用方传入已有实例，避免每次评估都创建新 LLM 连接。
    """
    from app.rag.prompt_builder import build_rag_prompt
    from app.rag.retriever import retriever

    # Retrieve relevant chunks
    # Task 9: 使用 settings.RETRIEVAL_TOP_K 保持评估与生产一致，避免评估结果系统性偏低
    chunks = await retriever.retrieve(query, kb_id, top_k=settings.RETRIEVAL_TOP_K)
    contexts = [c.get("content", "") for c in chunks]

    if not contexts:
        return "无法获取相关内容来回答此问题。", []

    # Build prompt
    prompt = build_rag_prompt(query, chunks)

    # Generate answer — 复用传入的 LLM 实例，或按需创建
    if llm is None:
        from app.models.factory import ModelFactory
        llm = ModelFactory.create_llm()
    answer = await llm.chat(
        [{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    answer = answer or ""

    return answer, contexts
