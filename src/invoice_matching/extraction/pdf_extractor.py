"""PDF 文本提取：可搜索 PDF 直接取文本，扫描件转图片走 OCR。"""
from __future__ import annotations

import io
from pathlib import Path

from ..logging_config import get_logger
from ..models import ExtractionMethod
from .base import PageContent
from .ocr import OcrManager, OcrUnavailableError

log = get_logger(__name__)


def extract_pdf(path: Path, ocr_manager: OcrManager | None = None) -> list[PageContent]:
    import pymupdf
    from PIL import Image

    doc = pymupdf.open(str(path))
    pages: list[PageContent] = []
    try:
        for i, page in enumerate(doc):
            text = (page.get_text("text") or "").strip()
            if text:
                pages.append(
                    PageContent(i + 1, text, ExtractionMethod.TEXT, 1.0, source=str(path))
                )
                continue
            # 扫描页：渲染为图片后 OCR
            if ocr_manager is not None and ocr_manager.available:
                try:
                    pix = page.get_pixmap(dpi=200)
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    lines = ocr_manager.recognize(img)
                    ocr_text = "\n".join(ln.text for ln in lines)
                    conf = round(sum(ln.confidence for ln in lines) / len(lines), 4) if lines else 0.0
                    pages.append(
                        PageContent(i + 1, ocr_text, ExtractionMethod.OCR, conf, source=str(path))
                    )
                except OcrUnavailableError as exc:
                    pages.append(
                        PageContent(
                            i + 1, "", ExtractionMethod.OCR, 0.0,
                            source=str(path), warning=f"第{i+1}页为扫描件且 OCR 不可用：{exc}",
                        )
                    )
            else:
                msg = "第%d页为扫描件且 OCR 不可用，无法识别" % (i + 1)
                log.warning(msg)
                pages.append(
                    PageContent(i + 1, "", ExtractionMethod.OCR, 0.0, source=str(path), warning=msg)
                )
    finally:
        doc.close()
    return pages
