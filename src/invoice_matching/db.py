"""SQLite 数据持久化层：任务、文档、提取、业务单据、匹配、异常、审核、日志、别名。

- 主键/外键关系清晰，含必要索引。
- 重要写入使用事务。
- 通过 UNIQUE 约束防止重复登记。
- 数据库文件默认仅存储在本地 data/ 目录。
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import settings
from .logging_config import get_logger
from .models import (
    DocumentType,
    ExtractionResult,
    GoodsReceiptNote,
    Invoice,
    PurchaseOrder,
    entity_from_type,
)
from .processing.aliases import AliasRegistry

log = get_logger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS reconciliation_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    original_name TEXT NOT NULL,
    stored_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    file_hash TEXT NOT NULL,
    extension TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    doc_type TEXT,
    status TEXT NOT NULL DEFAULT 'imported',
    extraction_method TEXT,
    imported_at TEXT NOT NULL,
    UNIQUE(file_hash, task_id),
    FOREIGN KEY(task_id) REFERENCES reconciliation_tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS extraction_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL UNIQUE,
    doc_type TEXT,
    method TEXT,
    confidence REAL,
    data_json TEXT,
    raw_text TEXT,
    evidence_json TEXT,
    missing_fields TEXT,
    needs_review TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS business_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    document_id INTEGER,
    doc_type TEXT NOT NULL,
    doc_number TEXT,
    doc_date TEXT,
    supplier_name TEXT,
    supplier_tax_no TEXT,
    buyer_name TEXT,
    total_amount TEXT,
    data_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES reconciliation_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS line_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    business_document_id INTEGER NOT NULL,
    item_no TEXT,
    name TEXT,
    spec TEXT,
    unit TEXT,
    quantity TEXT,
    unit_price TEXT,
    amount TEXT,
    tax_rate TEXT,
    tax_amount TEXT,
    line_total TEXT,
    planned_qty TEXT,
    received_qty TEXT,
    source TEXT,
    FOREIGN KEY(business_document_id) REFERENCES business_documents(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS line_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    invoice_number TEXT,
    item_no TEXT,
    name TEXT,
    po_item_no TEXT,
    po_name TEXT,
    match_basis TEXT,
    po_qty TEXT,
    received_qty TEXT,
    invoice_qty TEXT,
    po_price TEXT,
    invoice_price TEXT,
    status TEXT,
    anomaly_codes TEXT,
    FOREIGN KEY(task_id) REFERENCES reconciliation_tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    code TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    entity_type TEXT,
    entity_ref TEXT,
    field TEXT,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    FOREIGN KEY(task_id) REFERENCES reconciliation_tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS review_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    anomaly_id INTEGER,
    document_id INTEGER,
    field_path TEXT,
    old_value TEXT,
    new_value TEXT,
    reason TEXT,
    reviewer TEXT,
    action TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(task_id) REFERENCES reconciliation_tasks(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    action TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical TEXT NOT NULL,
    alias TEXT NOT NULL,
    UNIQUE(canonical, alias)
);

CREATE INDEX IF NOT EXISTS idx_documents_task ON documents(task_id);
CREATE INDEX IF NOT EXISTS idx_biz_task ON business_documents(task_id);
CREATE INDEX IF NOT EXISTS idx_line_biz ON line_items(business_document_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_task ON anomalies(task_id);
CREATE INDEX IF NOT EXISTS idx_review_task ON review_records(task_id);
CREATE INDEX IF NOT EXISTS idx_matches_task ON line_matches(task_id);
CREATE INDEX IF NOT EXISTS idx_audit_task ON audit_logs(task_id);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _json_dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _json_load(s: str | None) -> Any:
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None


class Database:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path else settings.db_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.executescript(SCHEMA)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    # ---------- 任务 ----------
    def create_task(self, name: str) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                "INSERT INTO reconciliation_tasks(name, status, created_at, updated_at) VALUES(?,?,?,?)",
                (name, "processing", _now(), _now()),
            )
            return int(cur.lastrowid)

    def update_task_status(self, task_id: int, status: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE reconciliation_tasks SET status=?, updated_at=? WHERE id=?",
                (status, _now(), task_id),
            )

    def get_task(self, task_id: int) -> dict | None:
        row = self.connect().execute(
            "SELECT * FROM reconciliation_tasks WHERE id=?", (task_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_tasks(self) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM reconciliation_tasks ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 文档 ----------
    def insert_document(self, doc: dict) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO documents
                   (task_id, original_name, stored_name, stored_path, file_hash, extension,
                    size_bytes, doc_type, status, extraction_method, imported_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    doc.get("task_id"), doc["original_name"], doc["stored_name"],
                    str(doc["stored_path"]), doc["file_hash"], doc["extension"],
                    doc["size_bytes"], doc.get("doc_type"), doc.get("status", "imported"),
                    doc.get("extraction_method"), doc["imported_at"],
                ),
            )
            return int(cur.lastrowid)

    def update_document(self, document_id: int, **fields: Any) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [document_id]
        with self.transaction() as conn:
            conn.execute(f"UPDATE documents SET {cols} WHERE id=?", vals)

    def get_document(self, document_id: int) -> dict | None:
        row = self.connect().execute(
            "SELECT * FROM documents WHERE id=?", (document_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_documents(self, task_id: int | None = None) -> list[dict]:
        if task_id is None:
            rows = self.connect().execute("SELECT * FROM documents ORDER BY id DESC").fetchall()
        else:
            rows = self.connect().execute(
                "SELECT * FROM documents WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_document(self, document_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM business_documents WHERE document_id=?", (document_id,))
            conn.execute("DELETE FROM documents WHERE id=?", (document_id,))

    def known_hashes(self, task_id: int | None = None) -> set[str]:
        if task_id is None:
            rows = self.connect().execute("SELECT DISTINCT file_hash FROM documents").fetchall()
        else:
            rows = self.connect().execute(
                "SELECT DISTINCT file_hash FROM documents WHERE task_id=?", (task_id,)
            ).fetchall()
        return {r["file_hash"] for r in rows}

    # ---------- 提取结果 ----------
    def save_extraction(self, document_id: int, result: ExtractionResult) -> int:
        data_json = result.data.to_dict() if result.data else None
        with self.transaction() as conn:
            conn.execute("DELETE FROM extraction_results WHERE document_id=?", (document_id,))
            cur = conn.execute(
                """INSERT INTO extraction_results
                   (document_id, doc_type, method, confidence, data_json, raw_text,
                    evidence_json, missing_fields, needs_review, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    document_id,
                    result.document_type.value if result.document_type else None,
                    result.method.value,
                    result.confidence,
                    _json_dump(data_json) if data_json else None,
                    result.raw_text,
                    _json_dump(result.evidence),
                    _json_dump(result.missing_fields),
                    _json_dump(result.needs_review),
                    _now(),
                ),
            )
            return int(cur.lastrowid)

    def get_extraction(self, document_id: int) -> dict | None:
        row = self.connect().execute(
            "SELECT * FROM extraction_results WHERE document_id=?", (document_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["data"] = _json_load(d.pop("data_json", None))
        d["evidence"] = _json_load(d.pop("evidence_json", None)) or {}
        d["missing_fields"] = _json_load(d.pop("missing_fields", None)) or []
        d["needs_review"] = _json_load(d.pop("needs_review", None)) or []
        return d

    # ---------- 业务单据 ----------
    def save_business_document(
        self, task_id: int, document_id: int | None, doc_type: DocumentType, entity: Any
    ) -> int:
        data = entity.to_dict()
        supplier = getattr(entity, "supplier_name", None) or getattr(entity, "seller_name", None)
        supplier_tax = getattr(entity, "supplier_tax_no", None) or getattr(entity, "seller_tax_no", None)
        buyer = getattr(entity, "buyer_name", None)
        doc_number, doc_date, total = None, None, None
        if doc_type == DocumentType.PURCHASE_ORDER:
            doc_number, doc_date, total = entity.po_number, entity.order_date, entity.total_amount
        elif doc_type == DocumentType.INVOICE:
            doc_number, doc_date, total = entity.invoice_number, entity.invoice_date, entity.total_amount
        else:
            doc_number, doc_date = entity.grn_number, entity.receipt_date

        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO business_documents
                   (task_id, document_id, doc_type, doc_number, doc_date, supplier_name,
                    supplier_tax_no, buyer_name, total_amount, data_json, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id, document_id, doc_type.value, doc_number, doc_date,
                    supplier, supplier_tax, buyer,
                    None if total is None else str(total),
                    _json_dump(data), _now(),
                ),
            )
            biz_id = int(cur.lastrowid)
            for ln in entity.lines:
                conn.execute(
                    """INSERT INTO line_items
                       (business_document_id, item_no, name, spec, unit, quantity, unit_price,
                        amount, tax_rate, tax_amount, line_total, planned_qty, received_qty, source)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        biz_id, ln.item_no, ln.name, ln.spec, ln.unit,
                        _s(getattr(ln, "quantity", None)), _s(getattr(ln, "unit_price", None)),
                        _s(getattr(ln, "amount", None)), _s(getattr(ln, "tax_rate", None)),
                        _s(getattr(ln, "tax_amount", None)), _s(getattr(ln, "line_total", None)),
                        _s(getattr(ln, "planned_qty", None)), _s(getattr(ln, "received_qty", None)),
                        getattr(ln, "source", ""),
                    ),
                )
            return biz_id

    def update_business_document(
        self, document_id: int, doc_type: DocumentType, entity: Any
    ) -> None:
        """人工修正后回写业务单据（按 document_id 更新，不新增行）。"""
        data = entity.to_dict()
        supplier = getattr(entity, "supplier_name", None) or getattr(entity, "seller_name", None)
        supplier_tax = getattr(entity, "supplier_tax_no", None) or getattr(entity, "seller_tax_no", None)
        buyer = getattr(entity, "buyer_name", None)
        doc_number, doc_date, total = None, None, None
        if doc_type == DocumentType.PURCHASE_ORDER:
            doc_number, doc_date, total = entity.po_number, entity.order_date, entity.total_amount
        elif doc_type == DocumentType.INVOICE:
            doc_number, doc_date, total = entity.invoice_number, entity.invoice_date, entity.total_amount
        else:
            doc_number, doc_date = entity.grn_number, entity.receipt_date

        with self.transaction() as conn:
            conn.execute(
                """UPDATE business_documents SET
                   doc_number=?, doc_date=?, supplier_name=?, supplier_tax_no=?, buyer_name=?,
                   total_amount=?, data_json=? WHERE document_id=? AND doc_type=?""",
                (
                    doc_number, doc_date, supplier, supplier_tax, buyer,
                    None if total is None else str(total),
                    _json_dump(data), document_id, doc_type.value,
                ),
            )

    def update_extraction_data(self, document_id: int, data: dict) -> None:
        with self.transaction() as conn:
            conn.execute(
                "UPDATE extraction_results SET data_json=? WHERE document_id=?",
                (_json_dump(data), document_id),
            )

    def get_business_documents(self, task_id: int) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM business_documents WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["entity"] = entity_from_type(DocumentType(d["doc_type"]), _json_load(d["data_json"]))
            out.append(d)
        return out

    # ---------- 匹配结果 ----------
    def save_line_matches(self, task_id: int, matches: list) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM line_matches WHERE task_id=?", (task_id,))
            for m in matches:
                conn.execute(
                    """INSERT INTO line_matches
                       (task_id, invoice_number, item_no, name, po_item_no, po_name, match_basis,
                        po_qty, received_qty, invoice_qty, po_price, invoice_price, status, anomaly_codes)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        task_id, m.invoice_number, m.item_no, m.name, m.po_item_no, m.po_name,
                        m.match_basis,
                        _s(m.po_qty), _s(m.received_qty), _s(m.invoice_qty),
                        _s(m.po_price), _s(m.invoice_price), m.status,
                        _json_dump(m.anomaly_codes),
                    ),
                )

    def get_line_matches(self, task_id: int) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM line_matches WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 异常 ----------
    def save_anomalies(self, task_id: int, anomalies: list) -> list[int]:
        ids: list[int] = []
        with self.transaction() as conn:
            conn.execute("DELETE FROM anomalies WHERE task_id=?", (task_id,))
            for a in anomalies:
                cur = conn.execute(
                    """INSERT INTO anomalies
                       (task_id, code, severity, message, entity_type, entity_ref, field, evidence, status)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (task_id, a.code, a.severity, a.message, a.entity_type, a.entity_ref, a.field, a.evidence, "open"),
                )
                ids.append(int(cur.lastrowid))
        return ids

    def get_anomalies(self, task_id: int) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM anomalies WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def update_anomaly_status(self, anomaly_id: int, status: str) -> None:
        with self.transaction() as conn:
            conn.execute("UPDATE anomalies SET status=? WHERE id=?", (status, anomaly_id))

    # ---------- 审核 ----------
    def add_review_record(self, record: dict) -> int:
        with self.transaction() as conn:
            cur = conn.execute(
                """INSERT INTO review_records
                   (task_id, anomaly_id, document_id, field_path, old_value, new_value,
                    reason, reviewer, action, created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.get("task_id"), record.get("anomaly_id"), record.get("document_id"),
                    record.get("field_path"), record.get("old_value"), record.get("new_value"),
                    record.get("reason"), record.get("reviewer"), record.get("action"), _now(),
                ),
            )
            return int(cur.lastrowid)

    def get_review_records(self, task_id: int) -> list[dict]:
        rows = self.connect().execute(
            "SELECT * FROM review_records WHERE task_id=? ORDER BY id", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 审计日志 ----------
    def add_audit_log(self, task_id: int | None, action: str, detail: str = "") -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT INTO audit_logs(task_id, action, detail, created_at) VALUES(?,?,?,?)",
                (task_id, action, detail, _now()),
            )

    def get_audit_logs(self, task_id: int | None = None, limit: int = 200) -> list[dict]:
        if task_id is None:
            rows = self.connect().execute(
                "SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = self.connect().execute(
                "SELECT * FROM audit_logs WHERE task_id=? ORDER BY id DESC LIMIT ?", (task_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]

    # ---------- 别名 ----------
    def add_alias(self, canonical: str, alias: str) -> None:
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO aliases(canonical, alias) VALUES(?,?)", (canonical, alias)
            )

    def delete_alias(self, alias_id: int) -> None:
        with self.transaction() as conn:
            conn.execute("DELETE FROM aliases WHERE id=?", (alias_id,))

    def list_aliases(self) -> list[dict]:
        rows = self.connect().execute("SELECT * FROM aliases ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    def load_aliases(self) -> AliasRegistry:
        return AliasRegistry.from_rows([(r["canonical"], r["alias"]) for r in self.list_aliases()])

    # ---------- 统计 ----------
    def dashboard_stats(self) -> dict:
        conn = self.connect()
        total_tasks = conn.execute("SELECT COUNT(*) c FROM reconciliation_tasks").fetchone()["c"]
        tasks_with_anomalies = conn.execute(
            "SELECT COUNT(DISTINCT task_id) c FROM anomalies"
        ).fetchone()["c"]
        pending = conn.execute(
            "SELECT COUNT(*) c FROM anomalies WHERE status='open'"
        ).fetchone()["c"]
        duplicate = conn.execute(
            "SELECT COUNT(*) c FROM anomalies WHERE code='DUPLICATE_INVOICE'"
        ).fetchone()["c"]
        return {
            "total_tasks": total_tasks,
            "matched_ok": max(0, total_tasks - tasks_with_anomalies),
            "with_anomalies": tasks_with_anomalies,
            "pending_review": pending,
            "duplicate_invoices": duplicate,
        }


def _s(v: Any) -> str | None:
    return None if v is None else str(v)
