import os
import hashlib
import shutil
import uuid
from pathlib import Path
from loguru import logger
from app.config import settings


def _get_base_dir() -> Path:
    """Get the project base directory (backend/).
    Resolves relative to this file: app/utils/storage.py -> ../../
    """
    return Path(__file__).resolve().parent.parent.parent


MAGIC_NUMBERS = {
    ".pdf": [b"%PDF-"],
    ".docx": [
        bytes([0x50, 0x4B, 0x03, 0x04]),
        bytes([0x50, 0x4B, 0x05, 0x06]),
        bytes([0x50, 0x4B, 0x07, 0x08]),
    ],
    ".md": [],
    ".markdown": [],
    ".txt": [],
}

TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}

ALLOWED_EXT = {".pdf", ".docx", ".md", ".markdown", ".txt"}


def get_storage_dir() -> Path:
    storage = _get_base_dir() / "storage"
    storage.mkdir(parents=True, exist_ok=True)
    (storage / "temp").mkdir(parents=True, exist_ok=True)
    return storage


def get_kb_dir(kb_id: int) -> Path:
    kb_dir = get_storage_dir() / str(kb_id)
    kb_dir.mkdir(parents=True, exist_ok=True)
    return kb_dir


def validate_file_type(filename: str, content: bytes) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"Unsupported file type: {ext}")

    if ext in TEXT_EXTENSIONS:
        return ext.lstrip(".")

    magic_list = MAGIC_NUMBERS.get(ext, [])
    if not magic_list:
        logger.warning(f"No magic number defined for {ext}, skipping magic check")
        return ext.lstrip(".")

    header = content[:8]
    matched = False
    for magic in magic_list:
        if header.startswith(magic):
            matched = True
            break

    if not matched:
        logger.warning(f"File magic mismatch: {filename}, header={header[:4].hex()}")
        raise ValueError(f"File content does not match extension: {ext}")

    return ext.lstrip(".")


def safe_filename(original_name: str, doc_id: int) -> str:
    ext = os.path.splitext(original_name)[1].lower()
    safe_id = str(uuid.uuid4())[:8]
    return f"{doc_id}_{safe_id}{ext}"


def save_upload_file(upload_file, kb_id: int, doc_id: int) -> tuple:
    kb_dir = get_kb_dir(kb_id)

    content = upload_file.file.read()
    file_size = len(content)

    max_size = settings.MAX_FILE_SIZE_MB * 1024 * 1024
    if file_size > max_size:
        raise ValueError(f"File too large (max {settings.MAX_FILE_SIZE_MB}MB)")

    file_type = validate_file_type(upload_file.filename, content)
    file_hash = hashlib.sha256(content).hexdigest()

    saved_name = safe_filename(upload_file.filename, doc_id)
    file_path = kb_dir / saved_name

    with file_path.open("wb") as f:
        f.write(content)

    logger.info(f"File saved: kb={kb_id} doc={doc_id} size={file_size} type={file_type}")

    return str(file_path), file_type, file_size, file_hash


def compute_file_hash(file_path) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def delete_file(file_path: str):
    try:
        os.remove(file_path)
        logger.info(f"File deleted: {file_path}")
    except FileNotFoundError:
        pass


def delete_kb_dir(kb_id: int):
    kb_dir = get_storage_dir() / str(kb_id)
    if kb_dir.exists():
        shutil.rmtree(kb_dir, ignore_errors=True)
        logger.info(f"KB dir deleted: kb={kb_id}")
