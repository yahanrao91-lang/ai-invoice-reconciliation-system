"""三单匹配引擎：供应商、订单、商品、数量、单价、金额核对与重复发票识别。

系统输出的是对账审核建议，不是付款授权，也不做税务真伪查验。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from ..anomalies import Anomaly, Severity
from ..config import BusinessRules
from ..models import (
    GoodsReceiptNote,
    GrnLine,
    Invoice,
    PurchaseOrder,
    TradeLine,
)
from ..processing.standardize import CENTS, quantize_money
from .aliases import AliasRegistry
from .validate import _close


@dataclass
class LineMatch:
    """发票行与采购订单、收货记录的匹配结果。"""

    invoice_number: str
    item_no: str | None
    name: str | None
    po_item_no: str | None
    po_name: str | None
    match_basis: str          # item_no / name_spec / name_only / alias / none
    po_qty: Decimal | None
    received_qty: Decimal | None
    invoice_qty: Decimal | None
    po_price: Decimal | None
    invoice_price: Decimal | None
    status: str               # 匹配一致 / 数量差异 / 价格差异 / 供应商不一致 / 待人工确认
    anomaly_codes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "invoice_number": self.invoice_number,
            "item_no": self.item_no,
            "name": self.name,
            "po_item_no": self.po_item_no,
            "po_name": self.po_name,
            "match_basis": self.match_basis,
            "po_qty": None if self.po_qty is None else str(self.po_qty),
            "received_qty": None if self.received_qty is None else str(self.received_qty),
            "invoice_qty": None if self.invoice_qty is None else str(self.invoice_qty),
            "po_price": None if self.po_price is None else str(self.po_price),
            "invoice_price": None if self.invoice_price is None else str(self.invoice_price),
            "status": self.status,
            "anomaly_codes": self.anomaly_codes,
        }


@dataclass
class MatchResult:
    """单张采购订单的三单匹配结果。"""

    po_number: str | None
    invoice_numbers: list[str] = field(default_factory=list)
    grn_numbers: list[str] = field(default_factory=list)
    line_matches: list[LineMatch] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)

    def summary(self) -> dict:
        counts = {
            "匹配一致": 0, "存在数量差异": 0, "存在价格差异": 0,
            "供应商信息不一致": 0, "待人工确认": 0,
        }
        for lm in self.line_matches:
            key = lm.status
            counts[key] = counts.get(key, 0) + 1
        return counts


def _match_po_line(inv_line: TradeLine, po: PurchaseOrder, aliases: AliasRegistry | None):
    """返回 (po_line, basis)。优先商品编号，其次名称+规格，再次别名，最后仅名称。"""
    if inv_line.item_no:
        for pl in po.lines:
            if pl.item_no and pl.item_no == inv_line.item_no:
                return pl, "item_no"
    if inv_line.name:
        for pl in po.lines:
            if pl.name and pl.name == inv_line.name and (pl.spec or "") == (inv_line.spec or ""):
                return pl, "name_spec"
    if aliases is not None and inv_line.name:
        key = aliases.resolve(inv_line.name)
        for pl in po.lines:
            if pl.name and aliases.resolve(pl.name) == key:
                return pl, "alias"
    if inv_line.name:
        for pl in po.lines:
            if pl.name and pl.name == inv_line.name:
                return pl, "name_only"
    return None, "none"


def _grn_received_map(grns: list[GoodsReceiptNote]) -> dict[str, Decimal]:
    """汇总每件商品的累计实收数量（同时按商品编号与名称聚合，便于别名/缺号场景查找）。"""
    m: dict[str, Decimal] = {}
    for grn in grns:
        for gl in grn.lines:
            for key in (gl.item_no, gl.name):
                if not key:
                    continue
                m[key] = m.get(key, Decimal(0)) + (gl.received_qty or Decimal(0))
    return m


def _lookup_received(
    inv_line: TradeLine, rmap: dict[str, Decimal], aliases: AliasRegistry | None
) -> tuple[Decimal | None, str]:
    if inv_line.item_no and inv_line.item_no in rmap:
        return rmap[inv_line.item_no], "item_no"
    if inv_line.name and inv_line.name in rmap:
        return rmap[inv_line.name], "name"
    if aliases is not None and inv_line.name:
        key = aliases.resolve(inv_line.name)
        for k in rmap:
            if aliases.resolve(k) == key:
                return rmap[k], "alias"
    return None, "none"


def _item_key(ln: TradeLine, aliases: AliasRegistry | None) -> str | None:
    """跨发票聚合用的商品键：优先商品编号，其次名称（含别名解析）。"""
    if ln.item_no:
        return ln.item_no
    if ln.name:
        return (aliases.resolve(ln.name) if aliases else ln.name) or None
    return None


def _received_for_key(
    key: str, rmap: dict[str, Decimal], aliases: AliasRegistry | None
) -> Decimal | None:
    """按聚合键查找累计实收数量。"""
    if key in rmap:
        return rmap[key]
    if aliases is not None:
        for k in rmap:
            if aliases.resolve(k) == key:
                return rmap[k]
    return None


def _supplier_check(
    po: PurchaseOrder, invoices: list[Invoice], grns: list[GoodsReceiptNote]
) -> list[Anomaly]:
    issues: list[Anomaly] = []
    po_name, po_tax = po.supplier_name, po.supplier_tax_no

    for inv in invoices:
        if inv.seller_name and po_name and inv.seller_name != po_name:
            issues.append(
                Anomaly(
                    "SUPPLIER_NAME_MISMATCH", Severity.HIGH,
                    f"发票销售方与采购订单供应商名称不一致：发票={inv.seller_name}，订单={po_name}",
                    "invoice", inv.invoice_number or "", "seller_name", "",
                )
            )
        if inv.seller_tax_no and po_tax and inv.seller_tax_no != po_tax:
            issues.append(
                Anomaly(
                    "SUPPLIER_TAX_MISMATCH", Severity.HIGH,
                    f"发票销售方税号与采购订单供应商税号不一致：发票={inv.seller_tax_no}，订单={po_tax}",
                    "invoice", inv.invoice_number or "", "seller_tax_no", "",
                )
            )

    for grn in grns:
        if grn.supplier_name and po_name and grn.supplier_name != po_name:
            issues.append(
                Anomaly(
                    "SUPPLIER_NAME_MISMATCH", Severity.HIGH,
                    f"收货记录供应商与采购订单供应商名称不一致：收货={grn.supplier_name}，订单={po_name}",
                    "grn", grn.grn_number or "", "supplier_name", "",
                )
            )
        if grn.supplier_tax_no and po_tax and grn.supplier_tax_no != po_tax:
            issues.append(
                Anomaly(
                    "SUPPLIER_TAX_MISMATCH", Severity.HIGH,
                    f"收货记录供应商税号与采购订单供应商税号不一致：收货={grn.supplier_tax_no}，订单={po_tax}",
                    "grn", grn.grn_number or "", "supplier_tax_no", "",
                )
            )
    return issues


def _invoice_key(inv: Invoice) -> tuple | None:
    """重复发票识别键。"""
    if inv.invoice_number:
        return ("num", inv.invoice_number)
    return None


def run_matching_for_po(
    po: PurchaseOrder,
    invoices: list[Invoice],
    grns: list[GoodsReceiptNote],
    rules: BusinessRules,
    aliases: AliasRegistry | None = None,
    seen_invoice_keys: set[tuple] | None = None,
) -> MatchResult:
    """对一张采购订单执行三单匹配。"""
    seen = seen_invoice_keys if seen_invoice_keys is not None else set()
    result = MatchResult(
        po_number=po.po_number,
        invoice_numbers=[i.invoice_number or "" for i in invoices],
        grn_numbers=[g.grn_number or "" for g in grns],
    )

    result.anomalies.extend(_supplier_check(po, invoices, grns))
    rmap = _grn_received_map(grns)
    reported_over_keys: set[str] = set()

    for inv in invoices:
        # 重复发票检查
        key = _invoice_key(inv)
        if key:
            if key in seen:
                result.anomalies.append(
                    Anomaly(
                        "DUPLICATE_INVOICE", Severity.CRITICAL,
                        f"重复发票：发票号码 {inv.invoice_number} 已登记",
                        "invoice", inv.invoice_number or "", "invoice_number", "",
                    )
                )
            else:
                seen.add(key)

        for idx, ln in enumerate(inv.lines):
            po_line, basis = _match_po_line(ln, po, aliases)
            received_qty, recv_basis = _lookup_received(ln, rmap, aliases)
            codes: list[str] = []

            if po_line is None:
                result.anomalies.append(
                    Anomaly(
                        "ITEM_NOT_IN_PO", Severity.MEDIUM,
                        f"发票商品「{ln.name or ln.item_no or ''}」在采购订单中找不到对应项，待人工确认",
                        "invoice", inv.invoice_number or "", "name", "",
                    )
                )
                codes.append("ITEM_NOT_IN_PO")

            # 数量核对
            if received_qty is None and ln.quantity is not None:
                result.anomalies.append(
                    Anomaly(
                        "ITEM_NO_GRN", Severity.HIGH,
                        f"发票商品「{ln.name or ln.item_no or ''}」没有对应收货记录",
                        "invoice", inv.invoice_number or "", "name", "",
                    )
                )
                codes.append("ITEM_NO_GRN")
            else:
                if ln.quantity is not None and received_qty is not None and ln.quantity > received_qty:
                    result.anomalies.append(
                        Anomaly(
                            "QTY_OVER_RECEIPT", Severity.HIGH,
                            f"发票数量 {ln.quantity} 超过实际收货数量 {received_qty}（{ln.name or ln.item_no or ''}）",
                            "invoice", inv.invoice_number or "", "quantity",
                            f"invoice_qty={ln.quantity}, received_qty={received_qty}",
                        )
                    )
                    codes.append("QTY_OVER_RECEIPT")
                    reported_over_keys.add(_item_key(ln, aliases) or "")

                if (
                    po_line is not None
                    and po_line.quantity is not None
                    and received_qty is not None
                    and received_qty > po_line.quantity
                    and not rules.allow_over_receipt
                ):
                    result.anomalies.append(
                        Anomaly(
                            "QTY_OVER_PO", Severity.HIGH,
                            f"实际收货数量 {received_qty} 超过采购订单数量 {po_line.quantity}（{ln.name or ln.item_no or ''}）",
                            "grn", result.grn_numbers[0] if result.grn_numbers else "", "received_qty",
                            f"received_qty={received_qty}, po_qty={po_line.quantity}",
                        )
                    )
                    codes.append("QTY_OVER_PO")

            # 单价核对
            if (
                po_line is not None
                and po_line.unit_price is not None
                and ln.unit_price is not None
                and not _close(ln.unit_price, po_line.unit_price, rules.price_tolerance_rate)
            ):
                result.anomalies.append(
                    Anomaly(
                        "PRICE_DIFF", Severity.HIGH,
                        f"单价不一致：采购订单 {po_line.unit_price}，发票 {ln.unit_price}（{ln.name or ln.item_no or ''}）",
                        "invoice", inv.invoice_number or "", "unit_price",
                        f"po_price={po_line.unit_price}, invoice_price={ln.unit_price}",
                    )
                )
                codes.append("PRICE_DIFF")

            # 计量单位核对（标准化后仍不一致 → 提示人工确认）
            if (
                po_line is not None
                and po_line.unit is not None
                and ln.unit is not None
                and ln.unit != po_line.unit
            ):
                result.anomalies.append(
                    Anomaly(
                        "UNIT_MISMATCH", Severity.MEDIUM,
                        f"计量单位不一致：采购订单 {po_line.unit}，发票 {ln.unit}（{ln.name or ln.item_no or ''}）",
                        "invoice", inv.invoice_number or "", "unit", "",
                    )
                )
                codes.append("UNIT_MISMATCH")

            status = _classify_status(codes, basis, po_line)

            result.line_matches.append(
                LineMatch(
                    invoice_number=inv.invoice_number or "",
                    item_no=ln.item_no,
                    name=ln.name,
                    po_item_no=po_line.item_no if po_line else None,
                    po_name=po_line.name if po_line else None,
                    match_basis=basis,
                    po_qty=po_line.quantity if po_line else None,
                    received_qty=received_qty,
                    invoice_qty=ln.quantity,
                    po_price=po_line.unit_price if po_line else None,
                    invoice_price=ln.unit_price,
                    status=status,
                    anomaly_codes=codes,
                )
            )

    # 跨发票累计开票数量核对（分批开票：防止多张发票合计超收漏判）
    if len(invoices) > 1:
        _check_aggregate_qty(result, invoices, rmap, aliases, rules, reported_over_keys)

    # 订单金额 vs 发票金额
    if po.total_amount is not None and invoices:
        inv_sum = sum((i.total_amount or Decimal(0)) for i in invoices)
        if inv_sum:
            mismatch = not _close(inv_sum, po.total_amount, rules.amount_tolerance)
            over_invoiced = inv_sum > po.total_amount
            # 允许分批开票时，仅在累计开票金额超过订单金额时告警；否则任何偏差都告警
            should_flag = mismatch and (not rules.allow_partial_invoice or over_invoiced)
            if should_flag:
                result.anomalies.append(
                    Anomaly(
                        "PO_INVOICE_AMOUNT_DIFF", Severity.HIGH,
                        f"采购订单金额 {po.total_amount} 与发票合计 {quantize_money(inv_sum)} 存在差异",
                        "po", po.po_number or "", "total_amount", "",
                    )
                )

    return result


def _classify_status(codes: list[str], basis: str, po_line: TradeLine | None) -> str:
    if "ITEM_NOT_IN_PO" in codes or basis == "none":
        return "待人工确认"
    if "QTY_OVER_RECEIPT" in codes or "QTY_OVER_PO" in codes or "ITEM_NO_GRN" in codes:
        return "存在数量差异"
    if "PRICE_DIFF" in codes:
        return "存在价格差异"
    if "UNIT_MISMATCH" in codes:
        return "待人工确认"
    return "匹配一致"


def _check_aggregate_qty(
    result: MatchResult,
    invoices: list[Invoice],
    rmap: dict[str, Decimal],
    aliases: AliasRegistry | None,
    rules: BusinessRules,
    reported_over_keys: set[str],
) -> None:
    """多张发票分批开票时，按商品汇总开票数量与实收数量核对，防止合计超收漏判。"""
    agg: dict[str, Decimal] = {}
    key_names: dict[str, str] = {}
    for inv in invoices:
        for ln in inv.lines:
            key = _item_key(ln, aliases)
            if not key:
                continue
            agg[key] = agg.get(key, Decimal(0)) + (ln.quantity or Decimal(0))
            key_names.setdefault(key, ln.name or ln.item_no or key)

    for key, qty in agg.items():
        received = _received_for_key(key, rmap, aliases)
        if received is None or qty <= received or key in reported_over_keys:
            continue
        result.anomalies.append(
            Anomaly(
                "QTY_OVER_RECEIPT", Severity.HIGH,
                f"发票累计开票数量 {qty} 超过实际收货数量 {received}（{key_names.get(key, key)}）",
                "invoice", key, "quantity", f"aggregate_invoice_qty={qty}, received_qty={received}",
            )
        )
        # 将聚合级数量差异同步到该商品的匹配行状态
        for lm in result.line_matches:
            if lm.item_no == key or lm.name == key:
                if "QTY_OVER_RECEIPT" not in lm.anomaly_codes:
                    lm.anomaly_codes.append("QTY_OVER_RECEIPT")
                    lm.status = _classify_status(lm.anomaly_codes, lm.match_basis, None)


@dataclass
class TaskMatchOutcome:
    """整组文档的匹配结果。"""

    per_po: list[MatchResult] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    orphan_invoices: list[str] = field(default_factory=list)
    orphan_grns: list[str] = field(default_factory=list)

    @property
    def line_matches(self) -> list[LineMatch]:
        out: list[LineMatch] = []
        for r in self.per_po:
            out.extend(r.line_matches)
        return out

    @property
    def summary(self) -> dict:
        counts = {
            "匹配一致": 0, "存在数量差异": 0, "存在价格差异": 0,
            "供应商信息不一致": 0, "待人工确认": 0,
        }
        for r in self.per_po:
            s = r.summary()
            for k, v in s.items():
                counts[k] = counts.get(k, 0) + v
        return counts


def match_task(
    purchase_orders: list[PurchaseOrder],
    invoices: list[Invoice],
    grns: list[GoodsReceiptNote],
    rules: BusinessRules,
    aliases: AliasRegistry | None = None,
    seen_invoice_keys: set[tuple] | None = None,
) -> TaskMatchOutcome:
    """整组文档三单匹配：按采购订单编号分组。"""
    seen = seen_invoice_keys if seen_invoice_keys is not None else set()
    outcome = TaskMatchOutcome()

    po_by_number: dict[str, PurchaseOrder] = {}
    for po in purchase_orders:
        if po.po_number:
            po_by_number[po.po_number] = po

    # 无订单可关联的发票 / 收货
    for inv in invoices:
        if not inv.po_number:
            outcome.anomalies.append(
                Anomaly(
                    "PO_NUMBER_MISSING", Severity.MEDIUM,
                    f"发票 {inv.invoice_number or ''} 缺少关联采购订单号",
                    "invoice", inv.invoice_number or "", "po_number", "",
                )
            )
            outcome.orphan_invoices.append(inv.invoice_number or "")
        elif inv.po_number not in po_by_number:
            outcome.anomalies.append(
                Anomaly(
                    "PO_NOT_FOUND", Severity.HIGH,
                    f"发票 {inv.invoice_number or ''} 关联的采购订单 {inv.po_number} 不存在",
                    "invoice", inv.invoice_number or "", "po_number", "",
                )
            )
            outcome.orphan_invoices.append(inv.invoice_number or "")

    for grn in grns:
        if not grn.po_number:
            outcome.anomalies.append(
                Anomaly(
                    "PO_NUMBER_MISSING", Severity.MEDIUM,
                    f"收货记录 {grn.grn_number or ''} 缺少关联采购订单号",
                    "grn", grn.grn_number or "", "po_number", "",
                )
            )
            outcome.orphan_grns.append(grn.grn_number or "")
        elif grn.po_number not in po_by_number:
            outcome.anomalies.append(
                Anomaly(
                    "PO_NOT_FOUND", Severity.HIGH,
                    f"收货记录 {grn.grn_number or ''} 关联的采购订单 {grn.po_number} 不存在",
                    "grn", grn.grn_number or "", "po_number", "",
                )
            )
            outcome.orphan_grns.append(grn.grn_number or "")

    for po_number, po in po_by_number.items():
        po_invoices = [i for i in invoices if i.po_number == po_number]
        po_grns = [g for g in grns if g.po_number == po_number]
        if po_invoices or po_grns:
            r = run_matching_for_po(po, po_invoices, po_grns, rules, aliases, seen)
            outcome.per_po.append(r)
            outcome.anomalies.extend(r.anomalies)

    return outcome
