"""文档导入层：文件校验、SHA-256 哈希、安全文件名、重复检测、类型识别。"""
from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import settings
from .logging_config import get_logger

log = get_logger(__name__)


@dataclass
class ImportedDocument:
    original_name: str
    stored_name: str
    stored_path: Path
    file_hash: str
    extension: str
    size_bytes: int
    imported_at: str
    status: str = "imported"      # imported / duplicate / rejected
    doc_type: str | None = None
    error: str | None = None


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def secure_filename(name: str) -> str:
    """安全化文件名：保留中文/字母/数字，其余字符替换为下划线。"""
    p = Path(name)
    suffix = p.suffix.lower()
    stem = p.stem
    safe = re.sub(r"[^\w一-鿿-]", "_", stem).strip("._")
    if not safe:
        safe = "file"
    return f"{safe}{suffix}"


def validate_file(path: Path) -> str | None:
    """校验文件类型与大小；返回错误信息或 None。"""
    ext = path.suffix.lower()
    if ext not in settings.file_rules.allowed_extensions:
        return f"不支持的文件类型：{ext or '(无扩展名)'}"
    try:
        size = path.stat().st_size
    except OSError as exc:
        return f"无法读取文件：{exc}"
    if size == 0:
        return "文件为空"
    if size > settings.file_rules.max_file_size_bytes:
        limit_mb = settings.file_rules.max_file_size_bytes // (1024 * 1024)
        return f"文件超过大小限制（{limit_mb}MB）"
    return None


def import_file(
    src: Path,
    known_hashes: set[str] | None = None,
    target_dir: Path | None = None,
) -> ImportedDocument:
    """导入单个文件：校验、去重、安全保存。"""
    settings.ensure_dirs()
    target_dir = target_dir or settings.upload_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    original_name = src.name
    ext = src.suffix.lower()

    err = validate_file(src)
    if err:
        return ImportedDocument(
            original_name=original_name, stored_name="", stored_path=src,
            file_hash="", extension=ext, size_bytes=0,
            imported_at=_now(), status="rejected", error=err,
        )

    file_hash = sha256_of(src)
    if known_hashes and file_hash in known_hashes:
        return ImportedDocument(
            original_name=original_name, stored_name="", stored_path=src,
            file_hash=file_hash, extension=ext, size_bytes=src.stat().st_size,
            imported_at=_now(), status="duplicate", error="相同文件已存在（SHA-256 重复）",
        )

    safe = secure_filename(original_name)
    unique = f"{uuid.uuid4().hex[:12]}_{safe}"
    dest = target_dir / unique
    shutil.copy2(src, dest)

    return ImportedDocument(
        original_name=original_name, stored_name=unique, stored_path=dest,
        file_hash=file_hash, extension=ext, size_bytes=src.stat().st_size,
        imported_at=_now(), status="imported",
    )


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
