"""端到端编排：导入 → 提取 → 标准化 → 验证 → 匹配 → 异常 → 持久化。"""
from __future__ import annotations

from pathlib import Path

from .ai.extractor import extract_with_llm_retry
from .ai.llm_provider import build_provider
from .ai.offline_parser import parse_offline
from .anomalies import Anomaly, Severity
from .config import settings
from .db import Database
from .detection import detect_document_type
from .document_import import import_file
from .extraction import extract_text
from .extraction.ocr import OcrManager
from .logging_config import get_logger
from .models import DocumentType, ExtractionMethod
from .processing.aliases import AliasRegistry
from .processing.matching import match_task
from .processing.validate import validate_invoice, validate_po

log = get_logger(__name__)


class Pipeline:
    """对账任务流水线。"""

    def __init__(self, db: Database | None = None, ocr_manager: OcrManager | None = None) -> None:
        self.db = db or Database()
        self.ocr = ocr_manager if ocr_manager is not None else OcrManager()

    # ---------- 任务 ----------
    def create_task(self, name: str) -> int:
        task_id = self.db.create_task(name)
        self.db.add_audit_log(task_id, "创建任务", name)
        return task_id

    # ---------- 导入 ----------
    def import_files(self, task_id: int, paths: list[Path]) -> list[dict]:
        """批量导入文件；返回每个文件的处理结果（含重复/失败提示）。"""
        known = self.db.known_hashes()
        results: list[dict] = []
        for p in paths:
            imp = import_file(p, known_hashes=known)
            if imp.status == "imported":
                doc_id = self.db.insert_document(
                    {
                        "task_id": task_id,
                        "original_name": imp.original_name,
                        "stored_name": imp.stored_name,
                        "stored_path": imp.stored_path,
                        "file_hash": imp.file_hash,
                        "extension": imp.extension,
                        "size_bytes": imp.size_bytes,
                        "doc_type": detect_document_type("", imp.original_name),
                        "status": "imported",
                        "imported_at": imp.imported_at,
                    }
                )
                known.add(imp.file_hash)
                self.db.add_audit_log(task_id, "导入文档", f"{imp.original_name} -> {imp.stored_name}")
                results.append({"ok": True, "document_id": doc_id, "name": imp.original_name, "message": "导入成功"})
            elif imp.status == "duplicate":
                results.append({"ok": False, "document_id": None, "name": imp.original_name, "message": imp.error or "重复文件"})
            else:
                results.append({"ok": False, "document_id": None, "name": imp.original_name, "message": imp.error or "导入失败"})
        return results

    # ---------- 提取 ----------
    def process_document(self, task_id: int, document_id: int) -> dict:
        """提取单个文档并持久化结构化结果。"""
        doc = self.db.get_document(document_id)
        if not doc:
            return {"ok": False, "message": "文档不存在"}

        try:
            extracted = extract_text(Path(doc["stored_path"]), self.ocr)
        except Exception as exc:  # noqa: BLE001
            self.db.update_document(document_id, status="failed")
            self.db.add_audit_log(task_id, "提取失败", f"{doc['original_name']}: {exc}")
            return {"ok": False, "message": f"文本提取失败：{exc}"}

        self.db.update_document(document_id, status="extracted", extraction_method=extracted.method.value)

        text = extracted.text.strip()
        warnings = list(extracted.extra.get("warnings", []))

        if not text:
            self.db.update_document(document_id, status="failed")
            msg = "未能提取到文本内容（OCR 不可用或文档无文本层）"
            self.db.add_audit_log(task_id, "提取失败", f"{doc['original_name']}: {msg}")
            return {"ok": False, "message": msg, "warnings": warnings}

        # AI 提取 / 离线解析
        provider = build_provider()
        result = None
        method_label = ""
        try:
            if provider is not None and settings.llm_enabled:
                result = extract_with_llm_retry(text, provider, settings.llm_max_retries)
                method_label = "AI 模型"
            else:
                result = parse_offline(text, doc["original_name"])
                method_label = "离线规则"
        except Exception as exc:  # noqa: BLE001
            log.warning("文档 %s 智能提取失败，回退离线解析：%s", doc["original_name"], exc)
            result = parse_offline(text, doc["original_name"])
            method_label = "离线规则（AI 提取失败后回退）"
            warnings.append(f"AI 提取失败：{exc}")

        if result.document_type is None or result.data is None:
            self.db.update_document(document_id, status="needs_review")
            return {"ok": True, "needs_review": True, "message": "无法自动识别文档，需人工录入", "warnings": warnings}

        self.db.save_extraction(document_id, result)
        self.db.update_document(document_id, doc_type=result.document_type.value, status="processed")
        self.db.save_business_document(task_id, document_id, result.document_type, result.data)
        self.db.add_audit_log(
            task_id, "结构化提取",
            f"{doc['original_name']} -> {result.document_type.label}（方式：{result.method.value}，置信度 {result.confidence}）",
        )
        return {
            "ok": True,
            "needs_review": bool(result.missing_fields or result.needs_review),
            "document_type": result.document_type.value,
            "method": result.method.value,
            "method_label": method_label,
            "confidence": result.confidence,
            "missing_fields": result.missing_fields,
            "warnings": warnings,
        }

    # ---------- 匹配 ----------
    def run_matching(self, task_id: int, aliases: AliasRegistry | None = None) -> dict:
        """加载业务单据，执行验证 + 三单匹配，保存异常与匹配结果。"""
        biz = self.db.get_business_documents(task_id)
        pos, invs, grns = [], [], []
        for b in biz:
            e = b["entity"]
            if b["doc_type"] == "purchase_order":
                pos.append(e)
            elif b["doc_type"] == "invoice":
                invs.append(e)
            elif b["doc_type"] == "goods_receipt_note":
                grns.append(e)

        anomalies = []
        for po in pos:
            anomalies.extend(validate_po(po, settings.rules))
        for inv in invs:
            anomalies.extend(validate_invoice(inv, settings.rules))

        # 缺失文件 / 无法解析的文档
        for doc in self.db.list_documents(task_id):
            if doc["status"] in ("failed", "needs_review"):
                anomalies.append(
                    Anomaly(
                        "MISSING_DOCUMENT", Severity.HIGH,
                        f"文档「{doc['original_name']}」未能完成结构化提取（状态：{doc['status']}）",
                        "document", doc["stored_name"], "status", "",
                    )
                )

        seen = set()
        outcome = match_task(pos, invs, grns, settings.rules, aliases, seen)
        anomalies.extend(outcome.anomalies)

        self.db.save_anomalies(task_id, anomalies)
        self.db.save_line_matches(task_id, outcome.line_matches)
        self.db.update_task_status(task_id, "completed")
        self.db.add_audit_log(
            task_id, "执行匹配",
            f"PO={len(pos)}，发票={len(invs)}，收货={len(grns)}，异常={len(anomalies)}，匹配行={len(outcome.line_matches)}",
        )
        return {
            "ok": True,
            "anomaly_count": len(anomalies),
            "line_match_count": len(outcome.line_matches),
            "summary": outcome.summary,
        }

    # ---------- 端到端 ----------
    def full_run(self, task_name: str, paths: list[Path]) -> dict:
        """一键执行：建任务 → 导入 → 提取 → 匹配。"""
        task_id = self.create_task(task_name)
        imported = self.import_files(task_id, paths)
        doc_ids = [r["document_id"] for r in imported if r["ok"] and r["document_id"]]
        process_results = [self.process_document(task_id, did) for did in doc_ids]
        aliases = self.db.load_aliases()
        match_result = self.run_matching(task_id, aliases)
        return {
            "task_id": task_id,
            "imported": imported,
            "processed": process_results,
            "matching": match_result,
        }
