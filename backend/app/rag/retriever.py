"""Hybrid retrieval: BM25 + vector + RRF fusion."""
import logging
from typing import Optional
from app.models.factory import ModelFactory
from app.rag.bm25 import bm25_store
from app.config import settings
from app.core.metrics import RAG_RETRIEVAL_TOTAL
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue

logger = logging.getLogger(__name__)


class HybridRetriever:
    """BM25 + vector retrieval + RRF fusion."""

    def __init__(self):
        self._qdrant_client: Optional[QdrantClient] = None
        self._embedding = None

    @property
    def qdrant(self):
        if self._qdrant_client is None:
            self._qdrant_client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
            )
        return self._qdrant_client

    @property
    def embedding(self):
        if self._embedding is None:
            self._embedding = ModelFactory.create_embedding()
        return self._embedding

    def _collection_name(self, kb_id: int) -> str:
        return f"chunks_kb_{kb_id}"

    def _ensure_collection(self, kb_id: int):
        """Ensure collection exists, create if not."""
        name = self._collection_name(kb_id)
        try:
            self.qdrant.get_collection(name)
        except Exception:
            self.qdrant.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=settings.EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )

    async def retrieve(self, query: str, kb_id: int,
                       top_k: int = 10) -> list[dict]:
        """Run hybrid retrieval and return fused top-k chunks."""
        RAG_RETRIEVAL_TOTAL.labels(kb_id=str(kb_id)).inc()
        vec_results = await self._vector_search(query, kb_id, top_k * 2)
        # Bug 4: Load chunks from DB for BM25 context enrichment,
        # otherwise bm25_store.search returns empty content.
        chunks_for_bm25 = await self._load_chunks_for_bm25(kb_id)
        bm25_results = await bm25_store.search(
            kb_id, query, top_k * 2, chunks=chunks_for_bm25
        )
        merged = self._rrf_fuse(vec_results, bm25_results)
        return merged[:top_k]

    async def _load_chunks_for_bm25(self, kb_id: int) -> list[dict]:
        """Load all chunks of a KB from DB for BM25 search.

        Bug 4: bm25_store.search needs the original chunks list to map
        ranked indices back to chunk_id / content. Without this, the
        BM25 path returns chunks with empty content.
        """
        try:
            from app.database import async_session
            from sqlalchemy import text
            async with async_session() as session:
                result = await session.execute(
                    text(
                        "SELECT id as chunk_id, doc_id, content, chunk_index "
                        "FROM document_chunks "
                        "WHERE doc_id IN (SELECT id FROM documents WHERE kb_id = :kb_id) "
                        "ORDER BY id"
                    ),
                    {"kb_id": kb_id},
                )
                rows = result.fetchall()
                return [
                    {
                        "chunk_id": r[0],
                        "doc_id": r[1],
                        "content": r[2],
                        "chunk_index": r[3],
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.warning("_load_chunks_for_bm25 failed: %s", e)
            return []

    async def _vector_search(self, query: str, kb_id: int,
                             top_k: int) -> list[dict]:
        try:
            query_vec = await self.embedding.embed([query])
            self._ensure_collection(kb_id)
            # Bug 2: qdrant-client >= 1.10 removed .search(); use .query_points().
            response = self.qdrant.query_points(
                collection_name=self._collection_name(kb_id),
                query=query_vec[0],
                limit=top_k,
                with_payload=True,
            )
            chunks = []
            for point in response.points:
                payload = point.payload or {}
                chunks.append({
                    "chunk_id": payload.get("chunk_id", point.id),
                    "doc_id": payload.get("doc_id"),
                    "kb_id": payload.get("kb_id", kb_id),
                    "filename": payload.get("filename", ""),
                    "content": payload.get("content", ""),
                    "page": payload.get("page"),
                    "score": point.score,
                    "source": "vector",
                })
            return chunks
        except Exception as e:
            logger.warning("vector search failed: %s", e)
            return []

    async def add_chunks(self, kb_id: int, chunks: list[dict], vectors: list[list[float]]):
        """Add chunks to Qdrant collection."""
        self._ensure_collection(kb_id)
        points = []
        for i, (chunk, vec) in enumerate(zip(chunks, vectors)):
            point_id = chunk.get("chunk_id") or chunk.get("id") or i + 1
            points.append(PointStruct(
                id=point_id,
                vector=vec,
                payload={
                    "chunk_id": point_id,
                    "doc_id": chunk.get("doc_id"),
                    "kb_id": kb_id,
                    "filename": chunk.get("filename", ""),
                    "content": chunk.get("content", ""),
                    "chunk_index": chunk.get("chunk_index", i),
                    "file_type": chunk.get("file_type", ""),
                    "page": chunk.get("page"),
                },
            ))
        self.qdrant.upsert(
            collection_name=self._collection_name(kb_id),
            points=points,
        )

    def delete_by_doc_id(self, kb_id: int, doc_id: int):
        """Delete all chunks for a document."""
        try:
            self.qdrant.delete(
                collection_name=self._collection_name(kb_id),
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="doc_id",
                            match=MatchValue(value=doc_id),
                        ),
                    ],
                ),
            )
        except Exception as e:
            logger.warning("delete_by_doc_id failed: %s", e)

    def delete_collection(self, kb_id: int):
        """Delete entire collection for a knowledge base."""
        try:
            self.qdrant.delete_collection(self._collection_name(kb_id))
        except Exception as e:
            print(f"[WARN] delete_collection failed: {e}")

    def _rrf_fuse(self, vec_results: list[dict],
                  bm25_results: list[dict], k: int = 60) -> list[dict]:
        """Reciprocal Rank Fusion.

        Both vec_results and bm25_results are lists of dicts with 'chunk_id' key.
        Score = sum of 1/(k + rank + 1) for each list.
        """
        rrf_scores = {}
        chunk_map = {}

        # Vector results
        for rank, r in enumerate(vec_results):
            cid = r["chunk_id"]
            rrf_scores[cid] = rrf_scores.get(cid, 0) + 1 / (k + rank + 1)
            if cid not in chunk_map:
                chunk_map[cid] = dict(r)

        # BM25 results (now dicts, not tuples)
        for rank, r in enumerate(bm25_results):
            cid = r.get("chunk_id")
            if cid is None:
                continue
            rrf_scores[cid] = rrf_scores.get(cid, 0) + 1 / (k + rank + 1)
            if cid not in chunk_map:
                chunk_map[cid] = {
                    "chunk_id": cid,
                    "doc_id": r.get("doc_id"),
                    "filename": r.get("filename", ""),
                    "content": r.get("content", ""),
                    "page": r.get("page"),
                    "score": r.get("score", 0),
                    "source": "bm25",
                }

        sorted_ids = sorted(rrf_scores, key=rrf_scores.get, reverse=True)
        result = []
        for cid in sorted_ids:
            chunk = dict(chunk_map.get(cid, {"chunk_id": cid}))
            chunk["rrf_score"] = rrf_scores[cid]
            result.append(chunk)
        return result


retriever = HybridRetriever()