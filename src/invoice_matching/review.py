"""人工审核工作流（Human-in-the-Loop）：修正、确认、意见、留痕。"""
from __future__ import annotations

import re
from typing import Any

from .db import Database
from .logging_config import get_logger
from .models import DocumentType, entity_from_type
from .processing.standardize import parse_decimal, parse_tax_rate

log = get_logger(__name__)

_NUMERIC_FIELDS = {
    "quantity", "unit_price", "amount", "tax_amount", "line_total",
    "planned_qty", "received_qty", "total_amount",
}


def _parse_value(field_name: str, raw: str) -> str | None:
    raw = (raw or "").strip()
    if field_name == "tax_rate":
        d = parse_tax_rate(raw)
        return None if d is None else str(d)
    if field_name in _NUMERIC_FIELDS:
        if raw == "":
            return None
        d = parse_decimal(raw)
        return None if d is None else str(d)
    return raw if raw else None


def _get_path(obj: dict, path: str) -> Any:
    cur: Any = obj
    for part in path.split("."):
        m = re.match(r"^(\w+)\[(\d+)\]$", part)
        if m:
            cur = cur[m.group(1)][int(m.group(2))]
        else:
            cur = cur[part]
    return cur


def _set_path(obj: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    cur: Any = obj
    for part in parts[:-1]:
        m = re.match(r"^(\w+)\[(\d+)\]$", part)
        if m:
            cur = cur[m.group(1)][int(m.group(2))]
        else:
            cur = cur[part]
    last = parts[-1]
    m = re.match(r"^(\w+)\[(\d+)\]$", last)
    if m:
        cur[m.group(1)][int(m.group(2))] = value
    else:
        cur[last] = value


def record_correction(
    db: Database,
    task_id: int,
    field_path: str,
    old_value: Any,
    new_value: Any,
    reason: str,
    reviewer: str = "审核员",
    anomaly_id: int | None = None,
    document_id: int | None = None,
) -> int:
    """记录一次人工修正（保留修改前/后值、时间、原因）。"""
    rid = db.add_review_record(
        {
            "task_id": task_id,
            "anomaly_id": anomaly_id,
            "document_id": document_id,
            "field_path": field_path,
            "old_value": None if old_value is None else str(old_value),
            "new_value": None if new_value is None else str(new_value),
            "reason": reason,
            "reviewer": reviewer,
            "action": "correct",
        }
    )
    db.add_audit_log(
        task_id, "人工修正",
        f"{field_path}: {old_value} -> {new_value}（原因：{reason}）",
    )
    return rid


def apply_correction(
    db: Database,
    task_id: int,
    document_id: int,
    field_path: str,
    new_value: str,
    reason: str,
    reviewer: str = "审核员",
) -> tuple[str | None, int | None]:
    """应用一次人工修正：更新提取结果与业务单据，并完整留痕。

    返回 (错误信息, review_record_id)。成功时错误信息为 None。
    """
    ext = db.get_extraction(document_id)
    if not ext or not ext.get("data") or not ext.get("doc_type"):
        return "该文档尚无结构化提取结果，无法修正", None
    data: dict = ext["data"]
    try:
        old_value = _get_path(data, field_path)
    except (KeyError, IndexError, TypeError):
        return f"字段路径无效：{field_path}", None

    field_name = field_path.split(".")[-1]
    field_name = re.sub(r"\[\d+\]$", "", field_name)
    parsed = _parse_value(field_name, new_value)
    _set_path(data, field_path, parsed)

    doc_type = DocumentType(ext["doc_type"])
    entity = entity_from_type(doc_type, data)
    db.update_extraction_data(document_id, data)
    db.update_business_document(document_id, doc_type, entity)

    rid = record_correction(
        db, task_id, field_path, old_value, parsed, reason, reviewer,
        document_id=document_id,
    )
    return None, rid


def record_confirmation(
    db: Database,
    task_id: int,
    anomaly_id: int,
    opinion: str,
    reviewer: str = "审核员",
    confirm: bool = True,
) -> int:
    """确认或驳回一条异常。确认后异常状态更新。"""
    action = "confirm" if confirm else "reject"
    rid = db.add_review_record(
        {
            "task_id": task_id,
            "anomaly_id": anomaly_id,
            "field_path": "",
            "old_value": None,
            "new_value": None,
            "reason": opinion,
            "reviewer": reviewer,
            "action": action,
        }
    )
    db.update_anomaly_status(anomaly_id, "confirmed" if confirm else "rejected")
    db.add_audit_log(
        task_id, "异常确认" if confirm else "异常驳回",
        f"异常#{anomaly_id}：{opinion}",
    )
    return rid
