"""AI 结构化提取：调用 LLM，校验 JSON，转换为统一数据模型，支持有限重试。"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

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
from ..schemas import DocumentSchema, validate_document_schema
from .field_applicability import compute_completeness, filter_applicable_missing_fields
from .llm_provider import LlmError, LlmProvider
from .prompts import SYSTEM_PROMPT, build_user_prompt

log = get_logger(__name__)

_TYPE_MAP = {
    "purchase_order": DocumentType.PURCHASE_ORDER,
    "invoice": DocumentType.INVOICE,
    "goods_receipt_note": DocumentType.GOODS_RECEIPT_NOTE,
}


def parse_json(raw: str) -> dict:
    """健壮的 JSON 解析：剥离代码块，必要时截取首个 JSON 对象。"""
    raw = (raw or "").strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```$", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LlmError("无法从 LLM 输出解析出 JSON 对象") from exc
    raise LlmError("LLM 输出中未找到 JSON 对象")


def schema_to_result(schema: DocumentSchema, raw_text: str = "") -> ExtractionResult:
    dt = _TYPE_MAP[schema.document_type]
    data = _build_entity(dt, schema)
    # 只保留「当前文档类型适用」的缺失字段，避免其它类型的字段拉低完整度参考值。
    applicable_missing = filter_applicable_missing_fields(
        schema.document_type, schema.missing_fields
    )
    confidence = compute_completeness(schema.document_type, schema.missing_fields)
    return ExtractionResult(
        document_type=dt,
        data=data,
        evidence=schema.evidence or {},
        method=ExtractionMethod.AI,
        confidence=confidence,
        missing_fields=applicable_missing,
        needs_review=schema.needs_review or [],
        raw_text=raw_text,
    )


def _build_entity(dt: DocumentType, s: DocumentSchema):
    if dt == DocumentType.PURCHASE_ORDER:
        return PurchaseOrder(
            po_number=normalize_item_no(s.document_number),
            order_date=normalize_date(s.document_date),
            supplier_name=normalize_supplier(s.supplier_name),
            supplier_tax_no=normalize_tax_no(s.supplier_tax_no),
            buyer_name=normalize_supplier(s.buyer_name),
            buyer_tax_no=normalize_tax_no(s.buyer_tax_no),
            total_amount=quantize_money(parse_decimal(s.total_amount)),
            lines=[_to_trade_line(li) for li in s.line_items],
        )
    if dt == DocumentType.INVOICE:
        return Invoice(
            invoice_code=normalize_item_no(s.document_code),
            invoice_number=normalize_item_no(s.document_number),
            invoice_date=normalize_date(s.document_date),
            seller_name=normalize_supplier(s.supplier_name),
            seller_tax_no=normalize_tax_no(s.supplier_tax_no),
            buyer_name=normalize_supplier(s.buyer_name),
            buyer_tax_no=normalize_tax_no(s.buyer_tax_no),
            po_number=normalize_item_no(s.related_po_number),
            total_amount=quantize_money(parse_decimal(s.total_amount)),
            lines=[_to_trade_line(li) for li in s.line_items],
        )
    return GoodsReceiptNote(
        grn_number=normalize_item_no(s.document_number),
        po_number=normalize_item_no(s.related_po_number),
        receipt_date=normalize_date(s.document_date),
        supplier_name=normalize_supplier(s.supplier_name),
        supplier_tax_no=normalize_tax_no(s.supplier_tax_no),
        lines=[_to_grn_line(li) for li in s.line_items],
    )


def _to_trade_line(li) -> TradeLine:
    return TradeLine(
        item_no=normalize_item_no(li.item_no),
        name=normalize_name(li.name),
        spec=normalize_name(li.spec),
        unit=normalize_unit(li.unit),
        quantity=quantize_qty(parse_decimal(li.quantity)),
        unit_price=quantize_money(parse_decimal(li.unit_price)),
        amount=quantize_money(parse_decimal(li.amount)),
        tax_rate=parse_tax_rate(li.tax_rate),
        tax_amount=quantize_money(parse_decimal(li.tax_amount)),
        line_total=quantize_money(parse_decimal(li.line_total)),
        source="ai",
    )


def _to_grn_line(li) -> GrnLine:
    return GrnLine(
        item_no=normalize_item_no(li.item_no),
        name=normalize_name(li.name),
        spec=normalize_name(li.spec),
        unit=normalize_unit(li.unit),
        planned_qty=quantize_qty(parse_decimal(li.planned_qty)),
        received_qty=quantize_qty(parse_decimal(li.received_qty)),
        source="ai",
    )


def extract_with_llm(text: str, provider: LlmProvider) -> ExtractionResult:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(text)},
    ]
    raw = provider.chat(messages, temperature=0.0)
    obj = parse_json(raw)
    schema = validate_document_schema(obj)
    return schema_to_result(schema, raw_text=text)


def extract_with_llm_retry(
    text: str, provider: LlmProvider, max_retries: int = 2
) -> ExtractionResult:
    """有限次数重试；记录失败原因，最终失败抛出 LlmError。"""
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return extract_with_llm(text, provider)
        except (LlmError, ValidationError, ValueError, KeyError) as exc:
            last_err = exc
            log.warning("AI 提取第 %d/%d 次失败：%s", attempt + 1, max_retries + 1, exc)
    raise LlmError(f"AI 结构化提取失败（已重试 {max_retries} 次）：{last_err}")
