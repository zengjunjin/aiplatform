"""Tests for app.utils.token_counter and app.utils.storage"""
import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from app.utils.token_counter import count_tokens, count_messages_tokens
from app.utils.storage import (
    get_storage_dir, get_kb_dir, validate_file_type, safe_filename,
    save_upload_file, compute_file_hash, delete_file, delete_kb_dir,
    ALLOWED_EXT, TEXT_EXTENSIONS, MAGIC_NUMBERS,
)


class TestTokenCounter:
    def test_count_tokens_non_empty_string(self):
        n = count_tokens("hello world")
        assert n > 0

    def test_count_tokens_empty_string(self):
        assert count_tokens("") == 0

    def test_count_tokens_unknown_model_falls_back(self):
        """未知 model → 用 cl100k_base encoding"""
        n = count_tokens("hello", model="unknown-model-xyz")
        assert n > 0

    def test_count_messages_tokens_basic(self):
        messages = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        total = count_messages_tokens(messages)
        # 2 条消息，每条 content 至少 1 token + 4 overhead + 2 对话 overhead
        assert total >= 2 + 8 + 2

    def test_count_messages_tokens_empty_list(self):
        assert count_messages_tokens([]) == 2  # 仅对话 overhead

    def test_count_messages_tokens_missing_content(self):
        """msg 无 content → 视为 0"""
        messages = [{"role": "user"}]  # 无 content
        assert count_messages_tokens(messages) == 6  # 0 + 4 + 2


class TestStorageDirs:
    def test_get_storage_dir_creates_dirs(self, tmp_path, monkeypatch):
        """get_storage_dir 创建 storage 和 storage/temp"""
        monkeypatch.chdir(tmp_path)
        storage = get_storage_dir()
        assert storage.exists()
        assert (storage / "temp").exists()

    def test_get_kb_dir_creates_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        kb_dir = get_kb_dir(kb_id=42)
        assert kb_dir.exists()
        assert kb_dir.name == "42"

    def test_get_kb_dir_idempotent(self, tmp_path, monkeypatch):
        """重复调用不报错"""
        monkeypatch.chdir(tmp_path)
        kb_dir1 = get_kb_dir(kb_id=1)
        kb_dir2 = get_kb_dir(kb_id=1)
        assert kb_dir1 == kb_dir2


class TestValidateFileType:
    def test_validate_pdf_with_correct_magic(self):
        content = b"%PDF-1.5 rest of pdf"
        assert validate_file_type("doc.pdf", content) == "pdf"

    def test_validate_pdf_with_wrong_magic_rejected(self):
        content = b"not a pdf at all"
        with pytest.raises(ValueError, match="content does not match"):
            validate_file_type("doc.pdf", content)

    def test_validate_docx_with_correct_magic(self):
        content = bytes([0x50, 0x4B, 0x03, 0x04]) + b"rest of docx"
        assert validate_file_type("doc.docx", content) == "docx"

    def test_validate_md_text_extension_skips_magic(self):
        """text 类型（md/txt）跳过 magic 检查"""
        content = b"# any content"
        assert validate_file_type("a.md", content) == "md"
        assert validate_file_type("b.txt", content) == "txt"
        assert validate_file_type("c.markdown", content) == "markdown"

    def test_validate_unsupported_extension_rejected(self):
        with pytest.raises(ValueError, match="Unsupported file type"):
            validate_file_type("a.exe", b"binary")

    def test_validate_extension_case_insensitive(self):
        """扩展名大写也接受"""
        content = b"%PDF-1.5"
        assert validate_file_type("DOC.PDF", content) == "pdf"


class TestSafeFilename:
    def test_safe_filename_preserves_extension(self):
        name = safe_filename("original.pdf", doc_id=42)
        assert name.endswith(".pdf")
        assert name.startswith("42_")

    def test_safe_filename_generates_unique_id(self):
        """每次生成不同 uuid"""
        n1 = safe_filename("a.md", 1)
        n2 = safe_filename("a.md", 1)
        assert n1 != n2  # uuid 不同

    def test_safe_filename_no_extension(self):
        name = safe_filename("noext", doc_id=10)
        # os.path.splitext 返回空字符串作为 ext
        assert name.startswith("10_")


class TestComputeFileHash:
    def test_compute_file_hash_consistent(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world")
        h1 = compute_file_hash(f)
        h2 = compute_file_hash(f)
        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    def test_compute_file_hash_different_content(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f1.write_bytes(b"content a")
        f2 = tmp_path / "b.txt"
        f2.write_bytes(b"content b")
        assert compute_file_hash(f1) != compute_file_hash(f2)

    def test_compute_file_hash_large_file(self, tmp_path):
        """大文件分块读取，结果应正确"""
        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * 10000)
        h = compute_file_hash(f)
        assert len(h) == 64


class TestDeleteFile:
    def test_delete_file_removes_existing(self, tmp_path):
        f = tmp_path / "to_delete.txt"
        f.write_text("x")
        assert f.exists()
        delete_file(str(f))
        assert not f.exists()

    def test_delete_file_missing_no_error(self, tmp_path):
        """删除不存在的文件 → 不抛异常"""
        delete_file(str(tmp_path / "nonexistent.txt"))  # 不抛


class TestDeleteKbDir:
    def test_delete_kb_dir_removes_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        kb_dir = get_kb_dir(kb_id=99)
        (kb_dir / "file.txt").write_text("x")
        assert kb_dir.exists()
        delete_kb_dir(kb_id=99)
        assert not kb_dir.exists()

    def test_delete_kb_dir_nonexistent_no_error(self, tmp_path, monkeypatch):
        """删除不存在的 kb 目录 → 不抛"""
        monkeypatch.chdir(tmp_path)
        delete_kb_dir(kb_id=999)  # 不存在，不抛


class TestSaveUploadFile:
    def test_save_upload_file_success(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # 构造 UploadFile-like 对象
        upload = MagicMock()
        upload.filename = "test.md"
        upload.file.read.return_value = b"# hello"

        path, file_type, size, hash_ = save_upload_file(upload, kb_id=1, doc_id=10)
        assert os.path.exists(path)
        assert file_type == "md"
        assert size == 7
        assert len(hash_) == 64

    def test_save_upload_file_too_large_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # mock settings.MAX_FILE_SIZE_MB = 1
        with patch("app.utils.storage.settings") as mock_settings:
            mock_settings.MAX_FILE_SIZE_MB = 1
            upload = MagicMock()
            upload.filename = "big.md"
            upload.file.read.return_value = b"x" * (2 * 1024 * 1024)  # 2MB

            with pytest.raises(ValueError, match="File too large"):
                save_upload_file(upload, kb_id=1, doc_id=10)

    def test_save_upload_file_unsupported_type_rejected(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        upload = MagicMock()
        upload.filename = "bad.exe"
        upload.file.read.return_value = b"binary"

        with pytest.raises(ValueError, match="Unsupported file type"):
            save_upload_file(upload, kb_id=1, doc_id=10)


class TestConstants:
    def test_allowed_ext_includes_all_supported(self):
        assert {".pdf", ".docx", ".md", ".markdown", ".txt"} == ALLOWED_EXT

    def test_text_extensions_subset_of_allowed(self):
        assert TEXT_EXTENSIONS.issubset(ALLOWED_EXT)

    def test_magic_numbers_pdf_defined(self):
        assert b"%PDF-" in MAGIC_NUMBERS[".pdf"]

    def test_magic_numbers_docx_zip_format(self):
        """docx 是 zip 格式，magic number 应包含 PK 签名"""
        for magic in MAGIC_NUMBERS[".docx"]:
            assert magic[0:2] == b"PK"

    def test_text_extensions_have_empty_magic(self):
        """md/txt 无 magic number（跳过检查）"""
        for ext in TEXT_EXTENSIONS:
            assert MAGIC_NUMBERS.get(ext) == []
