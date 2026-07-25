"""LLM 查询重写与扩展。

- rewrite_query: 消解多轮对话中的代词，将最新问题重写为独立完整问题
- expand_query: 生成多个语义相同的查询变体，提升检索召回率
- retrieve_with_expansion: 并行检索多个变体并合并去重

所有 LLM 调用均有 fallback：失败时返回原 query，避免阻断主流程。
"""

import asyncio

from loguru import logger

# 触发重写的代词/指代词（简单启发式）
_PRONOUNS = ("它", "他", "她", "这个", "那个", "上面", "之前")


async def rewrite_query(query: str, history: list[dict]) -> str:
    """根据对话历史将用户最新问题重写为独立的、无代词的完整问题。

    history 格式: [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]
    - history 为空或最近 3 轮无代词时直接返回原 query
    - LLM 调用失败时返回原 query（fallback）
    """
    # history 为空直接返回
    if not history:
        return query

    # 启发式：取最近 3 轮历史 + 当前 query，若无代词则跳过 LLM 调用
    recent = history[-3:] if len(history) > 3 else history
    recent_text = " ".join(m.get("content", "") for m in recent if isinstance(m, dict))
    combined = recent_text + " " + query
    if not any(p in combined for p in _PRONOUNS):
        return query

    try:
        from app.models.factory import ModelFactory

        llm = ModelFactory.create_llm()
        history_text = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}"
            for m in history
            if isinstance(m, dict)
        )
        prompt = (
            "你是一个查询重写助手。根据对话历史，将用户的最新问题重写为独立的、无代词的完整问题。\n\n"
            f"对话历史：\n{history_text}\n\n"
            f"最新问题：{query}\n\n"
            "重写后的独立问题（直接输出问题，不要解释）："
        )
        response = await llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        rewritten = (response or "").strip()
        return rewritten or query
    except Exception as e:
        logger.warning(f"Query rewrite failed, fallback to original: {e}")
        return query


async def expand_query(query: str) -> list[str]:
    """为原问题生成 3 个语义相同但表述不同的变体。

    返回 [query, p1, p2, p3]（去重，最多 4 个元素）。
    LLM 失败时返回 [query]（仅原 query）。
    """
    try:
        from app.models.factory import ModelFactory

        llm = ModelFactory.create_llm()
        prompt = (
            "你是一个查询扩展助手。请为以下问题生成 3 个语义相同但表述不同的变体，用于提升检索召回率。\n\n"
            f"原问题：{query}\n\n"
            "输出 3 个变体，每行一个，不要编号："
        )
        response = await llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        if not response:
            return [query]

        # 按行分割，过滤空行，最多取 3 个
        variants = [line.strip() for line in response.splitlines()]
        variants = [v for v in variants if v][:3]

        # 包含原 query，去重（保序）
        result = [query]
        for v in variants:
            if v not in result:
                result.append(v)
        return result
    except Exception as e:
        logger.warning(f"Query expansion failed, fallback to original: {e}")
        return [query]


async def retrieve_with_expansion(query: str, kb_id: int, top_k: int = 10, **kwargs) -> list:
    """查询扩展检索：生成多个变体并行检索，合并去重后按 score 排序取 top_k。

    返回去重排序后的 chunks 列表（与 retriever.retrieve 返回格式一致）。
    """
    from app.rag.retriever import retriever

    variants = await expand_query(query)

    # 并行检索所有变体（单个失败不影响其他）
    results = await asyncio.gather(
        *[retriever.retrieve(v, kb_id, top_k=top_k) for v in variants],
        return_exceptions=True,
    )

    # 合并结果，基于 chunk_id 去重（保留最高分）
    best: dict = {}  # chunk_id -> (score, chunk)
    for result in results:
        if isinstance(result, Exception):
            logger.warning(f"Retrieve variant failed: {result}")
            continue
        for chunk in result:
            cid = chunk.get("chunk_id")
            if cid is None:
                continue
            # 优先用 rrf_score（融合分数），回退 score
            score = chunk.get("rrf_score")
            if score is None:
                score = chunk.get("score", 0)
            if cid not in best or score > best[cid][0]:
                best[cid] = (score, chunk)

    # 按 score 降序排序，取 top_k
    merged = [chunk for _, chunk in sorted(best.values(), key=lambda x: x[0], reverse=True)]
    return merged[:top_k]
