"""PDF 文本提取、Excel 读取、图片格式检查、OCR 接口及异常处理测试。"""
from pathlib import Path

import pytest

from invoice_matching.document_import import validate_file
from invoice_matching.extraction import extract_text
from invoice_matching.extraction.excel_extractor import extract_excel
from invoice_matching.extraction.ocr import OcrManager, OcrUnavailableError, RapidOcrEngine
from invoice_matching.models import ExtractionMethod


def _write_pdf(path: Path, lines: list[str]) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for ln in lines:
        page.insert_text((50, y), ln, fontname="china-s", fontsize=11)
        y += 22
    doc.save(str(path))
    doc.close()


def _write_xlsx(path: Path, rows: list[list]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(str(path))


def test_pdf_text_extraction(tmp_path, no_ocr):
    p = tmp_path / "a.pdf"
    _write_pdf(p, ["采购订单编号：PO-1", "供应商名称：甲公司"])
    extracted = extract_text(p, OcrManager())
    assert extracted.method == ExtractionMethod.TEXT
    assert "采购订单编号" in extracted.text


def test_excel_reading(tmp_path):
    p = tmp_path / "a.xlsx"
    _write_xlsx(p, [["采购订单编号", "PO-1"], ["供应商名称", "甲公司"]])
    text, sheets = extract_excel(p)
    assert "采购订单编号" in text
    assert "PO-1" in text
    assert len(sheets) == 1


def test_image_format_check(tmp_path):
    png = tmp_path / "img.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    assert validate_file(png) is None
    txt = tmp_path / "bad.txt"
    txt.write_text("hello")
    assert validate_file(txt) is not None


def test_file_size_limit(tmp_path, monkeypatch):
    from invoice_matching.config import settings

    big = tmp_path / "big.pdf"
    big.write_bytes(b"x" * (settings.file_rules.max_file_size_bytes + 1))
    assert validate_file(big) is not None


def test_ocr_unavailable_raises(no_ocr):
    m = OcrManager()
    assert m.available is False
    with pytest.raises(OcrUnavailableError):
        m.recognize(None)


def test_ocr_engine_recognizes_image(tmp_path):
    """真实调用本地 OCR 引擎识别一张含中文的图片。"""
    from PIL import Image, ImageDraw, ImageFont

    font_candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
    ]
    font_path = next((f for f in font_candidates if Path(f).exists()), None)
    if font_path is None:
        pytest.skip("未找到中文字体")
    eng = RapidOcrEngine()
    if not eng.available:
        pytest.skip("RapidOCR 不可用")
    img = Image.new("RGB", (800, 200), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 40)
    draw.text((30, 60), "采购订单编号：PO-OCR-001", fill="black", font=font)
    lines = eng.recognize(img)
    assert isinstance(lines, list)
    assert len(lines) >= 1
    assert any("PO-OCR-001" in l.text for l in lines)


def test_multi_page_pdf_text_extraction(tmp_path, no_ocr):
    import pymupdf

    p = tmp_path / "multi.pdf"
    doc = pymupdf.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((50, 60), f"第{i+1}页 采购订单编号：PO-MULTI-{i+1}", fontname="china-s")
    doc.save(str(p))
    doc.close()

    extracted = extract_text(p, OcrManager())
    assert extracted.method == ExtractionMethod.TEXT
    assert len(extracted.pages) == 3
    assert "PO-MULTI-1" in extracted.text
    assert "PO-MULTI-3" in extracted.text


def test_scanned_pdf_ocr_unavailable(tmp_path, no_ocr):
    """无文本层 PDF（扫描件）在 OCR 不可用时显式标记，而非静默跳过。"""
    import pymupdf

    p = tmp_path / "scanned.pdf"
    doc = pymupdf.open()
    doc.new_page()  # 空白页：无文本层
    doc.save(str(p))
    doc.close()

    extracted = extract_text(p, OcrManager())
    assert extracted.method == ExtractionMethod.OCR
    assert extracted.extra["ocr_unavailable"] is True
    assert extracted.extra["warnings"]


def test_corrupted_pdf_raises(tmp_path, no_ocr):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"this is not a real pdf")
    with pytest.raises(Exception):
        extract_text(p, OcrManager())


def test_rotated_image_does_not_crash(tmp_path):
    """图片旋转后仍能进入 OCR 流程（旋转鲁棒性以不崩溃为验证边界）。"""
    from PIL import Image, ImageDraw, ImageFont

    font_path = next(
        (f for f in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
                     "C:/Windows/Fonts/simsun.ttc"] if Path(f).exists()), None
    )
    if font_path is None:
        pytest.skip("未找到中文字体")
    eng = RapidOcrEngine()
    if not eng.available:
        pytest.skip("RapidOCR 不可用")

    img = Image.new("RGB", (600, 300), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 36)
    draw.text((40, 100), "采购订单编号：PO-ROT-001", fill="black", font=font)
    rotated = img.rotate(90, expand=True)
    p = tmp_path / "rotated.png"
    rotated.save(str(p))

    extracted = extract_text(p, OcrManager())
    assert extracted.method == ExtractionMethod.OCR
