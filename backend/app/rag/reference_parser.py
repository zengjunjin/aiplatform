import re

CITATION_PATTERN = re.compile(r"\[(\d+)\]")


def parse_references(answer: str, cited_chunks: list[dict]) -> list[dict]:
    '''
    解析 LLM 输出中的引用标记 [n]
    cited_chunks: 检索到的 chunks(序号对应 prompt 中的 [n])
    '''
    matches = CITATION_PATTERN.findall(answer)
    cited_indices = set(int(m) for m in matches)

    references = []
    for idx in cited_indices:
        if 1 <= idx <= len(cited_chunks):
            chunk = cited_chunks[idx - 1]
            references.append({
                "chunk_id": chunk.get("chunk_id"),
                "doc_id": chunk.get("doc_id"),
                "filename": chunk.get("filename", ""),
                "page": chunk.get("page"),
                "snippet": chunk.get("content", "")[:200],
                "score": chunk.get("rerank_score", chunk.get("score", 0)),
            })
    return references


def strip_citations(text: str) -> str:
    '''移除引用标记,返回纯文本'''
    return CITATION_PATTERN.sub("", text)
