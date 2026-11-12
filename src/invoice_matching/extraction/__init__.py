"""文本提取与 OCR 层：PDF / 图片 / Excel。"""
from __future__ import annotations

from pathlib import Path

from ..logging_config import get_logger
from ..models import ExtractionMethod
from .base import ExtractedText, PageContent
from .excel_extractor import extract_excel
from .ocr import OcrManager, OcrUnavailableError
from .pdf_extractor import extract_pdf

log = get_logger(__name__)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}


def extract_text(path: Path, ocr_manager: OcrManager | None = None) -> ExtractedText:
    """按扩展名分发文本提取，返回统一 ExtractedText。"""
    ext = path.suffix.lower()

    if ext == ".pdf":
        pages = extract_pdf(path, ocr_manager)
        text = "\n\n".join(f"[第{p.page_no}页]\n{p.text}" for p in pages)
        methods = {p.method for p in pages}
        method = (
            ExtractionMethod.TEXT
            if methods == {ExtractionMethod.TEXT}
            else ExtractionMethod.OCR
        )
        conf = _avg([p.confidence for p in pages])
        warnings = [p.warning for p in pages if p.warning]
        return ExtractedText(
            text=text, pages=pages, method=method, confidence=conf,
            extra={"warnings": warnings, "ocr_unavailable": any(p.warning for p in pages)},
        )

    if ext in _IMAGE_EXTS:
        if ocr_manager is None or not ocr_manager.available:
            msg = "OCR 引擎不可用，无法识别图片。"
            log.warning(msg)
            return ExtractedText(
                text="", pages=[PageContent(1, "", ExtractionMethod.OCR, 0.0, warning=msg)],
                method=ExtractionMethod.OCR, confidence=0.0,
                extra={"warnings": [msg], "ocr_unavailable": True},
            )
        from PIL import Image

        img = Image.open(path)
        lines = ocr_manager.recognize(img)
        text = "\n".join(l.text for l in lines)
        conf = _avg([l.confidence for l in lines])
        return ExtractedText(
            text=text,
            pages=[PageContent(1, text, ExtractionMethod.OCR, conf)],
            method=ExtractionMethod.OCR,
            confidence=conf,
            extra={"warnings": [], "ocr_unavailable": False},
        )

    if ext == ".xlsx":
        text, sheets = extract_excel(path)
        return ExtractedText(
            text=text,
            pages=[PageContent(1, text, ExtractionMethod.TEXT, 1.0)],
            method=ExtractionMethod.TEXT,
            confidence=1.0,
            extra={"sheets": sheets, "warnings": [], "ocr_unavailable": False},
        )

    raise ValueError(f"不支持的文件类型：{ext}")


def _avg(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


__all__ = ["extract_text", "ExtractedText", "PageContent", "OcrManager", "OcrUnavailableError"]
