"""文档类型识别：依据文件名与文本关键词判定 PO / Invoice / GRN。"""
from __future__ import annotations

from pathlib import Path

from .models import DocumentType


def detect_document_type(text: str, filename: str = "") -> DocumentType | None:
    """返回识别出的文档类型；无法确定时返回 None。"""
    sample = (filename or "") + "\n" + (text or "")
    up = sample.upper()

    # 发票特征最明确，优先判断（仅凭「发票」或 INVOICE，价税合计在 PO 中也常见）
    if "发票" in sample or "INVOICE" in up:
        return DocumentType.INVOICE

    # 收货记录
    if any(k in sample for k in ("收货单", "收货记录", "入库单", "实际收货", "收货数量")) or \
            "GRN" in up:
        return DocumentType.GOODS_RECEIPT_NOTE

    # 采购订单
    if any(k in sample for k in ("采购订单", "采购单", "订购单", "订单编号", "订单日期")) or \
            "PURCHASE ORDER" in up:
        return DocumentType.PURCHASE_ORDER

    return None


def detect_document_type_from_path(path: Path) -> DocumentType | None:
    name = path.name
    up = name.upper()
    if "INVOICE" in up or "发票" in name:
        return DocumentType.INVOICE
    if "GRN" in up or "收货" in name:
        return DocumentType.GOODS_RECEIPT_NOTE
    if "PO" in up or "采购" in name or "订单" in name:
        return DocumentType.PURCHASE_ORDER
    return None
