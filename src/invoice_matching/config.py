"""集中配置管理：路径、文件规则、OCR、LLM、业务容差。

所有业务规则和容差集中在此，禁止散落在业务代码中。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：src/invoice_matching/config.py -> 上溯三级
PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_DATA_DIR = PROJECT_ROOT / "data"


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


@dataclass(frozen=True)
class BusinessRules:
    """业务规则与容差，全部集中管理。"""

    # 单价相对容差（超出即价格差异异常）
    price_tolerance_rate: Decimal = Decimal("0.01")
    # 金额相对容差
    amount_tolerance: Decimal = Decimal("0.02")
    # 税率容差
    tax_rate_tolerance: Decimal = Decimal("0.0001")
    # 允许部分收货（收货数量 < 订单数量）
    allow_partial_delivery: bool = True
    # 允许分批开票（发票数量 < 订单数量）
    allow_partial_invoice: bool = True
    # 是否允许收货数量超过订单数量
    allow_over_receipt: bool = False


@dataclass(frozen=True)
class FileRules:
    """文件导入规则。"""

    allowed_extensions: tuple = (".pdf", ".png", ".jpg", ".jpeg", ".xlsx")
    max_file_size_bytes: int = 20 * 1024 * 1024  # 20 MB


class Settings:
    """运行时配置单例。"""

    def __init__(self) -> None:
        self.project_root = PROJECT_ROOT
        self.data_dir = Path(os.getenv("APP_DATA_DIR", str(DEFAULT_DATA_DIR)))
        self.upload_dir = self.data_dir / "uploads"
        self.db_path = self.data_dir / "invoice_matching.db"
        self.export_dir = self.data_dir / "exports"
        self.log_dir = self.data_dir / "logs"
        self.file_rules = FileRules()
        self.rules = BusinessRules()

        # LLM（OpenAI-Compatible Chat Completions）
        self.llm_base_url = os.getenv("LLM_BASE_URL", "").strip()
        self.llm_api_key = os.getenv("LLM_API_KEY", "").strip()
        self.llm_model = os.getenv("LLM_MODEL", "").strip()
        self.llm_enabled = _get_bool("LLM_ENABLED", False)
        self.llm_timeout = int(os.getenv("LLM_TIMEOUT", "60") or "60")
        self.llm_max_retries = int(os.getenv("LLM_MAX_RETRIES", "2") or "2")

        # OCR
        self.ocr_engine = os.getenv("OCR_ENGINE", "rapidocr").strip().lower()
        self.ocr_enabled = _get_bool("OCR_ENABLED", True)

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir, self.export_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def llm_configured(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key and self.llm_model)


settings = Settings()
