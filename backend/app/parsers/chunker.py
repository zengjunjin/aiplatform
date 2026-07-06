import re
from typing import Optional
from app.config import settings


class TextChunker:
    '''文本分块器:按段落 + 字符数分块'''

    def __init__(self, chunk_size: int | None = None, overlap: int | None = None):
        self.chunk_size = chunk_size or settings.CHUNK_SIZE
        self.overlap = overlap or settings.CHUNK_OVERLAP

    def _clean_text(self, text: str) -> str:
        '''清洗文本: 去除 NUL 字符和其他不可见控制字符(保留换行、制表符)'''
        # 移除 NUL 字符 (PostgreSQL 不允许)
        text = text.replace("\x00", "")
        # 移除其他不可见控制字符 (保留 \n \t \r)
        text = re.sub(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
        return text

    def chunk(self, text: str, source_pages: list[dict] | None = None) -> list[dict]:
        '''分块,返回 [{"content": "...", "page": n, "char_count": ...}, ...]'''
        text = self._clean_text(text)
        # 1. 按双换行(段落)分割
        paragraphs = re.split(r"\n\s*\n", text)
        paragraphs = [p.strip() for p in paragraphs if p.strip()]

        # 2. 合并小段落,拆分大段落
        chunks = []
        buffer = ""
        buffer_start_page = None

        for para in paragraphs:
            # 尝试提取页码标记
            page_match = re.match(r"--- 第(\d+) 页 ---", para)
            current_page = int(page_match.group(1)) if page_match else None

            if buffer and len(buffer) + len(para) > self.chunk_size:
                chunks.append(self._make_chunk(buffer, buffer_start_page))
                # overlap: 保留尾部
                if self.overlap > 0:
                    buffer = buffer[-self.overlap:] + "\n\n" + para
                else:
                    buffer = para
                buffer_start_page = current_page
            else:
                if not buffer:
                    buffer_start_page = current_page
                buffer = (buffer + "\n\n" + para) if buffer else para

            # 如果单个段落超过 chunk_size,强制拆分
            while len(buffer) > self.chunk_size * 1.5:
                split_pos = self._find_split_pos(buffer, self.chunk_size)
                chunks.append(self._make_chunk(buffer[:split_pos], buffer_start_page))
                buffer = buffer[max(split_pos - self.overlap, 0):]

        if buffer.strip():
            chunks.append(self._make_chunk(buffer, buffer_start_page))

        return chunks

    def _make_chunk(self, content: str, page: int | None) -> dict:
        return {
            "content": content.strip(),
            "page": page,
            "char_count": len(content.strip()),
        }

    def _find_split_pos(self, text: str, target: int) -> int:
        '''在 target 附近找最近的句子边界'''
        for i in range(min(target, len(text)), max(0, target - 100), -1):
            if text[i] in "。?!;\n":
                return i + 1
        return target


chunker = TextChunker()
