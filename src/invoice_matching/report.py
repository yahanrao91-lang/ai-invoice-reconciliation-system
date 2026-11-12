"""自动生成 Excel 对账报告（openpyxl）。

包含：对账总览、采购订单明细、发票明细、收货记录明细、三单匹配结果、异常记录、人工审核历史。
要求：表头清晰、异常着色、金额格式、自动筛选、冻结窗格、自适应列宽、唯一文件名。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .db import Database
from .logging_config import get_logger

log = get_logger(__name__)

HEADER_FILL = PatternFill("solid", fgColor="2F5597")
HEADER_FONT = Font(bold=True, color="FFFFFF")
WARN_FILL = PatternFill("solid", fgColor="FFF2CC")
ERROR_FILL = PatternFill("solid", fgColor="F8CBAD")
OK_FILL = PatternFill("solid", fgColor="C6EFCE")


def _money(v) -> float | None:
    if v is None:
        return None
    try:
        return round(float(Decimal(str(v))), 2)
    except Exception:
        return None


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        return float(Decimal(str(v)))
    except Exception:
        return None


def _write_sheet(wb, title: str, headers: list[str], rows: list[list], money_cols: set[int] = frozenset()):
    ws = wb.create_sheet(title)
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
    for r in rows:
        ws.append(r)
    # 金额格式
    for idx in money_cols:
        for row in range(2, len(rows) + 2):
            ws.cell(row=row, column=idx).number_format = '#,##0.00'
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(1, len(rows) + 1)}"
    _autosize(ws, headers)
    return ws


def _autosize(ws, headers: list[str]) -> None:
    for i, h in enumerate(headers, start=1):
        max_len = len(str(h)) * 2
        for row in ws.iter_rows(min_col=i, max_col=i, min_row=2):
            for cell in row:
                if cell.value is not None:
                    max_len = max(max_len, len(str(cell.value)) * 2)
        ws.column_dimensions[get_column_letter(i)].width = min(max(max_len, 8), 50)


def generate_report(task_id: int, db: Database, export_dir: Path | None = None) -> Path:
    export_dir = export_dir or Path(db.path).parent / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)

    task = db.get_task(task_id) or {}
    docs = db.list_documents(task_id)
    biz = db.get_business_documents(task_id)
    matches = db.get_line_matches(task_id)
    anomalies = db.get_anomalies(task_id)
    reviews = db.get_review_records(task_id)

    pos = [b for b in biz if b["doc_type"] == "purchase_order"]
    invs = [b for b in biz if b["doc_type"] == "invoice"]
    grns = [b for b in biz if b["doc_type"] == "goods_receipt_note"]

    wb = Workbook()
    # 移除默认 sheet
    wb.remove(wb.active)

    # 1. 对账总览
    summary = _build_summary(task, docs, pos, invs, grns, matches, anomalies, reviews)
    _write_sheet(wb, "对账总览", ["指标", "值"], summary)

    # 2. 采购订单明细
    po_rows = []
    for b in pos:
        e = b["entity"]
        po_rows.append([e.po_number, e.order_date, e.supplier_name, e.supplier_tax_no,
                        e.buyer_name, len(e.lines), _money(e.total_amount)])
    _write_sheet(wb, "采购订单明细",
                 ["订单编号", "订单日期", "供应商", "供应商税号", "采购方", "明细行数", "总金额"],
                 po_rows, {7})

    # 3. 发票明细（含行）
    inv_rows = []
    for b in invs:
        e = b["entity"]
        for ln in e.lines:
            inv_rows.append([e.invoice_number, e.invoice_code, e.invoice_date, e.seller_name,
                             e.seller_tax_no, ln.item_no, ln.name, ln.spec, ln.unit,
                             _num(ln.quantity), _money(ln.unit_price), _money(ln.amount),
                             _num(ln.tax_rate), _money(ln.tax_amount), _money(ln.line_total)])
    _write_sheet(wb, "发票明细",
                 ["发票号码", "发票代码", "开票日期", "销售方", "销售方税号", "商品编号", "商品名称",
                  "规格", "单位", "数量", "单价", "金额", "税率", "税额", "价税合计"],
                 inv_rows, {11, 12, 14, 15})

    # 4. 收货记录明细
    grn_rows = []
    for b in grns:
        e = b["entity"]
        for ln in e.lines:
            grn_rows.append([e.grn_number, e.po_number, e.receipt_date, e.supplier_name,
                             ln.item_no, ln.name, ln.spec, ln.unit,
                             _num(ln.planned_qty), _num(ln.received_qty)])
    _write_sheet(wb, "收货记录明细",
                 ["收货单编号", "关联订单号", "收货日期", "供应商", "商品编号", "商品名称",
                  "规格", "单位", "计划收货数量", "实际收货数量"],
                 grn_rows, {9, 10})

    # 5. 三单匹配结果
    match_rows = []
    for m in matches:
        match_rows.append([m["invoice_number"], m["item_no"], m["name"], m["po_item_no"],
                           m["po_name"], m["match_basis"], m["po_qty"], m["received_qty"],
                           m["invoice_qty"], m["po_price"], m["invoice_price"], m["status"],
                           (m["anomaly_codes"] or "").replace(",", "; ")])
    ws = _write_sheet(wb, "三单匹配结果",
                      ["发票号码", "商品编号", "商品名称", "订单商品编号", "订单商品名称", "匹配依据",
                       "订单数量", "实收数量", "发票数量", "订单单价", "发票单价", "状态", "异常代码"],
                      match_rows, {7, 8, 9, 10, 11})
    _colorize_status(ws, 12)

    # 6. 异常记录
    anom_rows = [[a["code"], a["severity"], a["message"], a["entity_type"], a["entity_ref"],
                  a["status"]] for a in anomalies]
    ws2 = _write_sheet(wb, "异常记录",
                       ["异常代码", "严重程度", "说明", "单据类型", "单据编号", "状态"],
                       anom_rows)
    for row in range(2, len(anom_rows) + 2):
        sev = ws2.cell(row=row, column=2).value
        if sev in ("CRITICAL", "HIGH"):
            for c in range(1, 7):
                ws2.cell(row=row, column=c).fill = ERROR_FILL
        elif sev == "MEDIUM":
            for c in range(1, 7):
                ws2.cell(row=row, column=c).fill = WARN_FILL

    # 7. 人工审核历史
    rev_rows = [[r["action"], r["field_path"], r["old_value"], r["new_value"], r["reason"],
                 r["reviewer"], r["created_at"]] for r in reviews]
    _write_sheet(wb, "人工审核历史",
                 ["操作", "字段", "修改前", "修改后", "原因", "审核人", "时间"],
                 rev_rows)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = export_dir / f"对账报告_任务{task_id}_{ts}.xlsx"
    wb.save(filename)
    log.info("已生成对账报告：%s", filename)
    return filename


def _build_summary(task, docs, pos, invs, grns, matches, anomalies, reviews) -> list:
    open_anoms = [a for a in anomalies if a["status"] == "open"]
    critical = [a for a in anomalies if a["severity"] == "CRITICAL"]
    status_counts: dict[str, int] = {}
    for m in matches:
        status_counts[m["status"]] = status_counts.get(m["status"], 0) + 1
    return [
        ("任务编号", task.get("id")),
        ("任务名称", task.get("name")),
        ("处理状态", task.get("status")),
        ("创建时间", task.get("created_at")),
        ("文档数量", len(docs)),
        ("采购订单数", len(pos)),
        ("发票数", len(invs)),
        ("收货记录数", len(grns)),
        ("匹配行总数", len(matches)),
        ("匹配一致行数", status_counts.get("匹配一致", 0)),
        ("数量差异行数", status_counts.get("存在数量差异", 0)),
        ("价格差异行数", status_counts.get("存在价格差异", 0)),
        ("待人工确认行数", status_counts.get("待人工确认", 0)),
        ("异常总数", len(anomalies)),
        ("未处理异常数", len(open_anoms)),
        ("严重异常数", len(critical)),
        ("人工审核记录数", len(reviews)),
        ("审核建议", "本报告为对账审核建议，非付款授权，亦不构成税务真伪查验结论"),
    ]


def _colorize_status(ws, col: int) -> None:
    for row in ws.iter_rows(min_row=2, min_col=col, max_col=col):
        for cell in row:
            v = cell.value
            if v == "匹配一致":
                cell.fill = OK_FILL
            elif v in ("存在数量差异", "存在价格差异"):
                cell.fill = ERROR_FILL
            elif v == "待人工确认":
                cell.fill = WARN_FILL
