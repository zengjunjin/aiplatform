import re
from app.parsers.base import BaseParser


class MarkdownParser(BaseParser):
    def parse(self, file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content

    @property
    def supported_extensions(self) -> list[str]:
        return [".md", ".markdown"]