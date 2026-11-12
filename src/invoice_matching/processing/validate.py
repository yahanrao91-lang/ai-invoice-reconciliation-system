"""业务数据验证：金额 = 数量×单价、税额、价税合计、总金额一致（全部 Decimal）。"""
from __future__ import annotations

from decimal import Decimal

from ..anomalies import Anomaly, Severity
from ..config import BusinessRules
from ..models import Invoice, PurchaseOrder, TradeLine
from .standardize import CENTS, quantize_money


def compute_line_amount(qty: Decimal | None, price: Decimal | None) -> Decimal | None:
    if qty is None or price is None:
        return None
    return quantize_money(qty * price)


def compute_tax_amount(amount: Decimal | None, tax_rate: Decimal | None) -> Decimal | None:
    if amount is None or tax_rate is None:
        return None
    return quantize_money(amount * tax_rate)


def compute_line_total(amount: Decimal | None, tax_amount: Decimal | None) -> Decimal | None:
    if amount is None or tax_amount is None:
        return None
    return quantize_money(amount + tax_amount)


def _close(a: Decimal, b: Decimal, rate: Decimal) -> bool:
    allowed = max(CENTS, abs(b) * rate)
    return abs(a - b) <= allowed


def validate_trade_line(line: TradeLine, rules: BusinessRules, ref: str) -> list[Anomaly]:
    issues: list[Anomaly] = []

    expected_amount = compute_line_amount(line.quantity, line.unit_price)
    if line.amount is not None and expected_amount is not None and not _close(line.amount, expected_amount, rules.amount_tolerance):
        issues.append(
            Anomaly(
                "LINE_AMOUNT_MISMATCH", Severity.HIGH,
                f"商品金额计算不一致：数量×单价={expected_amount}，单据金额={line.amount}",
                "line", ref, "amount", f"quantity={line.quantity}, unit_price={line.unit_price}",
            )
        )

    expected_tax = compute_tax_amount(line.amount, line.tax_rate)
    if line.tax_amount is not None and expected_tax is not None and not _close(line.tax_amount, expected_tax, rules.amount_tolerance):
        issues.append(
            Anomaly(
                "LINE_TAX_MISMATCH", Severity.HIGH,
                f"税额计算不一致：金额×税率={expected_tax}，单据税额={line.tax_amount}",
                "line", ref, "tax_amount", f"amount={line.amount}, tax_rate={line.tax_rate}",
            )
        )

    expected_total = compute_line_total(line.amount, line.tax_amount)
    if line.line_total is not None and expected_total is not None and not _close(line.line_total, expected_total, rules.amount_tolerance):
        issues.append(
            Anomaly(
                "LINE_TOTAL_MISMATCH", Severity.HIGH,
                f"价税合计不一致：金额+税额={expected_total}，单据价税合计={line.line_total}",
                "line", ref, "line_total", "",
            )
        )

    return issues


def validate_po(po: PurchaseOrder, rules: BusinessRules) -> list[Anomaly]:
    issues: list[Anomaly] = []
    ref = po.po_number or ""
    for i, ln in enumerate(po.lines):
        issues.extend(validate_trade_line(ln, rules, f"{ref} 行{i + 1}"))
    if po.total_amount is not None and po.lines and all(ln.line_total is not None for ln in po.lines):
        line_sum = sum((ln.line_total for ln in po.lines), Decimal(0))
        line_sum = quantize_money(line_sum)
        if not _close(line_sum, po.total_amount, rules.amount_tolerance):
            issues.append(
                Anomaly(
                    "PO_TOTAL_MISMATCH", Severity.HIGH,
                    f"采购订单总金额与明细价税合计不一致：明细合计={line_sum}，总金额={po.total_amount}",
                    "po", ref, "total_amount", "",
                )
            )
    return issues


def validate_invoice(inv: Invoice, rules: BusinessRules) -> list[Anomaly]:
    issues: list[Anomaly] = []
    ref = inv.invoice_number or ""
    for i, ln in enumerate(inv.lines):
        issues.extend(validate_trade_line(ln, rules, f"{ref} 行{i + 1}"))
    if inv.total_amount is not None and inv.lines and all(ln.line_total is not None for ln in inv.lines):
        line_sum = sum((ln.line_total for ln in inv.lines), Decimal(0))
        line_sum = quantize_money(line_sum)
        if not _close(line_sum, inv.total_amount, rules.amount_tolerance):
            issues.append(
                Anomaly(
                    "INVOICE_TOTAL_MISMATCH", Severity.HIGH,
                    f"发票合计金额与明细价税合计不一致：明细合计={line_sum}，合计金额={inv.total_amount}",
                    "invoice", ref, "total_amount", "",
                )
            )
    return issues
