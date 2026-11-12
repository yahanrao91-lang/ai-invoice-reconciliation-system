"""Pydantic 数据校验：校验 LLM / 离线解析输出的结构化 JSON。

LLM 输出必须通过本 Schema 校验；校验失败触发有限次重试。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class LineItemSchema(BaseModel):
    item_no: str | None = None
    name: str | None = None
    spec: str | None = None
    unit: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    tax_rate: float | None = None
    tax_amount: float | None = None
    line_total: float | None = None
    planned_qty: float | None = None
    received_qty: float | None = None


class DocumentSchema(BaseModel):
    document_type: Literal["purchase_order", "invoice", "goods_receipt_note"]
    document_number: str | None = None          # PO 编号 / 发票号码 / 收货单编号
    document_code: str | None = None            # 发票代码等
    document_date: str | None = None
    related_po_number: str | None = None        # GRN / 发票关联的 PO 编号
    supplier_name: str | None = None
    supplier_tax_no: str | None = None
    buyer_name: str | None = None
    buyer_tax_no: str | None = None
    total_amount: float | None = None
    line_items: list[LineItemSchema] = Field(default_factory=list)
    evidence: dict[str, str] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    needs_review: list[str] = Field(default_factory=list)


def validate_document_schema(obj: dict[str, Any]) -> DocumentSchema:
    """校验并返回类型化结果；失败抛出 pydantic.ValidationError。"""
    return DocumentSchema.model_validate(obj)
