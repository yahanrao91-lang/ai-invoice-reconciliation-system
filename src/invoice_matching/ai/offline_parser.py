"""离线演示模式：本地规则/模板解析，用于未配置 API Key 的演示。

- 对随项目提供的模拟文档使用确定性规则解析。
- 无法可靠解析时返回人工录入提示，绝不伪装成真实 LLM 调用。
"""
from __future__ import annotations

import re

from ..detection import detect_document_type
from ..logging_config import get_logger
from ..models import (
    DocumentType,
    ExtractionMethod,
    ExtractionResult,
    GoodsReceiptNote,
    GrnLine,
    Invoice,
    PurchaseOrder,
    TradeLine,
)
from ..processing.standardize import (
    normalize_date,
    normalize_item_no,
    normalize_name,
    normalize_supplier,
    normalize_tax_no,
    normalize_unit,
    parse_decimal,
    parse_tax_rate,
    quantize_money,
    quantize_qty,
)

log = get_logger(__name__)


def _label(text: str, label: str) -> str | None:
    """提取形如「标签：值」的字段值。"""
    for line in text.splitlines():
        l = line.strip()
        if l.startswith(label):
            rest = l[len(label) :].lstrip(":： \t")
            return rest if rest else None
    return None


def _table_rows(text: str) -> list[list[str]]:
    """解析表格行：统一按 `|`、`/`、全角 `／` 切分（OCR 常把竖线识别为斜线）。

    说明：演示数据与常见票据明细值中不含斜线，故可安全统一切分。
    """
    rows: list[list[str]] = []
    for line in text.splitlines():
        l = line.strip()
        if not l or "商品明细" in l:
            continue
        if not any(ch in l for ch in "|/／"):
            continue
        l = l.replace("／", "/")
        cells = [c.strip() for c in re.split(r"[|/]", l)]
        if not cells:
            continue
        first = cells[0]
        if first in {"商品编号", "行号", "序号", "项目", "No"}:
            continue
        if any(k in first for k in ("合计", "总计", "价税合计")):
            continue
        rows.append(cells)
    return rows


def _parse_trade_lines(text: str) -> list[TradeLine]:
    items: list[TradeLine] = []
    for cells in _table_rows(text):
        if len(cells) < 4:
            continue
        name = normalize_name(cells[1])
        if not name:
            continue
        items.append(
            TradeLine(
                item_no=normalize_item_no(cells[0]),
                name=name,
                spec=normalize_name(cells[2]),
                unit=normalize_unit(cells[3]),
                quantity=quantize_qty(parse_decimal(cells[4])) if len(cells) > 4 else None,
                unit_price=quantize_money(parse_decimal(cells[5])) if len(cells) > 5 else None,
                amount=quantize_money(parse_decimal(cells[6])) if len(cells) > 6 else None,
                tax_rate=parse_tax_rate(cells[7]) if len(cells) > 7 else None,
                tax_amount=quantize_money(parse_decimal(cells[8])) if len(cells) > 8 else None,
                line_total=quantize_money(parse_decimal(cells[9])) if len(cells) > 9 else None,
                source="offline",
            )
        )
    return items


def _parse_grn_lines(text: str) -> list[GrnLine]:
    items: list[GrnLine] = []
    for cells in _table_rows(text):
        if len(cells) < 6:
            continue
        name = normalize_name(cells[1])
        if not name:
            continue
        items.append(
            GrnLine(
                item_no=normalize_item_no(cells[0]),
                name=name,
                spec=normalize_name(cells[2]),
                unit=normalize_unit(cells[3]),
                planned_qty=quantize_qty(parse_decimal(cells[4])),
                received_qty=quantize_qty(parse_decimal(cells[5])),
                source="offline",
            )
        )
    return items


def _parse_po(text: str) -> PurchaseOrder:
    total = _label(text, "合计金额") or _label(text, "价税合计") or _label(text, "总金额")
    return PurchaseOrder(
        po_number=normalize_item_no(_label(text, "采购订单编号") or _label(text, "订单编号")),
        order_date=normalize_date(_label(text, "订单日期")),
        supplier_name=normalize_supplier(_label(text, "供应商名称")),
        supplier_tax_no=normalize_tax_no(_label(text, "供应商税号")),
        buyer_name=normalize_supplier(_label(text, "采购方名称") or _label(text, "购买方名称")),
        buyer_tax_no=normalize_tax_no(_label(text, "采购方税号") or _label(text, "购买方税号")),
        total_amount=quantize_money(parse_decimal(total)),
        lines=_parse_trade_lines(text),
    )


def _parse_invoice(text: str) -> Invoice:
    total = _label(text, "合计金额") or _label(text, "价税合计")
    return Invoice(
        invoice_code=normalize_item_no(_label(text, "发票代码")),
        invoice_number=normalize_item_no(_label(text, "发票号码") or _label(text, "发票号")),
        invoice_date=normalize_date(_label(text, "开票日期") or _label(text, "发票日期")),
        seller_name=normalize_supplier(_label(text, "销售方名称") or _label(text, "供应商名称")),
        seller_tax_no=normalize_tax_no(_label(text, "销售方税号") or _label(text, "供应商税号")),
        buyer_name=normalize_supplier(_label(text, "购买方名称") or _label(text, "采购方名称")),
        buyer_tax_no=normalize_tax_no(_label(text, "购买方税号") or _label(text, "采购方税号")),
        po_number=normalize_item_no(_label(text, "关联采购订单号") or _label(text, "采购订单号")),
        total_amount=quantize_money(parse_decimal(total)),
        lines=_parse_trade_lines(text),
    )


def _parse_grn(text: str) -> GoodsReceiptNote:
    return GoodsReceiptNote(
        grn_number=normalize_item_no(_label(text, "收货单编号") or _label(text, "收货单号")),
        po_number=normalize_item_no(_label(text, "关联采购订单号") or _label(text, "采购订单号")),
        receipt_date=normalize_date(_label(text, "收货日期")),
        supplier_name=normalize_supplier(_label(text, "供应商名称")),
        supplier_tax_no=normalize_tax_no(_label(text, "供应商税号")),
        lines=_parse_grn_lines(text),
    )


def _collect_missing(dt: DocumentType, data) -> list[str]:
    missing: list[str] = []
    if dt == DocumentType.PURCHASE_ORDER:
        if not data.po_number:
            missing.append("采购订单编号")
        if not data.supplier_name:
            missing.append("供应商名称")
        if not data.lines:
            missing.append("商品明细")
    elif dt == DocumentType.INVOICE:
        if not data.invoice_number:
            missing.append("发票号码")
        if not data.seller_name:
            missing.append("销售方名称")
        if not data.lines:
            missing.append("商品明细")
    else:
        if not data.grn_number:
            missing.append("收货单编号")
        if not data.po_number:
            missing.append("关联采购订单号")
        if not data.lines:
            missing.append("商品明细")
    return missing


def parse_offline(text: str, filename: str = "") -> ExtractionResult:
    """离线规则解析入口。"""
    dt = detect_document_type(text, filename)
    if dt is None:
        return ExtractionResult(
            document_type=None,
            data=None,
            method=ExtractionMethod.OFFLINE,
            confidence=0.0,
            missing_fields=["文档类型"],
            needs_review=["无法识别文档类型，请人工选择类型并录入"],
            raw_text=text,
        )
    if dt == DocumentType.PURCHASE_ORDER:
        data = _parse_po(text)
    elif dt == DocumentType.INVOICE:
        data = _parse_invoice(text)
    else:
        data = _parse_grn(text)

    missing = _collect_missing(dt, data)
    confidence = max(0.2, round(0.9 - 0.05 * len(missing), 2))
    return ExtractionResult(
        document_type=dt,
        data=data,
        evidence=_evidence_map(text),
        method=ExtractionMethod.OFFLINE,
        confidence=confidence,
        missing_fields=missing,
        needs_review=[],
        raw_text=text,
    )


def _evidence_map(text: str) -> dict[str, str]:
    evidence: dict[str, str] = {}
    for label in (
        "采购订单编号", "订单编号", "订单日期", "供应商名称", "供应商税号", "采购方名称", "采购方税号",
        "发票代码", "发票号码", "开票日期", "销售方名称", "销售方税号", "购买方名称", "购买方税号",
        "关联采购订单号", "收货单编号", "收货日期", "合计金额", "价税合计",
    ):
        val = _label(text, label)
        if val:
            evidence[label] = val
    return evidence
