"""Plain-text-like parser base.

Markdown and plain-text files share the same parsing logic (read UTF-8
content as-is); only the supported extensions differ. This base class
extracts that shared logic so both parsers stay DRY without breaking
their existing public interfaces.
"""
from app.parsers.base import BaseParser


class TextLikeParser(BaseParser):
    """Base for parsers that read the file content as UTF-8 text unchanged."""

    _extensions: list[str] = []

    def parse(self, file_path: str) -> str:
        with open(file_path, encoding="utf-8") as f:
            return f.read()

    @property
    def supported_extensions(self) -> list[str]:
        return list(self._extensions)
