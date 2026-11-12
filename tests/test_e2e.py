"""端到端测试：从文件导入到三单匹配的完整流程。"""
from pathlib import Path

from invoice_matching.db import Database
from invoice_matching.pipeline import Pipeline

PO_LINES = [
    "模拟票据｜非真实业务凭证",
    "文档类型：采购订单（PO）",
    "采购订单编号：PO-E2E-001",
    "订单日期：2026-01-05",
    "供应商名称：华东精密制造有限公司",
    "供应商税号：91310000FAKE000A",
    "采购方名称：示例采购有限公司",
    "采购方税号：91310000BUYER00A",
    "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：",
    "ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | 200.00 | 20000.00 | 13% | 2600.00 | 22600.00",
    "合计金额：22600.00",
]

INV_LINES = [
    "模拟票据｜非真实业务凭证",
    "文档类型：供应商发票（Invoice）",
    "发票代码：3100160000",
    "发票号码：INV-E2E-001",
    "开票日期：2026-01-10",
    "销售方名称：华东精密制造有限公司",
    "销售方税号：91310000FAKE000A",
    "购买方名称：示例采购有限公司",
    "购买方税号：91310000BUYER00A",
    "关联采购订单号：PO-E2E-001",
    "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：",
    "ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | 200.00 | 20000.00 | 13% | 2600.00 | 22600.00",
    "合计金额：22600.00",
]

GRN_LINES_OK = [
    "模拟票据｜非真实业务凭证",
    "文档类型：收货记录（GRN）",
    "收货单编号：GRN-E2E-001",
    "关联采购订单号：PO-E2E-001",
    "收货日期：2026-01-20",
    "供应商名称：华东精密制造有限公司",
    "供应商税号：91310000FAKE000A",
    "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 计划收货数量 | 实际收货数量）：",
    "ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | 100",
]

GRN_LINES_SHORT = GRN_LINES_OK[:-1] + ["ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | 95"]


def _write_pdf(path: Path, lines: list[str]) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    y = 60
    for ln in lines:
        page.insert_text((50, y), ln, fontname="china-s", fontsize=11)
        y += 22
    doc.save(str(path))
    doc.close()


def _write_xlsx(path: Path, lines: list[str]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for ln in lines:
        ws.append([ln])
    wb.save(str(path))


def test_e2e_full_match(tmp_path, no_ocr):
    files = []
    for name, lines, writer in [
        ("po.pdf", PO_LINES, _write_pdf),
        ("inv.xlsx", INV_LINES, _write_xlsx),
        ("grn.pdf", GRN_LINES_OK, _write_pdf),
    ]:
        p = tmp_path / name
        writer(p, lines)
        files.append(p)

    db = Database(tmp_path / "e2e.db")
    pipe = Pipeline(db=db)
    r = pipe.full_run("e2e-一致", files)

    assert r["matching"]["anomaly_count"] == 0
    assert r["matching"]["line_match_count"] == 1
    assert db.get_task(r["task_id"])["status"] == "completed"
    assert r["matching"]["summary"]["匹配一致"] == 1


def test_e2e_qty_anomaly(tmp_path, no_ocr):
    files = []
    for name, lines, writer in [
        ("po.pdf", PO_LINES, _write_pdf),
        ("inv.pdf", INV_LINES, _write_pdf),
        ("grn.xlsx", GRN_LINES_SHORT, _write_xlsx),
    ]:
        p = tmp_path / name
        writer(p, lines)
        files.append(p)

    db = Database(tmp_path / "e2e.db")
    pipe = Pipeline(db=db)
    r = pipe.full_run("e2e-数量异常", files)

    codes = {a["code"] for a in db.get_anomalies(r["task_id"])}
    assert "QTY_OVER_RECEIPT" in codes
    assert r["matching"]["summary"]["存在数量差异"] == 1


def test_e2e_duplicate_invoice(tmp_path, no_ocr):
    files = []
    for name, lines, writer in [
        ("po.pdf", PO_LINES, _write_pdf),
        ("inv1.pdf", INV_LINES, _write_pdf),
        # 第二张发票：发票号码相同，但内容多一行备注，确保文件字节不同、可同时导入
        ("inv2.pdf", INV_LINES + ["备注：第二联"], _write_pdf),
        ("grn.pdf", GRN_LINES_OK, _write_pdf),
    ]:
        p = tmp_path / name
        writer(p, lines)
        files.append(p)

    db = Database(tmp_path / "e2e.db")
    pipe = Pipeline(db=db)
    r = pipe.full_run("e2e-重复发票", files)

    codes = {a["code"] for a in db.get_anomalies(r["task_id"])}
    assert "DUPLICATE_INVOICE" in codes


def test_e2e_corrupted_file_missing_document(tmp_path, no_ocr):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"this is not a valid pdf content")

    db = Database(tmp_path / "e2e.db")
    pipe = Pipeline(db=db)
    r = pipe.full_run("e2e-损坏文件", [bad])

    codes = {a["code"] for a in db.get_anomalies(r["task_id"])}
    assert "MISSING_DOCUMENT" in codes
    assert db.list_documents(r["task_id"])[0]["status"] == "failed"


def _agg_po_text():
    return [
        "模拟票据｜非真实业务凭证",
        "文档类型：采购订单（PO）",
        "采购订单编号：PO-AGG-001",
        "订单日期：2026-01-05",
        "供应商名称：华东精密制造有限公司",
        "供应商税号：91310000FAKE000A",
        "采购方名称：示例采购有限公司",
        "采购方税号：91310000BUYER00A",
        "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：",
        "ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | 200.00 | 20000.00 | 13% | 2600.00 | 22600.00",
        "合计金额：22600.00",
    ]


def _agg_inv_text(number, qty, amount, tax, total):
    return [
        "模拟票据｜非真实业务凭证",
        "文档类型：供应商发票（Invoice）",
        "发票代码：3100160000",
        f"发票号码：{number}",
        "开票日期：2026-01-10",
        "销售方名称：华东精密制造有限公司",
        "销售方税号：91310000FAKE000A",
        "购买方名称：示例采购有限公司",
        "购买方税号：91310000BUYER00A",
        "关联采购订单号：PO-AGG-001",
        "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：",
        f"ITEM-001 | 不锈钢轴承 | 6204 | 件 | {qty} | 200.00 | {amount} | 13% | {tax} | {total}",
        f"合计金额：{total}",
    ]


def _agg_grn_text(received):
    return [
        "模拟票据｜非真实业务凭证",
        "文档类型：收货记录（GRN）",
        "收货单编号：GRN-AGG-001",
        "关联采购订单号：PO-AGG-001",
        "收货日期：2026-01-20",
        "供应商名称：华东精密制造有限公司",
        "供应商税号：91310000FAKE000A",
        "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 计划收货数量 | 实际收货数量）：",
        f"ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | {received}",
    ]


def test_e2e_multi_invoice_aggregate_over_receipt(tmp_path, no_ocr):
    files = []
    for name, lines in [
        ("po.pdf", _agg_po_text()),
        ("inv1.pdf", _agg_inv_text("INV-AGG-1", 60, "12000.00", "1560.00", "13560.00")),
        ("inv2.pdf", _agg_inv_text("INV-AGG-2", 60, "12000.00", "1560.00", "13560.00")),
        ("grn.pdf", _agg_grn_text(100)),
    ]:
        p = tmp_path / name
        _write_pdf(p, lines)
        files.append(p)

    db = Database(tmp_path / "e2e.db")
    pipe = Pipeline(db=db)
    r = pipe.full_run("e2e-多发票超收", files)

    codes = {a["code"] for a in db.get_anomalies(r["task_id"])}
    assert "QTY_OVER_RECEIPT" in codes
