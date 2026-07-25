"""Unit tests for parsers.chunker module."""

from app.parsers.chunker import TextChunker, chunker


class TestTextChunker:
    def test_short_text_single_chunk(self):
        """Short text should produce a single chunk."""
        text = "Hello world, this is a short text."
        c = TextChunker(chunk_size=500, overlap=50)
        chunks = c.chunk(text)
        assert len(chunks) == 1
        assert isinstance(chunks[0], dict)
        assert "content" in chunks[0]
        assert chunks[0]["content"] == text

    def test_long_text_multiple_chunks(self):
        """Long text should be split into multiple chunks."""
        text = "Word " * 200  # 1000 chars
        c = TextChunker(chunk_size=200, overlap=20)
        chunks = c.chunk(text)
        assert len(chunks) > 1

    def test_overlap_between_chunks(self):
        """Adjacent chunks should have overlap."""
        text = "ABCDEFGHIJ" * 20  # 200 chars
        c = TextChunker(chunk_size=80, overlap=20)
        chunks = c.chunk(text)
        assert len(chunks) >= 2
        end_of_first = chunks[0]["content"][-10:]
        assert end_of_first in chunks[1]["content"]

    def test_chunk_size_limit(self):
        """No chunk should be much larger than chunk_size."""
        text = "Test content. " * 100
        chunk_size = 100
        c = TextChunker(chunk_size=chunk_size, overlap=20)
        chunks = c.chunk(text)
        for chunk in chunks:
            assert len(chunk["content"]) <= chunk_size * 1.5

    def test_empty_text(self):
        c = TextChunker(chunk_size=100, overlap=10)
        chunks = c.chunk("")
        assert len(chunks) == 0

    def test_preserves_content(self):
        """First and last content should be preserved."""
        text = "The quick brown fox jumps over the lazy dog. " * 20
        c = TextChunker(chunk_size=80, overlap=20)
        chunks = c.chunk(text)
        assert text[:50] in chunks[0]["content"]
        assert text[-50:].strip() in chunks[-1]["content"]

    def test_default_instance_exists(self):
        """The module-level chunker instance should exist."""
        assert chunker is not None
        result = chunker.chunk("Hello world")
        assert isinstance(result, list)

    def test_paragraph_splitting(self):
        """Text with multiple paragraphs should be handled."""
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        c = TextChunker(chunk_size=500, overlap=0)
        chunks = c.chunk(text)
        assert len(chunks) >= 1
        assert "First" in chunks[0]["content"]

    def test_chunk_has_char_count(self):
        c = TextChunker()
        chunks = c.chunk("Hello world")
        assert "char_count" in chunks[0]
        assert chunks[0]["char_count"] > 0
