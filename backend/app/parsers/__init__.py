import os

from app.parsers.base import BaseParser
from app.parsers.chunker import TextChunker, chunker
from app.parsers.docx_parser import DocxParser
from app.parsers.markdown_parser import MarkdownParser
from app.parsers.pdf_parser import PDFParser
from app.parsers.text_parser import TextParser


def get_parser(file_path: str) -> BaseParser | None:
    """根据文件扩展名返回对应的解析器"""
    ext = os.path.splitext(file_path)[1].lower()
    parsers = [PDFParser(), DocxParser(), MarkdownParser(), TextParser()]
    for p in parsers:
        if ext in p.supported_extensions:
            return p
    return None


__all__ = [
    "BaseParser",
    "TextParser",
    "MarkdownParser",
    "PDFParser",
    "DocxParser",
    "TextChunker",
    "chunker",
    "get_parser",
]
