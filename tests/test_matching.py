"""三单匹配引擎与异常检测测试。"""
from decimal import Decimal

from invoice_matching.anomalies import Severity
from invoice_matching.models import (
    GoodsReceiptNote,
    GrnLine,
    Invoice,
    PurchaseOrder,
    TradeLine,
)
from invoice_matching.processing.aliases import AliasRegistry
from invoice_matching.processing.matching import match_task


def _trade(item_no, name, qty, price, spec=""):
    return TradeLine(item_no=item_no, name=name, spec=spec, unit="件",
                     quantity=Decimal(str(qty)), unit_price=Decimal(str(price)))


def _grn_line(item_no, name, received, spec=""):
    return GrnLine(item_no=item_no, name=name, spec=spec, unit="件",
                   planned_qty=Decimal(str(received)), received_qty=Decimal(str(received)))


def _po(number="PO-1", supplier="甲", tax="T1", lines=None, total=None):
    return PurchaseOrder(po_number=number, supplier_name=supplier, supplier_tax_no=tax,
                         buyer_name="买方", lines=lines or [], total_amount=total)


def _inv(number="INV-1", seller="甲", tax="T1", po="PO-1", lines=None, total=None):
    return Invoice(invoice_number=number, seller_name=seller, seller_tax_no=tax,
                   buyer_name="买方", po_number=po, lines=lines or [], total_amount=total)


def _grn(number="GRN-1", po="PO-1", supplier="甲", tax="T1", lines=None):
    return GoodsReceiptNote(grn_number=number, po_number=po, supplier_name=supplier,
                            supplier_tax_no=tax, lines=lines or [])


def _codes(outcome):
    return {a.code for a in outcome.anomalies}


def test_match_consistent(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv], [grn], rules)
    assert outcome.anomalies == []
    assert outcome.summary["匹配一致"] == 1


def test_supplier_name_and_tax_mismatch(rules):
    po = _po(supplier="甲公司", tax="T1")
    inv = _inv(seller="乙公司", tax="T2", lines=[_trade("ITEM-001", "轴承", 100, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv], [grn], rules)
    codes = _codes(outcome)
    assert "SUPPLIER_NAME_MISMATCH" in codes
    assert "SUPPLIER_TAX_MISMATCH" in codes


def test_invoice_qty_over_receipt(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 95)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "QTY_OVER_RECEIPT" in _codes(outcome)
    assert outcome.summary["存在数量差异"] == 1


def test_receipt_over_po_qty(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 105, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 105)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "QTY_OVER_PO" in _codes(outcome)


def test_price_diff(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 100, 220)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "PRICE_DIFF" in _codes(outcome)
    assert outcome.summary["存在价格差异"] == 1


def test_duplicate_invoice(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv1 = _inv(number="INV-1", lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv2 = _inv(number="INV-1", lines=[_trade("ITEM-001", "轴承", 100, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv1, inv2], [grn], rules)
    assert "DUPLICATE_INVOICE" in _codes(outcome)


def test_po_not_found_and_missing_number(rules):
    inv = _inv(po="PO-999", lines=[_trade("ITEM-001", "轴承", 100, 200)])
    outcome = match_task([], [inv], [], rules)
    assert "PO_NOT_FOUND" in _codes(outcome)

    inv2 = _inv(po=None, lines=[_trade("ITEM-001", "轴承", 100, 200)])
    outcome2 = match_task([], [inv2], [], rules)
    assert "PO_NUMBER_MISSING" in _codes(outcome2)


def test_item_not_in_po(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-999", "未知商品", 10, 5)])
    grn = _grn(lines=[_grn_line("ITEM-999", "未知商品", 10)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "ITEM_NOT_IN_PO" in _codes(outcome)
    assert outcome.summary["待人工确认"] == 1


def test_partial_receipt_no_anomaly(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 50, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 50)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "QTY_OVER_RECEIPT" not in _codes(outcome)
    assert "QTY_OVER_PO" not in _codes(outcome)


def test_alias_matching(rules):
    aliases = AliasRegistry()
    aliases.add_alias("不锈钢轴承", "轴承")
    po = _po(lines=[_trade("ITEM-001", "不锈钢轴承", 100, 200)])
    inv = _inv(lines=[TradeLine(item_no=None, name="轴承", spec="", unit="件",
                                quantity=Decimal("100"), unit_price=Decimal("200"))])
    grn = _grn(lines=[_grn_line("ITEM-001", "不锈钢轴承", 100)])
    outcome = match_task([po], [inv], [grn], rules, aliases=aliases)
    assert outcome.line_matches[0].match_basis == "alias"
    assert outcome.line_matches[0].status == "匹配一致"


def test_multi_grn_received_aggregated(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    grn1 = _grn(number="GRN-1", lines=[_grn_line("ITEM-001", "轴承", 50)])
    grn2 = _grn(number="GRN-2", lines=[_grn_line("ITEM-001", "轴承", 50)])
    outcome = match_task([po], [inv], [grn1, grn2], rules)
    assert outcome.anomalies == []
    assert outcome.line_matches[0].received_qty == Decimal("100")


def test_multi_line_items(rules):
    po = _po(lines=[
        _trade("ITEM-001", "轴承", 100, 200),
        _trade("ITEM-002", "阀体", 50, 400),
    ])
    inv = _inv(lines=[
        _trade("ITEM-001", "轴承", 100, 200),
        _trade("ITEM-002", "阀体", 50, 400),
    ])
    grn = _grn(lines=[
        _grn_line("ITEM-001", "轴承", 100),
        _grn_line("ITEM-002", "阀体", 50),
    ])
    outcome = match_task([po], [inv], [grn], rules)
    assert outcome.anomalies == []
    assert len(outcome.line_matches) == 2


def test_item_no_priority_over_name(rules):
    po = _po(lines=[_trade("ITEM-001", "原名A", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-001", "别名名称B", 100, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "原名A", 100)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "ITEM_NOT_IN_PO" not in _codes(outcome)
    assert outcome.line_matches[0].match_basis == "item_no"
    assert outcome.line_matches[0].status == "匹配一致"


def test_unit_mismatch(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[TradeLine(item_no="ITEM-001", name="轴承", spec="", unit="箱",
                                quantity=Decimal("100"), unit_price=Decimal("200"))])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "UNIT_MISMATCH" in _codes(outcome)
    assert outcome.line_matches[0].status == "待人工确认"


def test_partial_invoice_no_amount_diff(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)], total=Decimal("22600.00"))
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 50, 200)], total=Decimal("11300.00"))
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 50)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "PO_INVOICE_AMOUNT_DIFF" not in _codes(outcome)


def test_over_invoice_amount_diff(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)], total=Decimal("22600.00"))
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 100, 200)], total=Decimal("24000.00"))
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "PO_INVOICE_AMOUNT_DIFF" in _codes(outcome)


def test_partial_invoice_amount_diff_when_disallowed(rules):
    import dataclasses

    strict = dataclasses.replace(rules, allow_partial_invoice=False)
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)], total=Decimal("22600.00"))
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 50, 200)], total=Decimal("11300.00"))
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 50)])
    outcome = match_task([po], [inv], [grn], strict)
    assert "PO_INVOICE_AMOUNT_DIFF" in _codes(outcome)


def test_multi_invoice_aggregate_over_receipt(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv1 = _inv(number="INV-1", lines=[_trade("ITEM-001", "轴承", 60, 200)])
    inv2 = _inv(number="INV-2", lines=[_trade("ITEM-001", "轴承", 60, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv1, inv2], [grn], rules)
    assert "QTY_OVER_RECEIPT" in _codes(outcome)
    assert outcome.summary["存在数量差异"] == 2


def test_price_within_tolerance_not_flagged(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv = _inv(lines=[_trade("ITEM-001", "轴承", 100, 201)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv], [grn], rules)
    assert "PRICE_DIFF" not in _codes(outcome)


def test_distinct_invoices_no_false_duplicate(rules):
    po = _po(lines=[_trade("ITEM-001", "轴承", 100, 200)])
    inv1 = _inv(number="INV-1", lines=[_trade("ITEM-001", "轴承", 50, 200)])
    inv2 = _inv(number="INV-2", lines=[_trade("ITEM-001", "轴承", 50, 200)])
    grn = _grn(lines=[_grn_line("ITEM-001", "轴承", 100)])
    outcome = match_task([po], [inv1, inv2], [grn], rules)
    assert "DUPLICATE_INVOICE" not in _codes(outcome)
    assert len(outcome.line_matches) == 2
