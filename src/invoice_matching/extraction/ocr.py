"""本地 OCR 抽象层。

默认引擎：RapidOCR（rapidocr-onnxruntime，自包含中文 ONNX 模型，兼容 Python 3.13）。
可选引擎：PaddleOCR、Tesseract。OCR 不可用时显式抛错 / 标记状态，绝不静默跳过。
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import settings
from ..logging_config import get_logger

log = get_logger(__name__)


class OcrUnavailableError(RuntimeError):
    """OCR 引擎不可用。"""


@dataclass
class OcrLine:
    text: str
    confidence: float
    box: tuple | None = None


class OcrEngine(Protocol):
    name: str
    available: bool

    def recognize(self, image) -> list[OcrLine]: ...


class RapidOcrEngine:
    name = "rapidocr"

    def __init__(self) -> None:
        self._engine = None
        self._error: str | None = None
        self.available = self._load()

    def _load(self) -> bool:
        try:
            from rapidocr_onnxruntime import RapidOCR

            self._engine = RapidOCR()
            return True
        except Exception as exc:  # noqa: BLE001 - 记录加载失败原因
            self._error = f"RapidOCR 初始化失败：{exc}"
            log.warning(self._error)
            return False

    def recognize(self, image) -> list[OcrLine]:
        import numpy as np

        if isinstance(image, (str, Path)):
            result, _ = self._engine(str(image))
        else:
            arr = np.array(image.convert("RGB"))
            result, _ = self._engine(arr)
        lines: list[OcrLine] = []
        for item in result or []:
            box, text, score = item[0], item[1], item[2]
            lines.append(
                OcrLine(
                    text=str(text),
                    confidence=float(score),
                    box=tuple(box) if box is not None else None,
                )
            )
        return lines


class PaddleOcrEngine:
    name = "paddleocr"

    def __init__(self) -> None:
        self._engine = None
        self._error: str | None = None
        self.available = self._load()

    def _load(self) -> bool:
        try:
            from paddleocr import PaddleOCR

            self._engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
            return True
        except Exception as exc:  # noqa: BLE001
            self._error = f"PaddleOCR 初始化失败：{exc}"
            log.warning(self._error)
            return False

    def recognize(self, image) -> list[OcrLine]:
        import numpy as np

        arr = np.array(image.convert("RGB"))
        result = self._engine.ocr(arr, cls=True)
        lines: list[OcrLine] = []
        for page in result or []:
            if not page:
                continue
            for box, (text, score) in page:
                lines.append(
                    OcrLine(
                        text=str(text),
                        confidence=float(score),
                        box=tuple(box) if box is not None else None,
                    )
                )
        return lines


class TesseractEngine:
    name = "tesseract"

    def __init__(self) -> None:
        self._error: str | None = None
        self.available = self._load()

    def _load(self) -> bool:
        try:
            import pytesseract  # noqa: F401
        except ImportError:
            self._error = "pytesseract 未安装"
            return False
        if shutil.which("tesseract") is None:
            self._error = "未找到 Tesseract 可执行文件（需单独安装）"
            return False
        return True

    def recognize(self, image) -> list[OcrLine]:
        import pytesseract

        text = pytesseract.image_to_string(image, lang="chi_sim+eng")
        return [OcrLine(text=text.strip(), confidence=1.0)]


_ENGINES = {
    "rapidocr": RapidOcrEngine,
    "paddleocr": PaddleOcrEngine,
    "tesseract": TesseractEngine,
}


class OcrManager:
    """根据配置选择 OCR 引擎并暴露统一状态。"""

    def __init__(self, engine_name: str | None = None) -> None:
        self.engine_name = (engine_name or settings.ocr_engine).lower()
        self.engine: OcrEngine | None = None
        self.status_message = ""
        self.available = False
        if settings.ocr_enabled:
            self._init_engine()
        else:
            self.status_message = "OCR 已在配置中禁用（OCR_ENABLED=0）"

    def _init_engine(self) -> None:
        cls = _ENGINES.get(self.engine_name, RapidOcrEngine)
        if self.engine_name not in _ENGINES:
            self.status_message = f"未知 OCR 引擎 {self.engine_name}，回退到 RapidOCR"
            log.warning(self.status_message)
            cls = RapidOcrEngine
        self.engine = cls()
        self.available = self.engine.available
        self.status_message = getattr(self.engine, "_error", "") or "OCR 引擎可用"

    def recognize(self, image) -> list[OcrLine]:
        if not self.available or self.engine is None:
            raise OcrUnavailableError(self.status_message or "OCR 引擎不可用")
        return self.engine.recognize(image)

    def status(self) -> dict:
        return {
            "engine": self.engine_name,
            "available": self.available,
            "message": self.status_message,
        }
