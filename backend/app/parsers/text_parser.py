from typing import Optional
from app.parsers.base import BaseParser


class TextParser(BaseParser):
    def parse(self, file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()

    @property
    def supported_extensions(self) -> list[str]:
        return [".txt"]