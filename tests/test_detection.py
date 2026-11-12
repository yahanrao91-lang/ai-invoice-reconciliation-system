"""文档类型识别测试。"""
from pathlib import Path

from invoice_matching.detection import detect_document_type, detect_document_type_from_path
from invoice_matching.models import DocumentType


def test_detect_invoice_by_chinese():
    assert detect_document_type("发票代码：3100160000") == DocumentType.INVOICE


def test_detect_invoice_by_english():
    assert detect_document_type("INVOICE NO: 123") == DocumentType.INVOICE


def test_detect_grn():
    assert detect_document_type("收货单编号：GRN-1") == DocumentType.GOODS_RECEIPT_NOTE


def test_detect_po():
    assert detect_document_type("采购订单编号：PO-1") == DocumentType.PURCHASE_ORDER


def test_detect_po_not_mistaken_for_invoice():
    # 采购订单中常出现「价税合计」，但不应误判为发票
    assert detect_document_type("采购订单编号：PO-1\n价税合计：100") == DocumentType.PURCHASE_ORDER


def test_detect_unknown():
    assert detect_document_type("随便一段文本") is None


def test_detect_from_path():
    assert detect_document_type_from_path(Path("Invoice_1.pdf")) == DocumentType.INVOICE
    assert detect_document_type_from_path(Path("GRN_1.png")) == DocumentType.GOODS_RECEIPT_NOTE
    assert detect_document_type_from_path(Path("PO_1.xlsx")) == DocumentType.PURCHASE_ORDER
