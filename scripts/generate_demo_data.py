"""生成演示数据：真实可读取的 PDF（可搜索）、PNG（供 OCR）、XLSX。

所有演示票据均使用虚构公司/供应商/商品数据，并标注「模拟票据｜非真实业务凭证」。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

DEMO_DIR = PROJECT_ROOT / "demo_data"

MARK = "模拟票据｜非真实业务凭证"


# ---------------- 场景数据（虚构） ----------------
def _scenarios():
    sup = "华东精密制造有限公司"
    sup_tax = "91310000FAKE000A"
    sup_tax_bad = "91310000FAKE000B"
    buyer = "示例采购有限公司"
    buyer_tax = "91310000BUYER00A"

    def trade(item_no, name, spec, unit, qty, price, tax="13%"):
        amount = round(qty * price, 2)
        rate = 0.13
        tax_amt = round(amount * rate, 2)
        total = round(amount + tax_amt, 2)
        return [item_no, name, spec, unit, str(qty), f"{price:.2f}", f"{amount:.2f}",
                tax, f"{tax_amt:.2f}", f"{total:.2f}"]

    def grnline(item_no, name, spec, unit, planned, received):
        return [item_no, name, spec, unit, str(planned), str(received)]

    line = trade("ITEM-001", "不锈钢轴承", "6204", "件", 100, 200.00)

    sc = []

    # 场景 A：三单匹配一致
    sc.append(dict(
        key="A", name="三单匹配一致",
        po=dict(number="PO-DEMO-A-001", date="2026-01-05", supplier=sup, supplier_tax=sup_tax,
                buyer=buyer, buyer_tax=buyer_tax, lines=[line], total="22600.00"),
        invoices=[dict(code="3100160000", number="INV-DEMO-A-001", date="2026-01-10",
                       seller=sup, seller_tax=sup_tax, buyer=buyer, buyer_tax=buyer_tax,
                       po="PO-DEMO-A-001", lines=[line], total="22600.00")],
        grns=[dict(number="GRN-DEMO-A-001", po="PO-DEMO-A-001", date="2026-01-20",
                   supplier=sup, supplier_tax=sup_tax,
                   lines=[grnline("ITEM-001", "不锈钢轴承", "6204", "件", 100, 100)])],
        formats=dict(po="pdf", invoice="pdf", grn="xlsx"),
    ))

    # 场景 B：数量异常（发票 100 > 实收 95）
    line_b_inv = trade("ITEM-001", "不锈钢轴承", "6204", "件", 100, 200.00)
    sc.append(dict(
        key="B", name="数量异常",
        po=dict(number="PO-DEMO-B-001", date="2026-02-01", supplier=sup, supplier_tax=sup_tax,
                buyer=buyer, buyer_tax=buyer_tax, lines=[line_b_inv], total="22600.00"),
        invoices=[dict(code="3100160000", number="INV-DEMO-B-001", date="2026-02-05",
                       seller=sup, seller_tax=sup_tax, buyer=buyer, buyer_tax=buyer_tax,
                       po="PO-DEMO-B-001", lines=[line_b_inv], total="22600.00")],
        grns=[dict(number="GRN-DEMO-B-001", po="PO-DEMO-B-001", date="2026-02-15",
                   supplier=sup, supplier_tax=sup_tax,
                   lines=[grnline("ITEM-001", "不锈钢轴承", "6204", "件", 100, 95)])],
        formats=dict(po="pdf", invoice="xlsx", grn="png"),
    ))

    # 场景 C：价格异常（PO 200，发票 220）
    line_c_po = trade("ITEM-001", "不锈钢轴承", "6204", "件", 100, 200.00)
    line_c_inv = trade("ITEM-001", "不锈钢轴承", "6204", "件", 100, 220.00)
    sc.append(dict(
        key="C", name="价格异常",
        po=dict(number="PO-DEMO-C-001", date="2026-03-01", supplier=sup, supplier_tax=sup_tax,
                buyer=buyer, buyer_tax=buyer_tax, lines=[line_c_po], total="22600.00"),
        invoices=[dict(code="3100160000", number="INV-DEMO-C-001", date="2026-03-05",
                       seller=sup, seller_tax=sup_tax, buyer=buyer, buyer_tax=buyer_tax,
                       po="PO-DEMO-C-001", lines=[line_c_inv], total="24860.00")],
        grns=[dict(number="GRN-DEMO-C-001", po="PO-DEMO-C-001", date="2026-03-15",
                   supplier=sup, supplier_tax=sup_tax,
                   lines=[grnline("ITEM-001", "不锈钢轴承", "6204", "件", 100, 100)])],
        formats=dict(po="pdf", invoice="pdf", grn="pdf"),
    ))

    # 场景 D：重复发票（同一发票号码两张）
    line_d = trade("ITEM-002", "铝合金阀体", "DN50", "件", 50, 400.00)
    sc.append(dict(
        key="D", name="重复发票",
        po=dict(number="PO-DEMO-D-001", date="2026-04-01", supplier=sup, supplier_tax=sup_tax,
                buyer=buyer, buyer_tax=buyer_tax, lines=[line_d], total="22600.00"),
        invoices=[
            dict(code="3100160000", number="INV-DEMO-D-001", date="2026-04-05",
                 seller=sup, seller_tax=sup_tax, buyer=buyer, buyer_tax=buyer_tax,
                 po="PO-DEMO-D-001", lines=[line_d], total="22600.00"),
            dict(code="3100160000", number="INV-DEMO-D-001", date="2026-04-05",
                 seller=sup, seller_tax=sup_tax, buyer=buyer, buyer_tax=buyer_tax,
                 po="PO-DEMO-D-001", lines=[line_d], total="22600.00"),
        ],
        grns=[dict(number="GRN-DEMO-D-001", po="PO-DEMO-D-001", date="2026-04-15",
                   supplier=sup, supplier_tax=sup_tax,
                   lines=[grnline("ITEM-002", "铝合金阀体", "DN50", "件", 50, 50)])],
        formats=dict(po="xlsx", invoice="pdf", grn="xlsx"),
    ))

    # 场景 E：供应商税号不一致
    line_e = trade("ITEM-003", "精密齿轮", "M2-20T", "件", 200, 55.00)
    sc.append(dict(
        key="E", name="供应商税号不一致",
        po=dict(number="PO-DEMO-E-001", date="2026-05-01", supplier=sup, supplier_tax=sup_tax,
                buyer=buyer, buyer_tax=buyer_tax, lines=[line_e], total="12430.00"),
        invoices=[dict(code="3100160000", number="INV-DEMO-E-001", date="2026-05-05",
                       seller=sup, seller_tax=sup_tax_bad, buyer=buyer, buyer_tax=buyer_tax,
                       po="PO-DEMO-E-001", lines=[line_e], total="12430.00")],
        grns=[dict(number="GRN-DEMO-E-001", po="PO-DEMO-E-001", date="2026-05-15",
                   supplier=sup, supplier_tax=sup_tax,
                   lines=[grnline("ITEM-003", "精密齿轮", "M2-20T", "件", 200, 200)])],
        formats=dict(po="pdf", invoice="pdf", grn="png"),
    ))

    # 场景 F：金额计算错误（数量×单价 ≠ 金额）
    line_f_po = trade("ITEM-004", "耐高温密封圈", "Φ50", "件", 300, 15.00)
    line_f_inv = ["ITEM-004", "耐高温密封圈", "Φ50", "件", "300", "15.00", "4400.00",
                  "13%", "585.00", "5085.00"]  # 金额应为 4500.00
    sc.append(dict(
        key="F", name="金额计算错误",
        po=dict(number="PO-DEMO-F-001", date="2026-06-01", supplier=sup, supplier_tax=sup_tax,
                buyer=buyer, buyer_tax=buyer_tax, lines=[line_f_po], total="5085.00"),
        invoices=[dict(code="3100160000", number="INV-DEMO-F-001", date="2026-06-05",
                       seller=sup, seller_tax=sup_tax, buyer=buyer, buyer_tax=buyer_tax,
                       po="PO-DEMO-F-001", lines=[line_f_inv], total="5085.00")],
        grns=[dict(number="GRN-DEMO-F-001", po="PO-DEMO-F-001", date="2026-06-15",
                   supplier=sup, supplier_tax=sup_tax,
                   lines=[grnline("ITEM-004", "耐高温密封圈", "Φ50", "件", 300, 300)])],
        formats=dict(po="pdf", invoice="xlsx", grn="pdf"),
    ))

    # 场景 G：缺失收货记录
    line_g = trade("ITEM-005", "伺服电机", "750W", "台", 10, 1500.00)
    sc.append(dict(
        key="G", name="缺失收货记录",
        po=dict(number="PO-DEMO-G-001", date="2026-07-01", supplier=sup, supplier_tax=sup_tax,
                buyer=buyer, buyer_tax=buyer_tax, lines=[line_g], total="16950.00"),
        invoices=[dict(code="3100160000", number="INV-DEMO-G-001", date="2026-07-05",
                       seller=sup, seller_tax=sup_tax, buyer=buyer, buyer_tax=buyer_tax,
                       po="PO-DEMO-G-001", lines=[line_g], total="16950.00")],
        grns=[],
        formats=dict(po="pdf", invoice="pdf"),
    ))

    return sc


# ---------------- 文本构造 ----------------
def _po_text(d) -> list[str]:
    lines = [
        MARK,
        "文档类型：采购订单（PO）",
        f"采购订单编号：{d['number']}",
        f"订单日期：{d['date']}",
        f"供应商名称：{d['supplier']}",
        f"供应商税号：{d['supplier_tax']}",
        f"采购方名称：{d['buyer']}",
        f"采购方税号：{d['buyer_tax']}",
        "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：",
    ]
    for ln in d["lines"]:
        lines.append(" | ".join(ln))
    lines.append(f"合计金额：{d['total']}")
    return lines


def _invoice_text(d) -> list[str]:
    lines = [
        MARK,
        "文档类型：供应商发票（Invoice）",
        f"发票代码：{d['code']}",
        f"发票号码：{d['number']}",
        f"开票日期：{d['date']}",
        f"销售方名称：{d['seller']}",
        f"销售方税号：{d['seller_tax']}",
        f"购买方名称：{d['buyer']}",
        f"购买方税号：{d['buyer_tax']}",
        f"关联采购订单号：{d['po']}",
        "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：",
    ]
    for ln in d["lines"]:
        lines.append(" | ".join(ln))
    lines.append(f"合计金额：{d['total']}")
    return lines


def _grn_text(d) -> list[str]:
    lines = [
        MARK,
        "文档类型：收货记录（GRN）",
        f"收货单编号：{d['number']}",
        f"关联采购订单号：{d['po']}",
        f"收货日期：{d['date']}",
        f"供应商名称：{d['supplier']}",
        f"供应商税号：{d['supplier_tax']}",
        "商品明细（商品编号 | 商品名称 | 规格 | 单位 | 计划收货数量 | 实际收货数量）：",
    ]
    for ln in d["lines"]:
        lines.append(" | ".join(ln))
    return lines


# ---------------- 渲染 ----------------
def _render_pdf(path: Path, lines: list[str]) -> None:
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 60
    for i, ln in enumerate(lines):
        fontsize = 11
        if i == 0:
            fontsize = 13
        page.insert_text((50, y), ln, fontsize=fontsize, fontname="china-s")
        y += 26
    doc.save(str(path))
    doc.close()


def _render_png(path: Path, lines: list[str]) -> None:
    from PIL import Image, ImageDraw, ImageFont

    font_path = _find_cjk_font()
    font = ImageFont.truetype(font_path, 30)
    img = Image.new("RGB", (1500, 1400), "white")
    draw = ImageDraw.Draw(img)
    y = 40
    for i, ln in enumerate(lines):
        size = 34 if i == 0 else 30
        f = ImageFont.truetype(font_path, size)
        draw.text((50, y), ln, fill="black", font=f)
        y += 66
    img.save(str(path))


def _render_xlsx(path: Path, lines: list[str]) -> None:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "票据数据"
    for ln in lines:
        ws.append([ln])
    ws.column_dimensions["A"].width = 90
    wb.save(str(path))


def _find_cjk_font() -> str:
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "C:/Windows/Fonts/simsun.ttc",
        "C:/Windows/Fonts/simkai.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise RuntimeError("未找到中文字体，请检查 C:/Windows/Fonts")


def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for sc in _scenarios():
        folder = DEMO_DIR / f"scenario_{sc['key']}"
        folder.mkdir(parents=True, exist_ok=True)
        fmts = sc["formats"]

        po_lines = _po_text(sc["po"])
        _save(folder / f"PO_{sc['key']}.{fmts['po']}", fmts["po"], po_lines)
        count += 1

        for idx, inv in enumerate(sc["invoices"]):
            inv_lines = _invoice_text(inv)
            ext = fmts["invoice"] if idx == 0 else "pdf"
            _save(folder / f"Invoice_{sc['key']}_{idx+1}.{ext}", ext, inv_lines)
            count += 1

        for idx, grn in enumerate(sc["grns"]):
            grn_lines = _grn_text(grn)
            ext = fmts.get("grn", "pdf")
            _save(folder / f"GRN_{sc['key']}_{idx+1}.{ext}", ext, grn_lines)
            count += 1

    print(f"已生成 {len(_scenarios())} 组场景、{count} 个文件 -> {DEMO_DIR}")


def _save(path: Path, ext: str, lines: list[str]) -> None:
    if ext == "pdf":
        _render_pdf(path, lines)
    elif ext == "png":
        _render_png(path, lines)
    elif ext == "xlsx":
        _render_xlsx(path, lines)
    else:
        raise ValueError(f"未知格式：{ext}")


if __name__ == "__main__":
    main()
