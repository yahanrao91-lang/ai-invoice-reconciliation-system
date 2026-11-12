# 独立质量审计报告（第二轮验收）

> 审计角色：独立软件质量审计工程师 / 企业自动化系统验收工程师。
> 审计日期：2026-11-09（补充验收更新：2026-11-12，见第 15 节）
> 审计方式：重新阅读全部源码与测试、真实运行测试与端到端流程、真实调用本地 OCR、mock 验证 LLM Provider、真实启动 Streamlit 并访问 HTTP 接口。**未采信第一轮开发总结，一切结论以本轮实际执行记录为准。**

---

## 1. 审计范围

| 对象 | 是否审计 |
|------|---------|
| `app.py` | ✅ 逐行 |
| `src/invoice_matching/` 全部 11 个子模块 | ✅ 逐行 |
| `tests/` 全部测试 | ✅ 逐行 |
| `scripts/generate_demo_data.py` | ✅ 逐行 |
| `requirements.txt` / `.env.example` / `.gitignore` / `pytest.ini` / `run.bat` | ✅ |
| SQLite 数据库结构（`db.py` SCHEMA） | ✅ |
| `docs/` 全部文档 | ✅ 抽查核对与实现一致性 |
| 演示数据 7 组场景 | ✅ 真实文件重新生成并端到端重跑 |

---

## 2. 实际源码检查结果

### 2.1 架构分层（符合要求）
- 导入 → 提取（PDF/图片/Excel）→ OCR → AI/离线结构化 → 标准化 → 验证 → 三单匹配 → 异常检测 → 人工审核 → 报告，分层清晰。
- **业务规则与 AI 严格解耦**：`ai/` 只做结构化信息提取，金额计算与匹配判定全部在 `processing/` 用 `Decimal` 完成，LLM 不做金额计算、不做放行决策。✅
- 数据模型统一（`models.py`），缺失字段一律 `None`，不编造。✅

### 2.2 关键实现核对
- `document_import.py`：类型/大小校验、安全文件名、SHA-256、重复检测。✅
- `detection.py`：发票/收货/订单识别；已确认「价税合计」不会再把采购订单误判为发票（有专门回归测试）。✅
- `extraction/`：可搜索 PDF 直接取文本；扫描页转图走 OCR；多页支持；图片走 OCR；Excel 走 openpyxl；OCR 不可用时显式标记（不静默跳过）。✅
- `ai/llm_provider.py`：OpenAI-Compatible Chat Completions；读取 `LLM_BASE_URL/API_KEY/MODEL/TIMEOUT`；超时、HTTP 错误、无效 JSON 均有处理。✅（详见第 3 节）
- `ai/extractor.py`：JSON 剥离代码块、截取对象、Pydantic Schema 校验、有限重试、字段级证据。✅
- `processing/matching.py`：8 类规则全部实现，本轮修复 3 处业务缺陷（见第 12 节）。✅
- `db.py`：10 张表、外键、索引、事务、UNIQUE 防重复。✅
- `review.py`：修正/确认/驳回，保留修改前后值、时间、原因、审核人。✅
- `report.py`：7 工作表、异常着色、金额格式、自动筛选、冻结窗格、唯一文件名。✅

### 2.3 源码检查发现的问题
已全部在本轮修复（详见第 11、12 节），无遗留 CRITICAL/HIGH 缺陷。

---

## 3. LLM 真实调用验证情况

**结论（已更新）**：真实外部模型调用已于 2026-11-12 补充验收通过（DeepSeek `deepseek-flash`，发票字段验证 7/7），详见第 15 节。以下保留 2026-11-09 首轮审计时的初始状态与 mock 验证记录。

- 本地检查结果：`LLM_ENABLED=False`，`LLM_BASE_URL=''`，`LLM_MODEL=''`，`LLM_API_KEY` 未设置，`build_provider()` 返回 `None`，系统处于「离线演示模式」。✅（无密钥可泄露，也未向任何人索取密钥）
- 下列能力已通过 **mock 测试**（`tests/test_llm_provider.py`，9 项）逐一验证：

| 审计项 | 结果 |
|--------|------|
| 1. OpenAI-Compatible Chat Completions 请求 | ✅ mock 验证 URL 以 `/chat/completions` 结尾、携带 `Authorization: Bearer` 头与 `model` |
| 2. 正确读取 BASE_URL/API_KEY/MODEL | ✅ `build_provider` 未配置返回 None，已配置返回 Provider |
| 3. 请求超时处理 | ✅ `requests.Timeout` → `LlmError` |
| 4. HTTP 错误处理 | ✅ 500/401 → `LlmError` 且含状态码 |
| 5. 无效 JSON 处理 | ✅ 响应无 JSON/缺 `choices` → `LlmError` |
| 6. 结构化输出校验 | ✅ Pydantic Schema 校验（`test_validate_document_schema_*`） |
| 7. 有限重试 | ✅ `extract_with_llm_retry` 重试后成功 / 全失败抛错（`test_extract_with_llm_retry_*`） |
| 8. 保护 API Key | ✅ 断言错误信息不包含密钥（`test_provider_does_not_leak_api_key`） |
| 9. 字段缺失不编造 | ✅ Schema 缺失字段为 `null` 且记入 `missing_fields` |
| 10. 保留字段来源证据 | ✅ `evidence` 字段贯穿 Schema → 提取结果 → 数据库 |

**更新**：上述「真实网络请求未执行」的限制已于 2026-11-12 解除（真实 DeepSeek 冒烟测试通过，见第 15 节）。设计保持不变：未配置即离线、配置并启用后才真实调用、不存在伪造 LLM 结果的代码路径。

---

## 4. OCR 实际识别验证情况

**结论：本地 RapidOCR（rapidocr-onnxruntime，PP-OCR 中文 ONNX）真实可用，已验证真实识别。**

- 引擎状态实测：`{'engine': 'rapidocr', 'available': True}`。✅
- 真实识别测试：程序生成含中文的图片，`RapidOcrEngine.recognize` 返回非空文本且命中 `PO-OCR-001`。✅

| 场景 | 结果 |
|------|------|
| 1. 正常文本 PDF | ✅ `method=text`，多页 PDF 3 页文本均提取 |
| 2. 扫描版 PDF（无文本层） | ✅ 正确路由到 OCR；OCR 关闭时显式返回 `ocr_unavailable=True` + 警告（不静默） |
| 3. 多页 PDF | ✅ 逐页提取，页码保留 |
| 4. 清晰中文图片 | ✅ 真实识别成功 |
| 5. 低清晰度图片 | ⚠️ 未做专门的低清样本验证；依赖 OCR 置信度与人工复核兜底（如实标记） |
| 6. 图片旋转 | ⚠️ 已验证「旋转后仍进入 OCR 流程且不崩溃」；旋转后的识别准确率未量化验证（如实标记） |
| 7. 文件不存在 | ✅ `import_file` 校验返回「无法读取文件」/ pipeline 标记失败 |
| 8. 不支持的文件格式 | ✅ `validate_file` 拒绝（`.txt` 等） |
| 9. 文件损坏 | ✅ 损坏 PDF → 提取失败 → 文档状态 `failed` + `MISSING_DOCUMENT` 异常 |
| 10. 中文商品名称与金额识别 | ✅ 演示 PNG（含中文商品名 + 金额）真实 OCR 后正确解析 |

- **追溯性**：每页 `PageContent` 保留页码、来源、提取方式、置信度参考值；`extraction_results` 表存 `raw_text`、`evidence`。✅

---

## 5. 三单匹配业务审计结果

对 20 项复杂情形逐一核对（`processing/matching.py` + `processing/validate.py`，全部金额 `Decimal`、容差集中配置）：

| # | 情形 | 结果 |
|---|------|------|
| 1 | 一张 PO 对应多张收货记录 | ✅ 按商品聚合实收数量（`test_multi_grn_received_aggregated`） |
| 2 | 一张 PO 对应多张发票 | ✅ 按 PO 分组处理 |
| 3 | 部分收货 | ✅ 不误报（`test_partial_receipt_no_anomaly`） |
| 4 | 分批开票 | ✅ **本轮修复**：`allow_partial_invoice=True` 时累计开票金额小于订单金额不再误报（`test_partial_invoice_no_amount_diff`） |
| 5 | 多个商品明细 | ✅ 逐行匹配（`test_multi_line_items`） |
| 6 | 商品名称不同但编号相同 | ✅ 编号优先匹配，不误报（`test_item_no_priority_over_name`） |
| 7 | 商品无编号但有别名 | ✅ 别名匹配，标记 `alias`（`test_alias_matching`） |
| 8 | 计量单位不一致 | ✅ **本轮新增**：`UNIT_MISMATCH`（MEDIUM，转人工确认）（`test_unit_mismatch`） |
| 9 | 数量超过订单数量 | ✅ `QTY_OVER_PO`（`test_receipt_over_po_qty`） |
| 10 | 发票数量超过收货数量 | ✅ 单行 + **本轮新增跨发票累计核对**（`test_invoice_qty_over_receipt` / `test_multi_invoice_aggregate_over_receipt`） |
| 11 | 供应商税号不同 | ✅ `SUPPLIER_TAX_MISMATCH` |
| 12 | 重复发票 | ✅ `DUPLICATE_INVOICE`（CRITICAL） |
| 13 | 文件重复但发票号码不同 | ✅ 负向验证：不同文件不同发票号不误判；同发票号不同文件可命中（`test_distinct_invoices_no_false_duplicate` / `test_e2e_duplicate_invoice`） |
| 14 | 单价不一致 | ✅ `PRICE_DIFF`，1% 容差内不误报（`test_price_within_tolerance_not_flagged`） |
| 15 | 商品金额计算错误 | ✅ `LINE_AMOUNT_MISMATCH` |
| 16 | 税额计算错误 | ✅ `LINE_TAX_MISMATCH` |
| 17 | 多行金额合计不一致 | ✅ `PO_TOTAL_MISMATCH` / `INVOICE_TOTAL_MISMATCH` |
| 18 | 缺少采购订单 | ✅ `PO_NOT_FOUND` / `PO_NUMBER_MISSING` |
| 19 | 缺少收货记录 | ✅ `ITEM_NO_GRN` |
| 20 | 金额精度与 Decimal 舍入 | ✅ `quantize_money`（ROUND_HALF_UP，2 位）；`_close` 容差 `max(0.01, |基准|×rate)` |

**结论**：无重复计算导致的错误放行；无漏判（本轮补齐了分批开票金额与跨发票数量两个漏判点）；不确定情形（无编号/别名/单位不一致/商品不在订单）均进入人工确认而非自动放行。系统不假设统一税务/折扣处理方式，金额规则精度与容差明确。

---

## 6. 数据库持久化审计结果

- **重开历史任务**：✅ 关闭并重开 `Database`（新连接、同路径），任务与文档仍存在（`test_persistence_across_reopen`）。
- **历史数据持久化**：✅ SQLite 文件落盘（`data/invoice_matching.db`），本地存储。
- **多次修改保留历史**：✅ 两次修正产生两条记录，分别保留各自修改前值（`test_multiple_corrections_preserve_history`）。
- **审核记录含修改前后值**：✅ `review_records.old_value/new_value`（`test_apply_correction_records_old_new_and_updates`）。
- **事务**：✅ 关键写入用 `Database.transaction()`；异常回滚验证通过（`test_transaction_rollback`）。
- **失败操作不留残缺数据**：✅ 事务回滚；损坏文件在提取失败时文档状态置 `failed`，不产生半成品业务单据。
- **重复发票双重检查**：
  - 文件级：`documents` 表 `UNIQUE(file_hash, task_id)`（数据库约束）✅
  - 业务级：匹配引擎 `_invoice_key` → `DUPLICATE_INVOICE`（CRITICAL 异常）✅
  - 说明：发票号未加数据库硬唯一约束，是**有意为之**——演示场景 D 需要「识别并标记重复」而非在入库时阻断第二张发票。
- **严重异常能否绕过人工审核**：❌ 不能。异常默认 `status='open'`（`test_anomaly_defaults_open`），界面只列出 open 异常，确认/驳回必须填写意见并由人点击；代码中不存在自动确认路径。

---

## 7. 人工审核工作流审计结果

- 字段修正：`apply_correction` 读取旧值 → 校验字段路径 → 解析新值 → 回写提取结果与业务单据 → 记录审核留痕。✅
- 修正留痕包含：`field_path`、`old_value`、`new_value`、`reason`、`reviewer`、`created_at`。✅
- 异常确认/驳回：`record_confirmation` 更新异常状态为 `confirmed/rejected`，并写审核记录与审计日志。✅
- 审计日志：创建任务、导入、提取、匹配、修正、确认/驳回均有记录。✅

**遗留限制（如实说明）**：点击「重新执行匹配」会重建异常表（DELETE+INSERT），已确认/驳回的异常状态会回到 `open`；但审核操作历史保留在 `review_records` 表（报告「人工审核历史」工作表读取该表），审计线索不丢失。

---

## 8. Web 交互验收情况

**不把 HTTP 200 当作全部页面验收通过。** 本轮回验如下：

- **HTTP 冒烟**：headless 启动 `streamlit run app.py`，访问 `http://localhost:8511` 返回 **HTTP 200**。✅
- **AppTest 交互**（`tests/test_app.py`，9 项）：
  - 应用启动无异常。✅
  - 七个页面逐一通过侧边栏导航切换并渲染，均无异常。✅
  - 历史页能读取已入库任务并显示在任务下拉框（验证界面与数据库真实连通）。✅
- **真实 UI 实操（2026-11-12 补充）**：场景 B 已通过界面完成「导入 → AI/OCR 提取 → 三单匹配 → 异常确认 → 报告导出」，人工审核记录落库（`review_records`，action=`confirm`）。详见第 15 节。✅
- **未自动化的人工交互步骤**（需人工点击验收，如实列出）：
  1. 「文档管理」批量上传 PO/Invoice/GRN → 点击「创建对账任务并处理」；
  2. 文件类型判断与文档信息预览（删除按钮）；
  3. 「AI 信息提取」查看 OCR 原文 / 结构化 JSON / 字段证据，并保存一次字段修正；
  4. 「三单匹配」重新执行匹配、查看异常差异图标；
  5. 「人工审核」填写意见并确认/驳回；
  6. 「历史记录与报告」生成并下载 Excel 报告并打开核对。
  > 上述 6 步对应的**服务层逻辑**（上传/提取/匹配/审核/报告）已被自动化测试覆盖；仅浏览器点击本身未逐项自动化。现场演示步骤见 `docs/demo_script.md`。

---

## 9. 自动化测试真实结果

本轮实际执行（`pytest --cov=invoice_matching`）：

```
92 passed, 4 warnings in ~12s
```

相比第一轮声称的 45 项，本轮新增 47 项，覆盖：LLM Provider（9 项 mock）、三单匹配复杂情形（15 项）、文档类型识别（7 项）、PDF 多页/扫描/损坏、图片旋转、数据库重开/事务回滚/删除清理、多发票/多收货/重复发票端到端。

未删除任何测试、未降低断言、未隐藏错误。✅

## 10. 覆盖率

```
TOTAL 1697 stmts, 88% 行覆盖率
```

| 模块 | 覆盖率 | 模块 | 覆盖率 |
|------|--------|------|--------|
| llm_provider.py | 100% | detection.py | 96% |
| config.py | 98% | db.py | 93% |
| matching.py | 90% | validate.py | 84% |
| extraction/__init__.py | 88% | report.py | 78% |
| ocr.py | 62% | pdf_extractor.py | 74% |

低覆盖区为可选引擎分支（PaddleOCR/Tesseract）与报告着色等展示分支，核心业务路径覆盖充分。✅

---

## 11. 漏洞和缺陷（审计发现，均已在第 12 节修复）

| 级别 | 缺陷 | 根源 | 影响 |
|------|------|------|------|
| HIGH | `PO_INVOICE_AMOUNT_DIFF` 在分批开票时误报 | `allow_partial_invoice` 定义了但从未使用，发票合计 < 订单金额仍报金额差异 | 部分开票的合法业务被误判异常 |
| HIGH | 多张发票累计数量超收漏判 | 数量核对只按单行发票 vs 总实收比较，未跨发票汇总 | 两张 60 的发票合计 120 > 实收 100 无法发现 |
| MEDIUM | 计量单位不一致完全未检查 | 匹配只按编号/名称，未比较标准化后的单位 | 100 件 vs 100 箱被当作相等 |
| MEDIUM | 删除文档留下孤儿业务单据 | `business_documents.document_id` 为 `SET NULL`，仅删 `documents` 行 | 潜在数据不一致（当前 UI 仅允许删除未处理文档，未实际暴露） |
| LOW | 死代码/冗余表达式 | `offline_parser` 置信度三元表达式两分支相同；`db.dashboard_stats` 未使用变量 | 可读性 |

---

## 12. 已修复问题

1. **分批开票金额误报（HIGH）**：`matching.py` 中仅当「不允许分批开票」或「累计开票金额 > 订单金额（超开票）」时才报 `PO_INVOICE_AMOUNT_DIFF`。
2. **跨发票累计数量核对（HIGH）**：新增 `_item_key` / `_received_for_key` / `_check_aggregate_qty`，多张发票按商品汇总开票数量与实收数量比较，超收补充告警并同步行状态。
3. **单位不一致检查（MEDIUM）**：新增 `UNIT_MISMATCH`（MEDIUM，转人工确认）。
4. **删除文档清理业务单据（MEDIUM）**：`delete_document` 在同一事务内先删 `business_documents` 再删 `documents`。
5. **死代码清理（LOW）**：`offline_parser.py` 置信度表达式、`db.dashboard_stats` 未使用变量。

每项修复均新增对应测试，修复后全量回归通过（92 passed），未引入其他问题。

---

## 13. 未解决问题（如实列出）

1. ~~真实 LLM 网络调用未验证~~ **已解决**：2026-11-12 完成真实 DeepSeek 冒烟测试，字段验证 7/7（见第 15 节）。
2. **PaddleOCR / Tesseract 可选引擎未做真实集成测试**：本机未装对应依赖，默认 RapidOCR 已实测可用。
3. **低清晰度/旋转图片的 OCR 准确率未量化**：已验证不崩溃与真实识别，极端模糊仍需人工复核。
4. **跨格式语义重复未检测**：同一发票以 PDF 与扫描件两种形式、OCR 后号码不同，无法通过 SHA-256 或发票号去重（需要内容级相似度，超出当前范围）。
5. **「重新执行匹配」重建异常状态**：已确认/驳回的异常状态回到 open（审核历史保留）。
6. **测试卫生**：少量测试未显式关闭 SQLite 连接，产生 ResourceWarning（非产品缺陷）。

---

## 14. GitHub 安全检查结果

| 检查项 | 结果 |
|--------|------|
| `.env` 被忽略 | ✅ `.gitignore` 含 `.env`；实测 `git check-ignore` 命中 |
| `.venv` 被忽略 | ✅ |
| SQLite 运行库被忽略 | ✅ `data/`、`*.db`、`*.sqlite3` 命中 |
| 上传的真实文档被忽略 | ✅ `data/uploads/`（在 `data/` 下） |
| 生成的报告/日志被忽略 | ✅ `data/exports/`、`data/logs/`、`exports/` |
| 演示数据纳入版本控制 | ✅ `demo_data/` 七组虚构演示票据已解除忽略、随仓库提交（全部含「模拟票据｜非真实业务凭证」标注，无真实企业/个人信息） |
| 硬编码密钥 | ✅ 未发现真实密钥；唯一命中为 README 中的占位符 `sk-xxxx`（文档示例，非密钥） |
| 真实企业票据/个人信息 | ✅ 未发现；演示数据全部虚构并含「模拟票据｜非真实业务凭证」 |
| 独立 Git 仓库 | ✅ 项目根为独立仓库，与兄弟项目 `企业库存自动化项目` 完全分离 |
| 未执行 git push / 发布 | ✅ 本仓库仅有未提交的本地工作区，未 commit、未 push |

`git status --short` 仅列出源码/配置/文档/测试与 `demo_data/`（七组虚构演示票据），无 `data/`、`.env`、`.venv`。✅

---

## 15. 补充验收结果（2026-11-12，真实 DeepSeek LLM）

> 本次补充针对上一轮唯一未决项——真实 LLM 网络调用——以及端到端 UI 实操。全部为实际执行记录，非 mock、非离线。

### 15.1 真实 LLM 冒烟测试（`scripts/smoke_test_llm.py`）

```
模型名称：deepseek-flash
服务地址：https://api.deepseek.com
Schema 验证：通过（Pydantic DocumentSchema）
[通过] 发票号码：实际=DEMO-INV-20261109
[通过] 供应商：实际=测试科技有限公司
[通过] 商品名称：实际=机械键盘
[通过] 数量：实际=10.0000
[通过] 单价：实际=200.00
[通过] 金额：实际=2000.00
[通过] 税率：实际=0.13
字段验证：7/7 全部通过
提取方式：ai
结果：通过
```

输入为完全虚构的发票文本（含「模拟票据｜非真实业务凭证」标识），未使用任何真实票据。

### 15.2 场景 B 端到端 AI 实操（SQLite 只读核验）

| 项目 | 实际记录 |
|------|---------|
| 任务 | `场景B-数量差异验收`，状态 `completed` |
| 三份文件 | `PO_B.pdf`（text）、`Invoice_B_1.xlsx`（text）、`GRN_B_1.png`（RapidOCR） |
| 结构化提取方式 | 三份文档 `extraction_results.method` 均为 `ai`（真实 DeepSeek，非离线） |
| 匹配结果 | `INV-DEMO-B-001` 发票数量 100.0000 vs 实收 95.0000，`status=存在数量差异` |
| 异常 | `QTY_OVER_RECEIPT`（HIGH），证据 `invoice_qty=100.0000, received_qty=95.0000` |
| 人工审核 | `review_records` 1 条，action=`confirm`，reviewer=`审核员`，含审核意见 |
| 持久化 | 任务/文档/业务单据/行明细/匹配/异常/审核/日志等 10 张表均落库，可重开历史任务 |

### 15.3 Excel 报告核验

`data/exports/对账报告_任务1_20261112_175711.xlsx` 共 **7 张工作表**且有数据：`对账总览`、`采购订单明细`、`发票明细`、`收货记录明细`、`三单匹配结果`、`异常记录`、`人工审核历史`。

### 15.4 RapidOCR 中文识别

场景 B 的 `GRN_B_1.png`（PNG 收货单）经本地 RapidOCR 真实识别（`documents.extraction_method=ocr`），OCR 文本再由 DeepSeek 结构化提取为 GRN（`method=ai`），中文商品名「不锈钢轴承」与数量正确。

---

## 16. 最终验收结论

**结论：A —— 正式通过（可作为求职作品展示）。**

判定理由：
- ✅ 核心业务闭环真实可用：92 项测试全部通过、88% 覆盖率、7 组演示场景端到端符合预期、本地 RapidOCR 真实识别中文票据、Streamlit 七页渲染 + HTTP 200。
- ✅ **真实 LLM 已验收**：DeepSeek（`deepseek-flash`）冒烟测试通过，发票字段验证 7/7；场景 B 的 PO/Invoice/GRN 三份文件结构化提取方式均为 `ai`（真实模型，非离线）。
- ✅ **端到端 UI 实操已验证**：场景 B 经界面完成「导入 → AI/OCR 提取 → 三单匹配 → 异常确认 → SQLite 持久化」，`QTY_OVER_RECEIPT` 正确识别并人工确认，Excel 报告 7 张工作表已核验。
- ✅ 审计发现并修复 2 HIGH / 2 MEDIUM / 1 LOW，均补测试，未伪造结果；核心业务不存在 C 级缺陷。

**必须如实保留的边界（不夸大）**：
- 本项目是**个人独立开发的学习/求职原型**，未上线、无真实客户、无商业部署。
- 真实验收范围为一组演示场景（场景 B）与一次真实 LLM 冒烟测试；**未声称所有生产环境功能已验证**（多用户并发、权限隔离、真实税务查验、ERP/付款对接等均不在本项目范围）。
- 真实 AI 提取仅在用户主动配置 `.env` 并启用后才会发起；未配置时系统以离线模式运行并明确标识。

---

*本报告全部结论由本轮实际执行记录支持；未采信第一轮开发总结，未删除测试，未伪造成功。*
