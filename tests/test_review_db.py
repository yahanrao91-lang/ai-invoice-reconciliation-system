"""SQLite 持久化、重复登记防护、人工修正记录测试。"""
import sqlite3
from decimal import Decimal

import pytest

from invoice_matching.anomalies import Anomaly, Severity
from invoice_matching.models import (
    DocumentType,
    ExtractionMethod,
    ExtractionResult,
    PurchaseOrder,
    TradeLine,
)
from invoice_matching.review import apply_correction, record_confirmation, record_correction


def _po() -> PurchaseOrder:
    return PurchaseOrder(
        po_number="PO-1", supplier_name="甲公司", buyer_name="买方",
        total_amount=Decimal("226.00"),
        lines=[TradeLine(item_no="ITEM-1", name="轴承", quantity=Decimal("10"),
                         unit_price=Decimal("20"), amount=Decimal("200"),
                         tax_rate=Decimal("0.13"), tax_amount=Decimal("26"),
                         line_total=Decimal("226"))],
    )


def _insert_doc(db, task_id, file_hash="abc"):
    return db.insert_document({
        "task_id": task_id, "original_name": "a.pdf", "stored_name": "x_a.pdf",
        "stored_path": "/tmp/x_a.pdf", "file_hash": file_hash, "extension": ".pdf",
        "size_bytes": 10, "imported_at": "2026-01-01 00:00:00",
    })


def test_task_and_document_persist(db):
    tid = db.create_task("测试任务")
    doc_id = _insert_doc(db, tid)
    assert tid > 0 and doc_id > 0
    assert db.get_document(doc_id)["original_name"] == "a.pdf"


def test_duplicate_hash_rejected(db):
    tid = db.create_task("t")
    _insert_doc(db, tid, file_hash="same")
    with pytest.raises(sqlite3.IntegrityError):
        _insert_doc(db, tid, file_hash="same")


def test_save_and_load_business_document(db):
    tid = db.create_task("t")
    doc_id = _insert_doc(db, tid)
    db.save_business_document(tid, doc_id, DocumentType.PURCHASE_ORDER, _po())
    biz = db.get_business_documents(tid)
    assert len(biz) == 1
    assert biz[0]["entity"].po_number == "PO-1"
    assert biz[0]["entity"].lines[0].name == "轴承"


def test_apply_correction_records_old_new_and_updates(db):
    tid = db.create_task("t")
    doc_id = _insert_doc(db, tid)
    db.save_business_document(tid, doc_id, DocumentType.PURCHASE_ORDER, _po())
    db.save_extraction(doc_id, ExtractionResult(
        document_type=DocumentType.PURCHASE_ORDER, data=_po(), method=ExtractionMethod.OFFLINE))

    err, rid = apply_correction(db, tid, doc_id, "supplier_name", "乙公司", "人工核对")
    assert err is None and rid is not None

    recs = db.get_review_records(tid)
    assert recs[0]["old_value"] == "甲公司"
    assert recs[0]["new_value"] == "乙公司"
    assert recs[0]["action"] == "correct"

    biz = db.get_business_documents(tid)
    assert biz[0]["entity"].supplier_name == "乙公司"


def test_apply_correction_line_quantity(db):
    tid = db.create_task("t")
    doc_id = _insert_doc(db, tid)
    db.save_business_document(tid, doc_id, DocumentType.PURCHASE_ORDER, _po())
    db.save_extraction(doc_id, ExtractionResult(
        document_type=DocumentType.PURCHASE_ORDER, data=_po(), method=ExtractionMethod.OFFLINE))
    err, _ = apply_correction(db, tid, doc_id, "lines[0].quantity", "12", "修正数量")
    assert err is None
    biz = db.get_business_documents(tid)
    assert biz[0]["entity"].lines[0].quantity == Decimal("12")


def test_confirmation_updates_anomaly_status(db):
    tid = db.create_task("t")
    ids = db.save_anomalies(tid, [Anomaly("QTY_OVER_RECEIPT", Severity.HIGH, "数量超收")])
    record_confirmation(db, tid, ids[0], "已核对无误", confirm=True)
    assert db.get_anomalies(tid)[0]["status"] == "confirmed"


def test_record_correction_manual(db):
    tid = db.create_task("t")
    rid = record_correction(db, tid, "total_amount", "100", "200", "复核")
    recs = db.get_review_records(tid)
    assert recs[0]["old_value"] == "100"
    assert recs[0]["new_value"] == "200"


def test_persistence_across_reopen(tmp_path):
    from invoice_matching.db import Database as DB

    path = tmp_path / "persist.db"
    db1 = DB(path)
    tid = db1.create_task("持久化任务")
    _insert_doc(db1, tid)
    db1.close()

    db2 = DB(path)
    assert db2.list_tasks()[0]["name"] == "持久化任务"
    assert len(db2.list_documents(tid)) == 1
    db2.close()


def test_multiple_corrections_preserve_history(db):
    tid = db.create_task("t")
    doc_id = _insert_doc(db, tid)
    db.save_business_document(tid, doc_id, DocumentType.PURCHASE_ORDER, _po())
    db.save_extraction(doc_id, ExtractionResult(
        document_type=DocumentType.PURCHASE_ORDER, data=_po(), method=ExtractionMethod.OFFLINE))

    apply_correction(db, tid, doc_id, "supplier_name", "乙公司", "第一次修正")
    apply_correction(db, tid, doc_id, "supplier_name", "丙公司", "第二次修正")

    recs = db.get_review_records(tid)
    assert len(recs) == 2
    assert recs[0]["old_value"] == "甲公司"
    assert recs[1]["old_value"] == "乙公司"
    assert recs[1]["new_value"] == "丙公司"


def test_anomaly_defaults_open(db):
    tid = db.create_task("t")
    db.save_anomalies(tid, [Anomaly("DUPLICATE_INVOICE", Severity.CRITICAL, "重复发票")])
    assert db.get_anomalies(tid)[0]["status"] == "open"


def test_transaction_rollback(db):
    db.create_task("t")
    with pytest.raises(RuntimeError):
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO reconciliation_tasks(name, status, created_at, updated_at) "
                "VALUES(?,?,?,?)", ("rolled", "x", "now", "now")
            )
            raise RuntimeError("boom")
    names = [t["name"] for t in db.list_tasks()]
    assert "rolled" not in names


def test_delete_document_removes_business_document(db):
    tid = db.create_task("t")
    doc_id = _insert_doc(db, tid)
    db.save_business_document(tid, doc_id, DocumentType.PURCHASE_ORDER, _po())
    assert len(db.get_business_documents(tid)) == 1

    db.delete_document(doc_id)
    assert len(db.get_business_documents(tid)) == 0
