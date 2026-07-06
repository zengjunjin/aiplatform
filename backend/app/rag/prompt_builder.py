SYSTEM_PROMPT = """你是知识库问答助手。根据以下文档片段回答问题,并在引用处标注 [n](n 为文档序号)。
【回答要求】
1. 仅依据提供的文档片段回答,不要编造信息
2. 引用文档时在句末标注 [1]、[2] 等序号
3. 如果文档中没有相关信息,如实回答"根据现有文档,我无法回答这个问题"
4. 末尾不要列出参考来源,系统会自动生成。
5. 回答要简洁、准确、有条理
"""


def build_rag_prompt(query: str, chunks: list[dict]) -> str:
    '''构造带引用标记的 RAG prompt'''
    parts = ["【文档片段】"]
    for i, chunk in enumerate(chunks, 1):
        filename = chunk.get("filename", "未知文档")
        page = chunk.get("page")
        page_info = f" 第{page}页" if page else ""
        content = chunk.get("content", "")
        parts.append(f"\n[{i}] 【{filename}】{page_info}")
        parts.append(f"内容:{content}")
    parts.append(f"\n\n【用户问题】\n{query}")
    return "\n".join(parts)


def build_context_messages(
    system_prompt: str,
    rag_context: str,
    history: list[dict],
    current_query: str,
    summary: str | None = None,
) -> list[dict]:
    '''构造完整的 messages 列表'''
    messages = [{"role": "system", "content": system_prompt}]
    if summary:
        messages.append({"role": "system", "content": f"【对话历史摘要】\n{summary}"})
    messages.append({"role": "system", "content": rag_context})
    messages.extend(history)
    messages.append({"role": "user", "content": current_query})
    return messages