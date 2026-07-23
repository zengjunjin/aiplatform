from app.parsers.base import BaseParser


class PDFParser(BaseParser):
    def parse(self, file_path: str) -> str:
        import pdfplumber
        pages = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                if text.strip():
                    pages.append(f"--- 第 {i+1} 页 ---\n{text}")
        return "\n\n".join(pages)

    @property
    def supported_extensions(self) -> list[str]:
        return [".pdf"]
