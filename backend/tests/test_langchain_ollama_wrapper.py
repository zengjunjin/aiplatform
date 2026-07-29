"""Unit tests for langchain_ollama_wrapper module (0% → 80%+ coverage)."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.models.langchain_ollama_wrapper import ChatOllama, OllamaEmbeddings


class TestChatOllama:
    """ChatOllama wrapper tests."""

    def test_llm_type(self):
        llm = ChatOllama()
        assert llm._llm_type == "ollama-chat"

    def test_init_defaults(self):
        llm = ChatOllama()
        assert llm.model == "qwen2.5:1.5b"
        assert llm.host == "http://ollama:11434"
        assert llm.temperature == 0.3

    def test_init_custom_params(self):
        llm = ChatOllama(model="qwen2.5:7b", host="http://localhost:11434")
        assert llm.model == "qwen2.5:7b"
        assert llm.host == "http://localhost:11434"

    def test_generate_converts_messages(self):
        """_generate should convert Langchain messages to Ollama format."""
        llm = ChatOllama()
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "Hello!"}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(llm._client, "post", return_value=mock_response) as mock_post:
            result = llm._generate([
                HumanMessage(content="Hi"),
                SystemMessage(content="You are helpful"),
            ])

            # Verify API call
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            payload = call_args[1]["json"]
            assert payload["model"] == "qwen2.5:1.5b"
            assert payload["stream"] is False
            messages = payload["messages"]
            assert messages[0]["role"] == "user"
            assert messages[0]["content"] == "Hi"
            assert messages[1]["role"] == "system"

            # Verify result
            assert len(result.generations) == 1
            gen = result.generations[0]
            assert isinstance(gen.message, AIMessage)
            assert gen.message.content == "Hello!"

    def test_generate_ai_message_role(self):
        """AI messages should map to 'assistant' role."""
        llm = ChatOllama()
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {"content": "response"}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(llm._client, "post", return_value=mock_response) as mock_post:
            from langchain_core.messages import AIMessage as AMsg
            llm._generate([HumanMessage(content="q"), AMsg(content="a")])
            payload = mock_post.call_args[1]["json"]
            assert payload["messages"][1]["role"] == "assistant"

    def test_generate_empty_content(self):
        """Empty response content should return empty AIMessage."""
        llm = ChatOllama()
        mock_response = MagicMock()
        mock_response.json.return_value = {"message": {}}
        mock_response.raise_for_status = MagicMock()

        with patch.object(llm._client, "post", return_value=mock_response):
            result = llm._generate([HumanMessage(content="test")])
            assert result.generations[0].message.content == ""


class TestOllamaEmbeddings:
    """OllamaEmbeddings wrapper tests."""

    def test_init_defaults(self):
        emb = OllamaEmbeddings()
        assert emb.model == "qwen2.5:1.5b"
        assert emb.host == "http://ollama:11434"

    def test_init_custom_params(self):
        emb = OllamaEmbeddings(model="nomic-embed", host="http://localhost:11434")
        assert emb.model == "nomic-embed"
        assert emb.host == "http://localhost:11434"

    def test_embed_query(self):
        """embed_query should return a single embedding vector."""
        emb = OllamaEmbeddings()
        mock_response = MagicMock()
        mock_response.json.return_value = {"embedding": [0.1, 0.2, 0.3]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(emb._client, "post", return_value=mock_response):
            result = emb.embed_query("test text")
            assert result == [0.1, 0.2, 0.3]

    def test_embed_documents(self):
        """embed_documents should return multiple embedding vectors."""
        emb = OllamaEmbeddings()
        mock_response1 = MagicMock()
        mock_response1.json.return_value = {"embedding": [0.1, 0.2]}
        mock_response1.raise_for_status = MagicMock()
        mock_response2 = MagicMock()
        mock_response2.json.return_value = {"embedding": [0.3, 0.4]}
        mock_response2.raise_for_status = MagicMock()

        with patch.object(emb._client, "post", side_effect=[mock_response1, mock_response2]):
            result = emb.embed_documents(["text1", "text2"])
            assert len(result) == 2
            assert result[0] == [0.1, 0.2]
            assert result[1] == [0.3, 0.4]

    def test_embed_empty_response(self):
        """Empty embedding in response should return empty list."""
        emb = OllamaEmbeddings()
        mock_response = MagicMock()
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        with patch.object(emb._client, "post", return_value=mock_response):
            result = emb.embed_query("test")
            assert result == []
