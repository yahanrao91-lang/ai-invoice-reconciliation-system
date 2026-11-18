"""AI 提取、JSON Schema 校验、缺失字段处理、离线解析测试。"""
import json
from decimal import Decimal

import pytest

from invoice_matching.ai.extractor import (
    extract_with_llm,
    extract_with_llm_retry,
    parse_json,
    schema_to_result,
)
from invoice_matching.ai.field_applicability import (
    APPLICABLE_FIELDS,
    canonical_field,
    compute_completeness,
    filter_applicable_missing_fields,
)
from invoice_matching.ai.llm_provider import LlmError
from invoice_matching.ai.offline_parser import parse_offline
from invoice_matching.models import DocumentType, ExtractionMethod
from invoice_matching.schemas import validate_document_schema


class FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, temperature=0.0):
        self.calls += 1
        return self.responses.pop(0)


def test_parse_json_strips_fences():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_parse_json_extracts_embedded_object():
    assert parse_json('前缀说明 {"a": 1} 后缀') == {"a": 1}


def test_validate_document_schema_valid():
    s = validate_document_schema(
        {"document_type": "invoice", "document_number": "INV-1",
         "line_items": [{"name": "轴承", "quantity": 10.0}]}
    )
    assert s.document_type == "invoice"
    assert s.document_number == "INV-1"
    assert s.line_items[0].name == "轴承"


def test_validate_document_schema_invalid_type():
    with pytest.raises(Exception):
        validate_document_schema({"document_type": "unknown"})


def test_validate_document_schema_missing_fields_default_null():
    s = validate_document_schema({"document_type": "purchase_order"})
    assert s.document_number is None
    assert s.line_items == []


def test_extract_with_llm_ok():
    resp = json.dumps({
        "document_type": "purchase_order", "document_number": "PO-1",
        "supplier_name": "供应商A",
        "line_items": [{"name": "x", "quantity": 5, "unit_price": 10.0,
                        "amount": 50.0, "tax_rate": 0.13, "tax_amount": 6.5,
                        "line_total": 56.5}],
        "total_amount": 56.5, "missing_fields": [],
    })
    result = extract_with_llm("文本", FakeProvider([resp]))
    assert result.document_type == DocumentType.PURCHASE_ORDER
    assert result.data.po_number == "PO-1"
    assert result.data.lines[0].quantity == Decimal("5")
    assert result.data.lines[0].tax_rate == Decimal("0.13")
    assert result.method == ExtractionMethod.AI


def test_extract_with_llm_retry_then_success():
    provider = FakeProvider([
        "不是json",
        json.dumps({"document_type": "invoice", "document_number": "INV-1", "line_items": []}),
    ])
    result = extract_with_llm_retry("文本", provider, max_retries=2)
    assert result.data.invoice_number == "INV-1"
    assert provider.calls == 2


def test_extract_with_llm_retry_all_fail():
    provider = FakeProvider(["x", "y", "z"])
    with pytest.raises(LlmError):
        extract_with_llm_retry("文本", provider, max_retries=2)
    assert provider.calls == 3


def test_offline_parser_po(po_text):
    result = parse_offline(po_text)
    assert result.document_type == DocumentType.PURCHASE_ORDER
    assert result.data.po_number == "PO-TEST-001"
    assert result.data.supplier_name == "华东精密制造有限公司"
    assert result.data.lines[0].quantity == Decimal("100")
    assert result.data.lines[0].unit_price == Decimal("200.00")
    assert result.data.total_amount == Decimal("22600.00")
    assert result.method == ExtractionMethod.OFFLINE


def test_offline_parser_missing_field_nulls():
    text = "文档类型：采购订单（PO）\n订单日期：2026-01-01\n商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：\nITEM-1 | 商品 | | 件 | 1 | 2.00 | 2.00 | 13% | 0.26 | 2.26"
    result = parse_offline(text)
    assert result.data.po_number is None
    assert "采购订单编号" in result.missing_fields


# ---------------------------------------------------------------------------
# 文档类型字段适用性：GRN 不适用字段过滤 + 字段完整度参考值
# ---------------------------------------------------------------------------


def test_applicable_fields_covers_all_document_types():
    assert set(APPLICABLE_FIELDS) == {
        "purchase_order", "invoice", "goods_receipt_note",
    }
    grn = APPLICABLE_FIELDS["goods_receipt_note"]
    # GRN 不应包含 PO/发票的交易金额字段
    assert "total_amount" not in grn
    assert "line_items.quantity" not in grn
    assert "line_items.unit_price" not in grn
    assert "line_items.received_qty" in grn


def test_canonical_field_normalizes_line_item_paths():
    assert canonical_field("line_items[0].quantity") == "line_items.quantity"
    assert canonical_field("line_items[1].received_qty") == "line_items.received_qty"
    assert canonical_field("line_items[*].unit") == "line_items.unit"
    assert canonical_field("line_items.name") == "line_items.name"
    assert canonical_field("total_amount") == "total_amount"


def test_grn_filters_out_non_applicable_missing_fields():
    missing = [
        "document_code",
        "buyer_name",
        "buyer_tax_no",
        "total_amount",
        "line_items[0].quantity",
        "line_items[0].unit_price",
        "line_items[0].amount",
        "line_items[0].tax_rate",
        "line_items[0].tax_amount",
        "line_items[0].line_total",
    ]
    assert filter_applicable_missing_fields("goods_receipt_note", missing) == []


def test_grn_keeps_truly_missing_received_qty():
    missing = ["line_items[0].received_qty", "line_items[0].quantity", "total_amount"]
    filtered = filter_applicable_missing_fields("goods_receipt_note", missing)
    assert filtered == ["line_items[0].received_qty"]


def test_grn_completeness_is_1_0_when_all_applicable_fields_present():
    missing = [
        "document_code", "buyer_name", "total_amount",
        "line_items[0].quantity", "line_items[0].unit_price",
    ]
    assert compute_completeness("goods_receipt_note", missing) == 1.0


def test_grn_missing_received_qty_lowers_completeness():
    assert compute_completeness(
        "goods_receipt_note", ["line_items[0].received_qty"]
    ) == 0.9


def test_po_applicability_not_affected_by_grn_rules():
    missing = [
        "line_items[0].received_qty", "line_items[0].planned_qty",
        "total_amount", "buyer_name",
    ]
    filtered = filter_applicable_missing_fields("purchase_order", missing)
    assert filtered == ["total_amount", "buyer_name"]


def test_invoice_applicability_not_affected_by_grn_rules():
    missing = [
        "line_items[0].received_qty", "document_code",
        "related_po_number", "line_items[0].quantity",
    ]
    filtered = filter_applicable_missing_fields("invoice", missing)
    assert filtered == ["document_code", "related_po_number", "line_items[0].quantity"]


def test_unknown_missing_field_is_preserved_not_silently_dropped():
    assert filter_applicable_missing_fields(
        "goods_receipt_note", ["some_unknown_field"]
    ) == ["some_unknown_field"]


def test_schema_to_result_grn_filters_missing_and_keeps_review_evidence():
    s = validate_document_schema({
        "document_type": "goods_receipt_note",
        "document_number": "GRN-1",
        "related_po_number": "PO-1",
        "supplier_name": "供应商A",
        "line_items": [{"item_no": "I-1", "name": "轴承",
                        "planned_qty": 100, "received_qty": 95}],
        "missing_fields": ["document_code", "total_amount", "line_items[0].quantity"],
        "needs_review": ["收货数量与计划数量不符"],
        "evidence": {"document_number": "GRN-1"},
    })
    result = schema_to_result(s)
    assert result.missing_fields == []
    assert result.needs_review == ["收货数量与计划数量不符"]
    assert result.evidence == {"document_number": "GRN-1"}
    assert result.confidence == 1.0


def test_schema_to_result_grn_missing_received_qty_kept():
    s = validate_document_schema({
        "document_type": "goods_receipt_note",
        "document_number": "GRN-1",
        "line_items": [{"name": "轴承", "planned_qty": 100}],
        "missing_fields": ["line_items[0].received_qty", "total_amount"],
    })
    result = schema_to_result(s)
    assert "line_items[0].received_qty" in result.missing_fields
    assert "total_amount" not in result.missing_fields
    assert result.confidence == 0.9
