"""统一数据模型：采购订单、发票、收货记录及行明细。

- 金额字段统一使用 Decimal，避免浮点误差。
- 缺失字段一律用 None 表示，绝不编造。
- 所有实体支持 to_dict / from_dict，用于 JSON 持久化与追溯。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class DocumentType(str, Enum):
    PURCHASE_ORDER = "purchase_order"
    INVOICE = "invoice"
    GOODS_RECEIPT_NOTE = "goods_receipt_note"

    @property
    def label(self) -> str:
        return {
            DocumentType.PURCHASE_ORDER: "采购订单 PO",
            DocumentType.INVOICE: "供应商发票 Invoice",
            DocumentType.GOODS_RECEIPT_NOTE: "收货记录 GRN",
        }[self]


class ExtractionMethod(str, Enum):
    TEXT = "text"        # PDF 直接文本层
    OCR = "ocr"          # 本地 OCR
    AI = "ai"            # 大语言模型结构化提取
    OFFLINE = "offline"  # 离线规则解析
    MANUAL = "manual"    # 人工录入


def _dec(value: Any) -> Decimal | None:
    """安全转换为 Decimal；None 与空串返回 None。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    s = str(value).strip().replace(",", "").replace("，", "")
    if s in {"", "-", "None", "null"}:
        return None
    try:
        return Decimal(s)
    except Exception:
        return None


def _dec_str(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


@dataclass
class TradeLine:
    """采购订单 / 发票共用的商品行。"""

    item_no: str | None = None
    name: str | None = None
    spec: str | None = None
    unit: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None      # 商品金额（不含税）= 数量 × 单价
    tax_rate: Decimal | None = None    # 税率（小数，如 0.13）
    tax_amount: Decimal | None = None  # 税额 = 金额 × 税率
    line_total: Decimal | None = None  # 价税合计 = 金额 + 税额
    source: str = ""                   # 该行来源说明（文件名/页码/行号）

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_no": self.item_no,
            "name": self.name,
            "spec": self.spec,
            "unit": self.unit,
            "quantity": _dec_str(self.quantity),
            "unit_price": _dec_str(self.unit_price),
            "amount": _dec_str(self.amount),
            "tax_rate": _dec_str(self.tax_rate),
            "tax_amount": _dec_str(self.tax_amount),
            "line_total": _dec_str(self.line_total),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TradeLine":
        return cls(
            item_no=d.get("item_no"),
            name=d.get("name"),
            spec=d.get("spec"),
            unit=d.get("unit"),
            quantity=_dec(d.get("quantity")),
            unit_price=_dec(d.get("unit_price")),
            amount=_dec(d.get("amount")),
            tax_rate=_dec(d.get("tax_rate")),
            tax_amount=_dec(d.get("tax_amount")),
            line_total=_dec(d.get("line_total")),
            source=d.get("source", ""),
        )


@dataclass
class GrnLine:
    """收货记录行：区分计划收货数量与实际收货数量。"""

    item_no: str | None = None
    name: str | None = None
    spec: str | None = None
    unit: str | None = None
    planned_qty: Decimal | None = None
    received_qty: Decimal | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_no": self.item_no,
            "name": self.name,
            "spec": self.spec,
            "unit": self.unit,
            "planned_qty": _dec_str(self.planned_qty),
            "received_qty": _dec_str(self.received_qty),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GrnLine":
        return cls(
            item_no=d.get("item_no"),
            name=d.get("name"),
            spec=d.get("spec"),
            unit=d.get("unit"),
            planned_qty=_dec(d.get("planned_qty")),
            received_qty=_dec(d.get("received_qty")),
            source=d.get("source", ""),
        )


@dataclass
class PurchaseOrder:
    po_number: str | None = None
    order_date: str | None = None
    supplier_name: str | None = None
    supplier_tax_no: str | None = None
    buyer_name: str | None = None
    buyer_tax_no: str | None = None
    lines: list[TradeLine] = field(default_factory=list)
    total_amount: Decimal | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "po_number": self.po_number,
            "order_date": self.order_date,
            "supplier_name": self.supplier_name,
            "supplier_tax_no": self.supplier_tax_no,
            "buyer_name": self.buyer_name,
            "buyer_tax_no": self.buyer_tax_no,
            "lines": [ln.to_dict() for ln in self.lines],
            "total_amount": _dec_str(self.total_amount),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PurchaseOrder":
        return cls(
            po_number=d.get("po_number"),
            order_date=d.get("order_date"),
            supplier_name=d.get("supplier_name"),
            supplier_tax_no=d.get("supplier_tax_no"),
            buyer_name=d.get("buyer_name"),
            buyer_tax_no=d.get("buyer_tax_no"),
            lines=[TradeLine.from_dict(x) for x in d.get("lines", [])],
            total_amount=_dec(d.get("total_amount")),
        )


@dataclass
class Invoice:
    invoice_code: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None
    seller_name: str | None = None
    seller_tax_no: str | None = None
    buyer_name: str | None = None
    buyer_tax_no: str | None = None
    po_number: str | None = None
    lines: list[TradeLine] = field(default_factory=list)
    total_amount: Decimal | None = None  # 价税合计

    def to_dict(self) -> dict[str, Any]:
        return {
            "invoice_code": self.invoice_code,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "seller_name": self.seller_name,
            "seller_tax_no": self.seller_tax_no,
            "buyer_name": self.buyer_name,
            "buyer_tax_no": self.buyer_tax_no,
            "po_number": self.po_number,
            "lines": [ln.to_dict() for ln in self.lines],
            "total_amount": _dec_str(self.total_amount),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Invoice":
        return cls(
            invoice_code=d.get("invoice_code"),
            invoice_number=d.get("invoice_number"),
            invoice_date=d.get("invoice_date"),
            seller_name=d.get("seller_name"),
            seller_tax_no=d.get("seller_tax_no"),
            buyer_name=d.get("buyer_name"),
            buyer_tax_no=d.get("buyer_tax_no"),
            po_number=d.get("po_number"),
            lines=[TradeLine.from_dict(x) for x in d.get("lines", [])],
            total_amount=_dec(d.get("total_amount")),
        )


@dataclass
class GoodsReceiptNote:
    grn_number: str | None = None
    po_number: str | None = None
    receipt_date: str | None = None
    supplier_name: str | None = None
    supplier_tax_no: str | None = None
    lines: list[GrnLine] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "grn_number": self.grn_number,
            "po_number": self.po_number,
            "receipt_date": self.receipt_date,
            "supplier_name": self.supplier_name,
            "supplier_tax_no": self.supplier_tax_no,
            "lines": [ln.to_dict() for ln in self.lines],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "GoodsReceiptNote":
        return cls(
            grn_number=d.get("grn_number"),
            po_number=d.get("po_number"),
            receipt_date=d.get("receipt_date"),
            supplier_name=d.get("supplier_name"),
            supplier_tax_no=d.get("supplier_tax_no"),
            lines=[GrnLine.from_dict(x) for x in d.get("lines", [])],
        )


@dataclass
class ExtractionResult:
    """一次结构化提取的结果，携带来源与方法标识。"""

    document_type: DocumentType | None = None
    data: PurchaseOrder | Invoice | GoodsReceiptNote | None = None
    evidence: dict[str, str] = field(default_factory=dict)
    method: ExtractionMethod = ExtractionMethod.MANUAL
    confidence: float = 0.0
    missing_fields: list[str] = field(default_factory=list)
    needs_review: list[str] = field(default_factory=list)
    raw_text: str = ""
    warnings: list[str] = field(default_factory=list)


def entity_from_type(doc_type: DocumentType, data: dict[str, Any]):
    if doc_type == DocumentType.PURCHASE_ORDER:
        return PurchaseOrder.from_dict(data)
    if doc_type == DocumentType.INVOICE:
        return Invoice.from_dict(data)
    if doc_type == DocumentType.GOODS_RECEIPT_NOTE:
        return GoodsReceiptNote.from_dict(data)
    raise ValueError(f"未知文档类型：{doc_type}")
