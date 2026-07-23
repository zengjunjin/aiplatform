from app.parsers.text_like_parser import TextLikeParser


class MarkdownParser(TextLikeParser):
    _extensions = [".md", ".markdown"]
