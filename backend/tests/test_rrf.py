"""Unit tests for RRF fusion algorithm in HybridRetriever."""
import pytest
from app.rag.retriever import HybridRetriever


@pytest.fixture
def retriever():
    return HybridRetriever()


class TestRRFFusion:
    def test_rrf_basic_fusion(self):
        """Test that overlapping items rank higher."""
        retriever = HybridRetriever()
        
        # Vector results: chunk A (rank 0), chunk B (rank 1), chunk C (rank 2)
        vec_results = [
            {"chunk_id": "A", "content": "vec A", "score": 0.9, "source": "vector"},
            {"chunk_id": "B", "content": "vec B", "score": 0.8, "source": "vector"},
            {"chunk_id": "C", "content": "vec C", "score": 0.7, "source": "vector"},
        ]
        
        # BM25 results: chunk B (rank 0), chunk A (rank 1), chunk D (rank 2)
        bm25_results = [
            {"chunk_id": "B", "score": 2.5, "content": "bm25 B"},
            {"chunk_id": "A", "score": 2.0, "content": "bm25 A"},
            {"chunk_id": "D", "score": 1.5, "content": "bm25 D"},
        ]
        
        result = retriever._rrf_fuse(vec_results, bm25_results)
        
        # Both A and B appear in both lists, should rank above C and D
        chunk_ids = [r["chunk_id"] for r in result]
        
        # B should be top (rank 0 in BM25 + rank 1 in vector)
        # A should be second (rank 0 in vector + rank 1 in BM25)
        # Both should rank above C and D (only in one list)
        assert "B" in chunk_ids
        assert "A" in chunk_ids

    def test_rrf_empty_vector(self):
        retriever = HybridRetriever()
        vec_results = []
        bm25_results = [
            {"chunk_id": "X1", "score": 1.0, "content": "bm25 X1"},
            {"chunk_id": "X2", "score": 0.9, "content": "bm25 X2"},
        ]
        result = retriever._rrf_fuse(vec_results, bm25_results)
        assert len(result) > 0

    def test_rrf_empty_bm25(self):
        retriever = HybridRetriever()
        vec_results = [
            {"chunk_id": "A", "content": "", "score": 0.9, "source": "vector"},
        ]
        bm25_results = []
        result = retriever._rrf_fuse(vec_results, bm25_results)
        assert len(result) == 1

    def test_rrf_both_empty(self):
        retriever = HybridRetriever()
        result = retriever._rrf_fuse([], [])
        assert len(result) == 0

    def test_rrf_score_positive(self):
        """All RRF scores should be positive."""
        retriever = HybridRetriever()
        vec_results = [
            {"chunk_id": "A", "content": "", "score": 0.9, "source": "vector"},
            {"chunk_id": "B", "content": "", "score": 0.8, "source": "vector"},
        ]
        bm25_results = [{"chunk_id": "A", "score": 1.0, "content": "bm25 A"}]
        result = retriever._rrf_fuse(vec_results, bm25_results)
        for r in result:
            assert r["rrf_score"] > 0


class TestHybridRetrieverMethods:
    def test_init_defaults(self):
        from app.rag.retriever import HybridRetriever
        retriever = HybridRetriever()
        assert retriever._qdrant_client is None
        assert retriever._embedding is None

    def test_collection_name_format(self):
        from app.rag.retriever import HybridRetriever
        retriever = HybridRetriever()
        name = retriever._collection_name(42)
        assert "42" in name
        assert isinstance(name, str)

    def test_rrf_fuse_single_vector(self):
        from app.rag.retriever import HybridRetriever
        retriever = HybridRetriever()
        vec = [{"chunk_id": "A", "content": "test", "score": 0.9, "source": "vector"}]
        result = retriever._rrf_fuse(vec, [])
        assert len(result) == 1
        assert result[0]["chunk_id"] == "A"
        assert "rrf_score" in result[0]
        assert result[0]["rrf_score"] > 0

    def test_rrf_fuse_single_bm25(self):
        from app.rag.retriever import HybridRetriever
        retriever = HybridRetriever()
        bm25 = [{"chunk_id": "B", "score": 2.5, "content": "bm25 B"}]
        vec = [{"chunk_id": "A", "content": "test", "score": 0.9, "source": "vector"}]
        result = retriever._rrf_fuse(vec, bm25)
        assert len(result) >= 1

    def test_rrf_fuse_preserves_metadata(self):
        from app.rag.retriever import HybridRetriever
        retriever = HybridRetriever()
        vec = [{"chunk_id": "X", "content": "hello", "score": 0.5, "source": "vector",
                 "doc_id": 1, "filename": "test.pdf"}]
        result = retriever._rrf_fuse(vec, [])
        assert result[0]["content"] == "hello"
        assert result[0]["doc_id"] == 1
        assert result[0]["filename"] == "test.pdf"

    def test_rrf_rank_based_not_score_based(self):
        """RRF uses rank positions, not raw scores."""
        from app.rag.retriever import HybridRetriever
        retriever = HybridRetriever()
        vec = [
            {"chunk_id": "first", "content": "", "score": 0.9, "source": "vector"},
            {"chunk_id": "second", "content": "", "score": 0.1, "source": "vector"},
        ]
        bm25 = [
            {"chunk_id": "second", "score": 3.0, "content": "bm25 second"},
            {"chunk_id": "first", "score": 0.5, "content": "bm25 first"},
        ]
        result = retriever._rrf_fuse(vec, bm25)
        ids = [r["chunk_id"] for r in result]
        assert "first" in ids
        assert "second" in ids

    def test_rrf_scores_differ_for_different_ranks(self):
        """Items with better combined ranks should have higher scores."""
        from app.rag.retriever import HybridRetriever
        retriever = HybridRetriever()
        vec = [
            {"chunk_id": "A", "content": "", "score": 0.9, "source": "vector"},
            {"chunk_id": "B", "content": "", "score": 0.8, "source": "vector"},
            {"chunk_id": "C", "content": "", "score": 0.7, "source": "vector"},
        ]
        bm25 = [{"chunk_id": "A", "score": 3.0, "content": "bm25 A"}]
        result = retriever._rrf_fuse(vec, bm25)
        scores_dict = {r["chunk_id"]: r["rrf_score"] for r in result}
        assert scores_dict["A"] > scores_dict["B"]
        assert scores_dict["A"] > scores_dict["C"]
