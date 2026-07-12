"""Evaluation service: generate test datasets and run RAGAS evaluation."""
import json
import random
import asyncio
from typing import Any
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from app.db.document_chunk import DocumentChunk
from app.db.document import Document
from app.db.knowledge_base import KnowledgeBase
from app.db.evaluation import EvaluationRun, EvaluationResult, EvaluationStatus
from app.core.exceptions import NotFoundError


async def generate_test_dataset(
    kb_id: int,
    db: AsyncSession,
    num_questions: int = 50,
) -> list[dict]:
    """Generate a test dataset from knowledge base chunks.

    Randomly samples chunks from the KB, then uses the LLM to generate
    a question for each chunk. Returns a list of {question, ground_truth, contexts}.
    """
    # Verify KB exists
    kb_result = await db.execute(select(KnowledgeBase).where(KnowledgeBase.id == kb_id))
    kb = kb_result.scalar_one_or_none()
    if not kb:
        raise NotFoundError("Knowledge base not found")

    # Get all chunks for this KB
    chunk_result = await db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.kb_id == kb_id)
        .order_by(func.random())
        .limit(num_questions)
    )
    chunks = chunk_result.scalars().all()

    if not chunks:
        logger.warning(f"No chunks found for KB {kb_id}")
        return []

    # Sample up to num_questions chunks
    sample_chunks = chunks[:num_questions]

    # 并发生成问题（Semaphore 限制并发度，避免打爆 LLM 服务）
    sem = asyncio.Semaphore(8)

    async def _gen(chunk):
        async with sem:
            return await _generate_question_from_chunk(chunk.content)

    questions = await asyncio.gather(*[_gen(c) for c in sample_chunks], return_exceptions=True)

    dataset = []
    for chunk, question in zip(sample_chunks, questions):
        if isinstance(question, Exception) or not question:
            continue
        dataset.append({
            "question": question,
            "ground_truth": chunk.content,
            "contexts": [chunk.content],
        })

    logger.info(f"Generated {len(dataset)} questions for KB {kb_id}")
    return dataset


async def _generate_question_from_chunk(chunk_content: str) -> str | None:
    """Use LLM to generate a question that can be answered by the chunk."""
    try:
        from app.models.factory import ModelFactory
        llm = ModelFactory.create_llm()

        prompt = (
            "你是一个问答数据集生成助手。请根据以下文本内容，生成一个可以用该文本回答的问题。\n\n"
            "规则：\n"
            "1. 问题应该具体、明确，答案可以直接从文本中找到\n"
            "2. 只返回问题本身，不要添加任何其他内容\n"
            "3. 问题应该用中文\n\n"
            f"文本内容：\n{chunk_content[:1500]}\n\n"
            "问题："
        )

        # Use non-streaming generation
        response = await llm.generate(prompt)
        question = response.strip()

        # Sanitize: remove common prefixes that LLMs might add
        for prefix in ["问题：", "Question:", "Q:", "问："]:
            if question.startswith(prefix):
                question = question[len(prefix):].strip()

        if len(question) < 5:
            return None

        return question
    except Exception as e:
        logger.warning(f"Failed to generate question from chunk: {e}")
        return None


async def get_rag_answer(query: str, kb_id: int) -> tuple[str, list[str]]:
    """Run the RAG pipeline to get an answer and retrieved contexts."""
    try:
        from app.rag.retriever import retriever
        from app.rag.prompt_builder import build_rag_prompt
        from app.models.factory import ModelFactory

        # Retrieve relevant chunks
        chunks = await retriever.retrieve(query, kb_id, top_k=5)
        contexts = [c.get("content", "") for c in chunks]

        if not contexts:
            return "无法获取相关内容来回答此问题。", []

        # Build prompt
        prompt = build_rag_prompt(query, chunks)

        # Generate answer
        llm = ModelFactory.create_llm()
        answer = await llm.generate(prompt)

        return answer, contexts

    except Exception as e:
        logger.error(f"RAG pipeline error for query '{query[:50]}...': {e}")
        return f"生成回答时出错: {str(e)}", []