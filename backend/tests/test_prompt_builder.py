"""Unit tests for rag.prompt_builder module."""
import pytest
from app.rag.prompt_builder import build_rag_prompt, build_context_messages, SYSTEM_PROMPT


SAMPLE_CHUNKS = [
    {"chunk_id": 1, "doc_id": 10, "filename": "manual.pdf", "content": "Warranty is 24 months."},
    {"chunk_id": 2, "doc_id": 20, "filename": "terms.docx", "content": "Service requires receipt."},
]


class TestBuildRagPrompt:
    def test_contains_document_markers(self):
        prompt = build_rag_prompt("What is warranty?", SAMPLE_CHUNKS)
        assert "【文档片段】" in prompt

    def test_contains_citation_numbers(self):
        prompt = build_rag_prompt("Question", SAMPLE_CHUNKS)
        assert "[1]" in prompt
        assert "[2]" in prompt

    def test_contains_filenames(self):
        prompt = build_rag_prompt("Q", SAMPLE_CHUNKS)
        assert "manual.pdf" in prompt
        assert "terms.docx" in prompt

    def test_contains_user_question(self):
        question = "What is the answer?"
        prompt = build_rag_prompt(question, SAMPLE_CHUNKS)
        assert "【用户问题】" in prompt
        assert question in prompt

    def test_empty_chunks(self):
        prompt = build_rag_prompt("Question", [])
        assert "【文档片段】" in prompt
        assert "Question" in prompt

    def test_chunk_content_present(self):
        prompt = build_rag_prompt("Q", SAMPLE_CHUNKS)
        assert "Warranty is 24 months." in prompt
        assert "Service requires receipt." in prompt


class TestBuildContextMessages:
    def test_returns_list(self):
        msgs = build_context_messages(SYSTEM_PROMPT, "context", [], "query")
        assert isinstance(msgs, list)
        assert len(msgs) >= 3  # system + context + user

    def test_system_message_first(self):
        msgs = build_context_messages(SYSTEM_PROMPT, "ctx", [], "q")
        assert msgs[0]["role"] == "system"
        assert SYSTEM_PROMPT in msgs[0]["content"]

    def test_user_query_last(self):
        msgs = build_context_messages(SYSTEM_PROMPT, "ctx", [], "my question")
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "my question"

    def test_history_included(self):
        history = [
            {"role": "user", "content": "Hi"},
            {"role": "assistant", "content": "Hello"},
        ]
        msgs = build_context_messages(SYSTEM_PROMPT, "ctx", history, "q")
        assert len(msgs) == 5  # system + context + 2 history + user

    def test_summary_included(self):
        msgs = build_context_messages(SYSTEM_PROMPT, "ctx", [], "q", summary="Old convo summary")
        assert msgs[1]["role"] == "system"
        assert "Old convo summary" in msgs[1]["content"]
