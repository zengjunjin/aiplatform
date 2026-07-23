from app.parsers.base import BaseParser


class DocxParser(BaseParser):
    def parse(self, file_path: str) -> str:
        from docx import Document
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)

    @property
    def supported_extensions(self) -> list[str]:
        return [".docx"]
