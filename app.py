"""AI 智能票据审核与采购对账系统 — Streamlit Web 界面（全中文）。"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import streamlit as st  # noqa: E402

from invoice_matching.config import settings  # noqa: E402
from invoice_matching.db import Database  # noqa: E402
from invoice_matching.extraction.ocr import OcrManager  # noqa: E402
from invoice_matching.logging_config import setup_logging  # noqa: E402
from invoice_matching.models import DocumentType  # noqa: E402
from invoice_matching.pipeline import Pipeline  # noqa: E402
from invoice_matching.report import generate_report  # noqa: E402
from invoice_matching.review import apply_correction, record_confirmation  # noqa: E402

st.set_page_config(page_title="AI 智能票据审核与采购对账系统", page_icon="🧾", layout="wide")

settings.ensure_dirs()
setup_logging(settings.log_dir)

_DOC_TYPE_LABEL = {
    "purchase_order": "采购订单 PO",
    "invoice": "供应商发票 Invoice",
    "goods_receipt_note": "收货记录 GRN",
}


@st.cache_resource
def get_db() -> Database:
    return Database()


@st.cache_resource
def get_ocr() -> OcrManager:
    return OcrManager()


@st.cache_resource
def get_pipeline() -> Pipeline:
    return Pipeline(db=get_db(), ocr_manager=get_ocr())


def fmt(v):
    """友好显示 Decimal/None。"""
    if v is None:
        return ""
    s = str(v)
    if s.endswith(".00"):
        return s[:-3]
    return s


def render_entity_lines(lines):
    rows = []
    for ln in lines:
        if hasattr(ln, "received_qty"):
            rows.append({
                "商品编号": ln.item_no or "", "商品名称": ln.name or "", "规格": ln.spec or "",
                "单位": ln.unit or "", "计划收货数量": fmt(ln.planned_qty), "实际收货数量": fmt(ln.received_qty),
            })
        else:
            rows.append({
                "商品编号": ln.item_no or "", "商品名称": ln.name or "", "规格": ln.spec or "",
                "单位": ln.unit or "", "数量": fmt(ln.quantity), "单价": fmt(ln.unit_price),
                "金额": fmt(ln.amount), "税率": fmt(ln.tax_rate), "税额": fmt(ln.tax_amount),
                "价税合计": fmt(ln.line_total),
            })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("无明细行")


def page_overview():
    st.header("业务总览")
    db = get_db()
    stats = db.dashboard_stats()
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("对账任务总数", stats["total_tasks"])
    c2.metric("匹配成功任务", stats["matched_ok"])
    c3.metric("存在异常任务", stats["with_anomalies"])
    c4.metric("待人工审核异常", stats["pending_review"])
    c5.metric("重复发票", stats["duplicate_invoices"])

    st.subheader("最近处理任务")
    tasks = db.list_tasks()[:10]
    if tasks:
        st.dataframe(
            [{"任务编号": t["id"], "名称": t["name"], "状态": t["status"],
              "创建时间": t["created_at"], "更新时间": t["updated_at"]} for t in tasks],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("暂无任务，请到「文档管理」页面上传文档并创建对账任务。")


def page_documents():
    st.header("文档管理")
    db = get_db()
    pipe = get_pipeline()

    st.subheader("1. 批量上传文档")
    uploaded = st.file_uploader(
        "支持 PDF / PNG / JPG / XLSX，可多选", type=["pdf", "png", "jpg", "jpeg", "xlsx"],
        accept_multiple_files=True,
    )
    task_name = st.text_input("对账任务名称", value="我的对账任务")

    if st.button("创建对账任务并处理", type="primary", disabled=not uploaded):
        tmpdir = Path(tempfile.mkdtemp())
        paths = []
        for u in uploaded:
            p = tmpdir / u.name
            p.write_bytes(u.getbuffer())
            paths.append(p)
        with st.spinner("正在导入、提取并执行三单匹配..."):
            result = pipe.full_run(task_name, paths)
        task_id = result["task_id"]
        ok_import = sum(1 for x in result["imported"] if x["ok"])
        st.success(f"任务 #{task_id} 处理完成：导入 {ok_import}/{len(paths)} 个文件，"
                   f"匹配行 {result['matching']['line_match_count']}，异常 {result['matching']['anomaly_count']}。")
        for x in result["imported"]:
            if not x["ok"]:
                st.warning(f"文件 {x['name']}：{x['message']}")
        st.session_state["active_task"] = task_id

    st.divider()
    st.subheader("2. 文档列表与状态")
    tasks = db.list_tasks()
    if not tasks:
        st.info("请先创建对账任务。")
        return
    options = {f"#{t['id']} {t['name']}": t["id"] for t in tasks}
    sel = st.selectbox("选择任务", list(options.keys()))
    task_id = options[sel]
    docs = db.list_documents(task_id)
    if docs:
        for d in docs:
            col1, col2, col3, col4, col5 = st.columns([3, 2, 2, 2, 1])
            col1.write(f"**{d['original_name']}**")
            col2.write(_DOC_TYPE_LABEL.get(d["doc_type"], "未识别"))
            col3.write(f"状态：{d['status']}")
            col4.write(f"提取方式：{d['extraction_method'] or '—'}")
            if d["status"] in ("imported", "failed", "needs_review") and col5.button("删除", key=f"del{d['id']}"):
                db.delete_document(d["id"])
                st.rerun()
    else:
        st.info("该任务下暂无文档。")


def page_extraction():
    st.header("AI 信息提取")
    db = get_db()
    tasks = db.list_tasks()
    if not tasks:
        st.info("暂无任务。")
        return
    options = {f"#{t['id']} {t['name']}": t["id"] for t in tasks}
    task_id = options[st.selectbox("选择任务", list(options.keys()))]
    docs = db.list_documents(task_id)
    if not docs:
        st.info("该任务下暂无文档。")
        return
    doc_options = {f"#{d['id']} {d['original_name']}": d["id"] for d in docs}
    doc_id = doc_options[st.selectbox("选择文档", list(doc_options.keys()))]
    doc = db.get_document(doc_id)
    ext = db.get_extraction(doc_id)

    if not ext:
        st.warning("该文档尚未完成结构化提取。")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("文档类型", _DOC_TYPE_LABEL.get(ext["doc_type"], "未识别"))
    c2.metric("提取方式", ext["method"])
    c3.metric("可信度参考值", f"{ext['confidence']:.2f}")
    c4.metric("缺失字段", len(ext["missing_fields"] or []))

    if ext["missing_fields"]:
        st.warning("缺失字段提醒：" + "、".join(ext["missing_fields"]))
    if ext["needs_review"]:
        st.info("待确认事项：" + "；".join(ext["needs_review"]))

    tab1, tab2, tab3 = st.tabs(["OCR / 原始文本", "结构化 JSON", "字段来源证据"])
    with tab1:
        st.text_area("提取到的文本", ext["raw_text"], height=260)
    with tab2:
        st.json(ext["data"] if ext["data"] else {})
    with tab3:
        if ext["evidence"]:
            st.dataframe(
                [{"字段": k, "原始文本证据": v} for k, v in ext["evidence"].items()],
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("无字段级证据。")

    st.divider()
    st.subheader("人工修正")
    if ext["data"]:
        st.caption("字段路径示例：supplier_name、total_amount、lines[0].quantity、lines[0].unit_price")
        col1, col2, col3, col4 = st.columns([2, 2, 2, 2])
        field_path = col1.text_input("字段路径", value="")
        new_value = col2.text_input("新值", value="")
        reason = col3.text_input("修改原因", value="人工核对修正")
        reviewer = col4.text_input("审核人", value="审核员")
        if st.button("保存修正", disabled=not (field_path and new_value)):
            err, rid = apply_correction(db, task_id, doc_id, field_path, new_value, reason, reviewer)
            if err:
                st.error(err)
            else:
                st.success(f"修正已保存（审核记录 #{rid}）")
                st.rerun()
    else:
        st.info("该文档无结构化数据可修正，请在人工审核页面手工录入。")


def page_matching():
    st.header("三单匹配")
    db = get_db()
    tasks = db.list_tasks()
    if not tasks:
        st.info("暂无任务。")
        return
    options = {f"#{t['id']} {t['name']}": t["id"] for t in tasks}
    task_id = options[st.selectbox("选择任务", list(options.keys()))]

    if st.button("重新执行匹配"):
        pipe = get_pipeline()
        aliases = db.load_aliases()
        res = pipe.run_matching(task_id, aliases)
        st.success(f"匹配完成：异常 {res['anomaly_count']}，匹配行 {res['line_match_count']}")

    biz = db.get_business_documents(task_id)
    pos = [b for b in biz if b["doc_type"] == "purchase_order"]
    invs = [b for b in biz if b["doc_type"] == "invoice"]
    grns = [b for b in biz if b["doc_type"] == "goods_receipt_note"]

    tab1, tab2, tab3, tab4 = st.tabs(["采购订单", "发票", "收货记录", "匹配结果"])
    with tab1:
        for b in pos:
            e = b["entity"]
            st.markdown(f"**订单编号：{e.po_number}**　日期：{e.order_date}　供应商：{e.supplier_name}")
            st.caption(f"供应商税号：{e.supplier_tax_no}　采购方：{e.buyer_name}　总金额：{fmt(e.total_amount)}")
            render_entity_lines(e.lines)
    with tab2:
        for b in invs:
            e = b["entity"]
            st.markdown(f"**发票号码：{e.invoice_number}**　日期：{e.invoice_date}　销售方：{e.seller_name}")
            st.caption(f"关联订单：{e.po_number}　合计金额：{fmt(e.total_amount)}")
            render_entity_lines(e.lines)
    with tab3:
        for b in grns:
            e = b["entity"]
            st.markdown(f"**收货单编号：{e.grn_number}**　日期：{e.receipt_date}　供应商：{e.supplier_name}")
            st.caption(f"关联订单：{e.po_number}")
            render_entity_lines(e.lines)
    with tab4:
        matches = db.get_line_matches(task_id)
        if matches:
            st.dataframe(
                [{
                    "发票号码": m["invoice_number"], "商品编号": m["item_no"], "商品名称": m["name"],
                    "订单商品": m["po_name"], "匹配依据": m["match_basis"], "订单数量": m["po_qty"],
                    "实收数量": m["received_qty"], "发票数量": m["invoice_qty"],
                    "订单单价": m["po_price"], "发票单价": m["invoice_price"], "状态": m["status"],
                } for m in matches],
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("暂无匹配结果。")

    st.divider()
    st.subheader("异常记录")
    anomalies = db.get_anomalies(task_id)
    if anomalies:
        for a in anomalies:
            sev = a["severity"]
            icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "INFO": "🔵"}.get(sev, "⚪")
            status = a["status"]
            st.markdown(f"{icon} **[{sev}]** {a['message']}（`{a['code']}`，状态：{status}）")
    else:
        st.success("未发现异常，三单匹配一致。")


def page_review():
    st.header("人工审核")
    db = get_db()
    tasks = db.list_tasks()
    if not tasks:
        st.info("暂无任务。")
        return
    options = {f"#{t['id']} {t['name']}": t["id"] for t in tasks}
    task_id = options[st.selectbox("选择任务", list(options.keys()))]

    anomalies = [a for a in db.get_anomalies(task_id) if a["status"] == "open"]
    if not anomalies:
        st.success("没有待处理的异常。")
        return

    st.subheader("待处理异常")
    for a in anomalies:
        with st.container(border=True):
            sev = a["severity"]
            icon = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "INFO": "🔵"}.get(sev, "⚪")
            st.markdown(f"{icon} **[{sev}]** {a['message']}")
            st.caption(f"代码 `{a['code']}`　单据：{a['entity_type']} {a['entity_ref']}　字段：{a['field'] or '—'}")
            c1, c2, c3 = st.columns([3, 2, 1])
            opinion = c1.text_input("审核意见", key=f"op{a['id']}", placeholder="填写处理结论")
            reviewer = c2.text_input("审核人", value="审核员", key=f"rv{a['id']}")
            confirm = c3.button("确认通过", key=f"cf{a['id']}")
            reject = c3.button("驳回", key=f"rj{a['id']}")
            if confirm and opinion:
                record_confirmation(db, task_id, a["id"], opinion, reviewer, confirm=True)
                st.rerun()
            if reject and opinion:
                record_confirmation(db, task_id, a["id"], opinion, reviewer, confirm=False)
                st.rerun()

    st.divider()
    st.subheader("审核操作历史")
    reviews = db.get_review_records(task_id)
    if reviews:
        st.dataframe(
            [{"操作": r["action"], "字段": r["field_path"], "修改前": r["old_value"],
              "修改后": r["new_value"], "原因": r["reason"], "审核人": r["reviewer"],
              "时间": r["created_at"]} for r in reviews],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("暂无审核记录。")


def page_history():
    st.header("历史记录与报告")
    db = get_db()
    tasks = db.list_tasks()
    if not tasks:
        st.info("暂无历史任务。")
        return
    options = {f"#{t['id']} {t['name']}": t["id"] for t in tasks}
    task_id = options[st.selectbox("选择任务", list(options.keys()))]
    task = db.get_task(task_id)

    c1, c2, c3 = st.columns(3)
    c1.metric("任务状态", task["status"])
    c2.metric("创建时间", task["created_at"])
    c3.metric("文档数", len(db.list_documents(task_id)))

    if st.button("生成并下载 Excel 对账报告", type="primary"):
        path = generate_report(task_id, db, settings.export_dir)
        st.download_button(
            "下载报告", data=path.read_bytes(), file_name=path.name,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    st.subheader("操作日志（审计）")
    logs = db.get_audit_logs(task_id)
    if logs:
        st.dataframe(
            [{"时间": l["created_at"], "操作": l["action"], "详情": l["detail"]} for l in logs],
            use_container_width=True, hide_index=True,
        )
    else:
        st.info("暂无操作日志。")


def page_system():
    st.header("系统状态与配置")
    ocr = get_ocr()
    status = ocr.status()
    c1, c2, c3 = st.columns(3)
    c1.metric("OCR 引擎", status["engine"])
    c2.metric("OCR 可用", "是" if status["available"] else "否")
    c3.metric("LLM 已启用", "是" if (settings.llm_configured and settings.llm_enabled) else "否")

    st.write("OCR 状态信息：", status["message"])
    st.write("LLM Base URL：", settings.llm_base_url or "（未配置）")
    st.write("LLM 模型：", settings.llm_model or "（未配置）")
    st.info(
        "当前系统为「离线演示模式」：使用本地规则解析随项目提供的模拟文档，OCR 使用本地 RapidOCR。"
        "配置 LLM_ENABLED=1 与 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL 后可启用真实大模型结构化提取。"
    )

    st.subheader("商品别名映射维护")
    db = get_db()
    c1, c2 = st.columns(2)
    canonical = c1.text_input("规范键（如商品编号）", key="canonical")
    alias = c2.text_input("别名", key="alias")
    if st.button("添加别名", disabled=not (canonical and alias)):
        db.add_alias(canonical, alias)
        st.rerun()
    aliases = db.list_aliases()
    if aliases:
        for a in aliases:
            col1, col2 = st.columns([4, 1])
            col1.write(f"`{a['canonical']}` → `{a['alias']}`")
            if col2.button("删除", key=f"alias{a['id']}"):
                db.delete_alias(a["id"])
                st.rerun()


def main():
    st.sidebar.title("🧾 AI 票据审核与采购对账")
    st.sidebar.caption("三单匹配 · 异常检测 · 人工审核")
    page = st.sidebar.radio(
        "导航",
        ["首页：业务总览", "文档管理", "AI 信息提取", "三单匹配", "人工审核",
         "历史记录与报告", "系统状态与配置"],
    )
    st.sidebar.divider()
    st.sidebar.caption("本系统输出对账审核建议，非付款授权，亦非税务真伪查验结论。")

    if page == "首页：业务总览":
        page_overview()
    elif page == "文档管理":
        page_documents()
    elif page == "AI 信息提取":
        page_extraction()
    elif page == "三单匹配":
        page_matching()
    elif page == "人工审核":
        page_review()
    elif page == "历史记录与报告":
        page_history()
    else:
        page_system()


if __name__ == "__main__":
    main()
