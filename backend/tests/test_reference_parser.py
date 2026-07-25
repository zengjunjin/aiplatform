"""Unit tests for rag.reference_parser module."""

from app.rag.reference_parser import parse_references, strip_citations

SAMPLE_CHUNKS = [
    {"chunk_id": 1, "doc_id": 10, "filename": "doc1.pdf", "content": "First chunk content here"},
    {"chunk_id": 2, "doc_id": 20, "filename": "doc2.md", "content": "Second chunk content here"},
    {"chunk_id": 3, "doc_id": 30, "filename": "doc3.docx", "content": "Third chunk content here"},
]


class TestParseReferences:
    def test_single_reference(self):
        result = parse_references("The answer is [1].", SAMPLE_CHUNKS)
        assert len(result) == 1
        assert result[0]["chunk_id"] == 1
        assert result[0]["filename"] == "doc1.pdf"

    def test_multiple_references(self):
        result = parse_references("See [1] and [2] for details.", SAMPLE_CHUNKS)
        assert len(result) == 2
        ids = [r["chunk_id"] for r in result]
        assert 1 in ids
        assert 2 in ids

    def test_no_references(self):
        result = parse_references("No citations here.", SAMPLE_CHUNKS)
        assert len(result) == 0

    def test_out_of_bounds_reference_ignored(self):
        result = parse_references("Refer to [99] which is out of range.", SAMPLE_CHUNKS)
        assert len(result) == 0  # [99] should be ignored

    def test_zero_reference_ignored(self):
        result = parse_references("Reference [0] is invalid.", SAMPLE_CHUNKS)
        assert len(result) == 0

    def test_duplicate_references_deduplicated(self):
        result = parse_references("[1] and [1] again.", SAMPLE_CHUNKS)
        assert len(result) == 1  # duplicates removed

    def test_reference_has_snippet(self):
        result = parse_references("Answer [1].", SAMPLE_CHUNKS)
        assert "snippet" in result[0]
        assert len(result[0]["snippet"]) > 0

    def test_empty_chunks(self):
        result = parse_references("[1]", [])
        assert len(result) == 0

    def test_empty_text(self):
        result = parse_references("", SAMPLE_CHUNKS)
        assert len(result) == 0


class TestStripCitations:
    def test_strip_single(self):
        result = strip_citations("Hello [1] world")
        assert result == "Hello  world"

    def test_strip_multiple(self):
        result = strip_citations("[1] [2] [3]")
        assert result == "  "

    def test_strip_none(self):
        result = strip_citations("No citations")
        assert result == "No citations"

    def test_strip_empty(self):
        result = strip_citations("")
        assert result == ""
