"""Tests for app.parsers module (document parsers)"""

import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.parsers.base import BaseParser
from app.parsers.docx_parser import DocxParser
from app.parsers.markdown_parser import MarkdownParser
from app.parsers.pdf_parser import PDFParser
from app.parsers.text_parser import TextParser

# ========== BaseParser ==========


class _ConcreteParser(BaseParser):
    def parse(self, file_path: str) -> str:
        return "test"

    @property
    def supported_extensions(self) -> list[str]:
        return [".test"]


class TestBaseParser:
    def test_base_parser_is_abstract(self):
        with pytest.raises(TypeError):
            BaseParser()

    def test_concrete_parser_implements_parse(self):
        p = _ConcreteParser()
        assert p.parse("/fake/path") == "test"

    def test_concrete_parser_implements_supported_extensions(self):
        p = _ConcreteParser()
        assert p.supported_extensions == [".test"]


# ========== TextParser ==========


class TestTextParser:
    def test_parse_reads_file_content(self):
        p = TextParser()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("Hello world\nLine 2")
            path = f.name
        try:
            result = p.parse(path)
            assert result == "Hello world\nLine 2"
        finally:
            os.unlink(path)

    def test_parse_empty_file(self):
        p = TextParser()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("")
            path = f.name
        try:
            result = p.parse(path)
            assert result == ""
        finally:
            os.unlink(path)

    def test_parse_unicode_content(self):
        p = TextParser()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("你好世界")
            path = f.name
        try:
            result = p.parse(path)
            assert result == "你好世界"
        finally:
            os.unlink(path)

    def test_supported_extensions(self):
        p = TextParser()
        assert ".txt" in p.supported_extensions
        assert len(p.supported_extensions) == 1

    def test_parse_file_not_found_raises(self):
        p = TextParser()
        with pytest.raises(FileNotFoundError):
            p.parse("/nonexistent/file.txt")


# ========== MarkdownParser ==========


class TestMarkdownParser:
    def test_parse_reads_markdown_content(self):
        p = MarkdownParser()
        md_content = "# Title\n\nSome **bold** text.\n\n- item 1\n- item 2"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(md_content)
            path = f.name
        try:
            result = p.parse(path)
            assert result == md_content
            assert "# Title" in result
            assert "**bold**" in result
        finally:
            os.unlink(path)

    def test_parse_empty_markdown(self):
        p = MarkdownParser()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("")
            path = f.name
        try:
            result = p.parse(path)
            assert result == ""
        finally:
            os.unlink(path)

    def test_supported_extensions(self):
        p = MarkdownParser()
        assert ".md" in p.supported_extensions
        assert ".markdown" in p.supported_extensions
        assert len(p.supported_extensions) == 2

    def test_parse_unicode_markdown(self):
        p = MarkdownParser()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("# 标题\n\n中文内容")
            path = f.name
        try:
            result = p.parse(path)
            assert "# 标题" in result
            assert "中文内容" in result
        finally:
            os.unlink(path)

    def test_parse_file_not_found_raises(self):
        p = MarkdownParser()
        with pytest.raises(FileNotFoundError):
            p.parse("/nonexistent/file.md")


# ========== DocxParser ==========


class TestDocxParser:
    def test_parse_extracts_paragraphs(self):
        p = DocxParser()
        fake_doc = MagicMock()
        fake_doc.paragraphs = [
            MagicMock(text="Hello"),
            MagicMock(text="   "),
            MagicMock(text="World"),
            MagicMock(text=""),
        ]
        mock_docx = MagicMock()
        mock_docx.Document.return_value = fake_doc
        with patch.dict(sys.modules, {"docx": mock_docx}):
            result = p.parse("/fake/path.docx")
        assert result == "Hello\n\nWorld"

    def test_parse_all_empty_paragraphs_returns_empty(self):
        p = DocxParser()
        fake_doc = MagicMock()
        fake_doc.paragraphs = [
            MagicMock(text=""),
            MagicMock(text="   "),
            MagicMock(text="\n"),
        ]
        mock_docx = MagicMock()
        mock_docx.Document.return_value = fake_doc
        with patch.dict(sys.modules, {"docx": mock_docx}):
            result = p.parse("/fake/path.docx")
        assert result == ""

    def test_parse_single_paragraph(self):
        p = DocxParser()
        fake_doc = MagicMock()
        fake_doc.paragraphs = [MagicMock(text="Single paragraph")]
        mock_docx = MagicMock()
        mock_docx.Document.return_value = fake_doc
        with patch.dict(sys.modules, {"docx": mock_docx}):
            result = p.parse("/fake/path.docx")
        assert result == "Single paragraph"

    def test_supported_extensions(self):
        p = DocxParser()
        assert ".docx" in p.supported_extensions
        assert len(p.supported_extensions) == 1

    def test_parse_document_call(self):
        p = DocxParser()
        fake_doc = MagicMock()
        fake_doc.paragraphs = []
        mock_docx = MagicMock()
        mock_docx.Document.return_value = fake_doc
        with patch.dict(sys.modules, {"docx": mock_docx}):
            p.parse("/test/path.docx")
        mock_docx.Document.assert_called_once_with("/test/path.docx")


# ========== PDFParser ==========


class TestPDFParser:
    def _make_fake_page(self, text):
        page = MagicMock()
        page.extract_text.return_value = text
        return page

    def _make_fake_pdf(self, pages):
        fake_pdf = MagicMock()
        fake_pdf.pages = pages
        fake_pdf.__enter__ = MagicMock(return_value=fake_pdf)
        fake_pdf.__exit__ = MagicMock(return_value=False)
        return fake_pdf

    def test_parse_extracts_text_from_pages(self):
        p = PDFParser()
        fake_pdf = self._make_fake_pdf(
            [
                self._make_fake_page("Page 1 content"),
                self._make_fake_page("Page 2 content"),
            ]
        )
        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = fake_pdf
        with patch.dict(sys.modules, {"pdfplumber": mock_pdfplumber}):
            result = p.parse("/fake/path.pdf")
        assert "Page 1 content" in result
        assert "Page 2 content" in result
        assert "第 1 页" in result
        assert "第 2 页" in result

    def test_parse_empty_pages_skipped(self):
        p = PDFParser()
        fake_pdf = self._make_fake_pdf(
            [
                self._make_fake_page(""),
                self._make_fake_page("   "),
                self._make_fake_page("Real content"),
            ]
        )
        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = fake_pdf
        with patch.dict(sys.modules, {"pdfplumber": mock_pdfplumber}):
            result = p.parse("/fake/path.pdf")
        assert "Real content" in result
        assert "第 3 页" in result

    def test_parse_all_empty_returns_empty(self):
        p = PDFParser()
        fake_pdf = self._make_fake_pdf(
            [
                self._make_fake_page(""),
                self._make_fake_page(None),
            ]
        )
        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = fake_pdf
        with patch.dict(sys.modules, {"pdfplumber": mock_pdfplumber}):
            result = p.parse("/fake/path.pdf")
        assert result == ""

    def test_parse_none_text_handled(self):
        p = PDFParser()
        fake_pdf = self._make_fake_pdf(
            [
                self._make_fake_page(None),
                self._make_fake_page("Valid text"),
            ]
        )
        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = fake_pdf
        with patch.dict(sys.modules, {"pdfplumber": mock_pdfplumber}):
            result = p.parse("/fake/path.pdf")
        assert "Valid text" in result
        assert "第 2 页" in result

    def test_supported_extensions(self):
        p = PDFParser()
        assert ".pdf" in p.supported_extensions
        assert len(p.supported_extensions) == 1

    def test_parse_pdfplumber_open_call(self):
        p = PDFParser()
        fake_pdf = self._make_fake_pdf([])
        mock_pdfplumber = MagicMock()
        mock_pdfplumber.open.return_value = fake_pdf
        with patch.dict(sys.modules, {"pdfplumber": mock_pdfplumber}):
            p.parse("/test/file.pdf")
        mock_pdfplumber.open.assert_called_once_with("/test/file.pdf")
