from abc import ABC, abstractmethod


class BaseParser(ABC):
    """文档解析器抽象基类"""

    @abstractmethod
    def parse(self, file_path: str) -> str:
        """解析文档,返回纯文本"""
        ...

    @property
    @abstractmethod
    def supported_extensions(self) -> list[str]:
        """支持的文件扩展名"""
        ...
