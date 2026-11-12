"""Excel 对账报告内容测试：报告必须反映实际审核结果。"""
from decimal import Decimal

from openpyxl import load_workbook

from invoice_matching.anomalies import Anomaly, Severity
from invoice_matching.models import DocumentType, PurchaseOrder, TradeLine
from invoice_matching.report import generate_report


def _insert_doc(db, task_id):
    return db.insert_document({
        "task_id": task_id, "original_name": "a.pdf", "stored_name": "x_a.pdf",
        "stored_path": "/tmp/x_a.pdf", "file_hash": "hash1", "extension": ".pdf",
        "size_bytes": 10, "imported_at": "2026-01-01 00:00:00",
    })


def test_report_sheets_and_anomaly_content(db, tmp_path):
    tid = db.create_task("报告测试")
    doc_id = _insert_doc(db, tid)
    po = PurchaseOrder(
        po_number="PO-1", supplier_name="甲公司",
        total_amount=Decimal("226.00"),
        lines=[TradeLine(item_no="ITEM-1", name="轴承", quantity=Decimal("10"),
                         unit_price=Decimal("20"), amount=Decimal("200"),
                         tax_rate=Decimal("0.13"), tax_amount=Decimal("26"),
                         line_total=Decimal("226"))],
    )
    db.save_business_document(tid, doc_id, DocumentType.PURCHASE_ORDER, po)
    db.save_anomalies(tid, [Anomaly("QTY_OVER_RECEIPT", Severity.HIGH, "数量超过实收")])

    path = generate_report(tid, db, tmp_path)
    assert path.exists()

    wb = load_workbook(path)
    for sheet in ("对账总览", "采购订单明细", "三单匹配结果", "异常记录", "人工审核历史"):
        assert sheet in wb.sheetnames

    ws = wb["异常记录"]
    found = any(cell.value == "QTY_OVER_RECEIPT" for row in ws.iter_rows() for cell in row)
    assert found, "异常记录表必须包含实际异常代码"
