"""文档类型字段适用性规则与字段完整度参考值计算。

三种单据（采购订单 PO / 供应商发票 Invoice / 收货记录 GRN）适用的业务字段不同。
AI 输出可能把其它单据类型的字段错误列入 missing_fields（例如把 PO/发票的
total_amount、unit_price 记到 GRN 上），导致完整度参考值被错误拉低。

本模块提供：

- :func:`filter_applicable_missing_fields`：按文档类型过滤缺失字段，只保留
  「适用于当前类型」的缺失项。
- :func:`compute_completeness`：基于过滤后的适用缺失字段数量计算字段完整度参考值。

过滤采用「白名单 + 已知字段」策略：只过滤「确定不属于当前类型」的字段；无法识别的
字段一律保留，绝不静默丢弃真正重要的信息。
"""
from __future__ import annotations

import re
from typing import Any

# 行级字段路径（PO / Invoice 共用的采购交易行）
_TRADE_LINE_FIELDS = frozenset({
    "line_items.item_no",
    "line_items.name",
    "line_items.spec",
    "line_items.unit",
    "line_items.quantity",
    "line_items.unit_price",
    "line_items.amount",
    "line_items.tax_rate",
    "line_items.tax_amount",
    "line_items.line_total",
})

# 行级字段路径（GRN 收货记录行：区分计划收货数量与实际收货数量）
_GRN_LINE_FIELDS = frozenset({
    "line_items.item_no",
    "line_items.name",
    "line_items.spec",
    "line_items.unit",
    "line_items.planned_qty",
    "line_items.received_qty",
})

# 各文档类型适用字段（顶层字段 + line_items.* 嵌套字段）
APPLICABLE_FIELDS: dict[str, frozenset[str]] = {
    "purchase_order": frozenset({
        "document_number",
        "document_date",
        "supplier_name",
        "supplier_tax_no",
        "buyer_name",
        "buyer_tax_no",
        "total_amount",
    }) | _TRADE_LINE_FIELDS,
    "invoice": frozenset({
        "document_number",
        "document_code",
        "document_date",
        "related_po_number",
        "supplier_name",
        "supplier_tax_no",
        "buyer_name",
        "buyer_tax_no",
        "total_amount",
    }) | _TRADE_LINE_FIELDS,
    "goods_receipt_note": frozenset({
        "document_number",
        "document_date",
        "related_po_number",
        "supplier_name",
        "supplier_tax_no",
    }) | _GRN_LINE_FIELDS,
}

# 所有已知字段的并集：用于区分「已知但不适用」与「无法识别」。
_ALL_KNOWN_FIELDS = frozenset().union(*APPLICABLE_FIELDS.values())

_LINE_PATH_RE = re.compile(r"^line_items(?:\[\d+\]|\[\*\])?\.(.+)$")

# 完整度参考值的下限与步长（沿用原启发式公式）
_COMPLETENESS_FLOOR = 0.2
_COMPLETENESS_STEP = 0.1


def _doc_type_value(document_type: Any) -> str:
    """兼容传入 DocumentType 枚举或字符串。"""
    return getattr(document_type, "value", document_type)


def canonical_field(path: str) -> str:
    """把 line_items[0].field / line_items[*].field / line_items.field 统一为
    line_items.field，便于与适用字段集合比较。"""
    p = (path or "").strip()
    m = _LINE_PATH_RE.match(p)
    if m:
        return f"line_items.{m.group(1).strip()}"
    return p


def filter_applicable_missing_fields(
    document_type: Any, missing_fields: list[str] | None
) -> list[str]:
    """按文档类型过滤缺失字段，返回适用于当前类型的缺失字段列表。

    规则：

    - 规范化嵌套路径（line_items[0].x -> line_items.x）。
    - 字段属于当前类型适用集合 -> 保留。
    - 字段属于其它类型的已知字段 -> 过滤（例如 GRN 的 total_amount / unit_price）。
    - 无法识别的字段 -> 保留（绝不静默丢弃，避免漏掉重要信息）。
    """
    if not missing_fields:
        return []
    applicable = APPLICABLE_FIELDS.get(_doc_type_value(document_type))
    if applicable is None:
        # 未知文档类型：不做任何过滤，全部保留。
        return list(missing_fields)
    result: list[str] = []
    for field in missing_fields:
        canon = canonical_field(field)
        if canon in applicable:
            result.append(field)
        elif canon in _ALL_KNOWN_FIELDS:
            continue
        else:
            result.append(field)
    return result


def compute_completeness(
    document_type: Any, missing_fields: list[str] | None
) -> float:
    """基于「过滤后的适用缺失字段数量」计算字段完整度参考值。

    数值 = max(0.2, 1.0 - 0.1 × 适用缺失字段数)。

    该值只是缺失字段数量的启发式参考，**不是 AI 模型真实概率置信度，也不代表票据
    真实性**；判断口径始终基于当前文档类型的适用字段。
    """
    filtered = filter_applicable_missing_fields(document_type, missing_fields)
    value = 1.0 - _COMPLETENESS_STEP * len(filtered)
    return max(_COMPLETENESS_FLOOR, round(value, 2))
