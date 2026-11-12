# GitHub 发布前检查清单

> 项目：AI 智能票据审核与采购对账系统
> 检查日期：2026-11-12
> 检查范围：80 个未跟踪文件（79 个项目文件 + 本清单自身），全部尚未 `git add`
> 结论：**可以发布**；除「补拍截图 / 建仓与首次推送」等人工动作外，无阻塞项。

---

## 一、发布建议（结论）

**建议发布。** 在真实环境完成了以下验证，且未发现任何 CRITICAL/HIGH 级问题：

- 92 项自动化测试全部通过（exit 0，0 失败 / 0 跳过 / 0 错误）。
- 真实 DeepSeek LLM 冒烟测试通过（发票字段验证 7/7），三单匹配场景 B 端到端实操通过（AI/OCR 提取 → `QTY_OVER_RECEIPT` → 人工审核 → Excel 报告）。
- 敏感信息扫描全部为误报，无真实密钥 / 个人信息 / 真实票据入库。
- 依赖完整，README 中的命令与当前目录结构一致。

发布前仅剩**人工动作**（见第九节），不涉及代码修改。

---

## 二、检查结果总表

| # | 检查项 | 结果 | 说明 |
|---|--------|------|------|
| 1 | 完整 git status | ✅ 通过 | `No commits yet`，80 个未跟踪文件，无意外文件、无已跟踪误加 |
| 2 | 文件核对（79+1） | ✅ 通过 | 见第八节清单，无遗漏、无多余 |
| 3 | 七组虚构演示数据可公开 | ✅ 通过 | 21 个文件全部含「模拟票据｜非真实业务凭证」，无真实企业/个人信息 |
| 4 | 敏感路径不被提交 | ✅ 通过 | `.env` `.venv/` `data/` `logs/` `exports/` `*.db` `*.sqlite3` `.coverage` 全部被 `git check-ignore` 命中 |
| 5 | 敏感信息扫描 | ✅ 通过 | 56 个文本文件 7 处命中，**均为误报**（占位符/mock/代码字段名），无真实密钥、手机号、邮箱、身份证、银行卡 |
| 6 | README 图片路径 | ✅ 通过 | `docs/screenshots/01_业务总览.png` 存在且被引用；其余 4 张为注释占位 |
| 7 | README 命令与目录一致 | ✅ 通过 | 绝对路径与 `.venv\Scripts\python.exe` 用法均与实际一致 |
| 8 | requirements.txt 依赖完整 | ✅ 通过 | 本轮补充缺失的 `pytest-cov>=4.1`，venv 实测 pytest 9.2.0 / pytest-cov 7.1.0 |
| 9 | pytest 92 项通过 | ✅ 通过 | 本轮实测 `92 passed`（223.82s，exit 0），见第三节 |
| 10 | 临时/残留/大文件 | ✅ 通过 | 无 `.tmp/.bak/.pyc` 残留，无 >1MB 文件 |
| 11 | 发布文件清单 | ✅ 通过 | 见第八节，共 80 个（含本清单） |
| 12 | 仓库简介与标签 | ✅ 已给出 | 见第十节 |

---

## 三、自动化测试结果（本轮实测）

后台任务 `b0hoqkuf8` 完整输出：

```
........................................................................ [ 78%]
....................                                                     [100%]
92 passed in 223.82s (0:03:43)

[exited with code 0]
```

| 项目 | 结果 |
|------|------|
| 收集测试数量（`--collect-only`） | **92 tests collected in 0.59s** |
| 通过 | **92 passed** |
| 失败 / 跳过 / 错误 | **0 / 0 / 0**（输出全为 `.`，无 `F`/`s`/`E`/`x` 标记） |
| 退出码 | **0** |
| 耗时 | 223.82s（0:03:43），主要来自 Streamlit AppTest 页面渲染 |
| pytest 版本 | 9.2.0（当前 `.venv` 实测） |
| pytest-cov 版本 | 7.1.0（当前 `.venv` 实测） |
| 测试函数定义数 | 86 个 `def test_`（含参数化展开为 92 例） |

**是否通过删除测试 / 降低断言获得成功：否。** 依据：

- `--collect-only` 收集数 = 92，与 `92 passed` 完全一致，不存在被跳过、被 deselected 或收集不到的用例。
- `tests/` 下 11 个测试文件全部完整（见第八节），本轮未删除、未改动任何测试文件。
- 历轮审计均为**只增测试**（45 → 92），从未删除测试或弱化断言。

---

## 四、敏感信息检查

- 扫描范围：全部预计提交的文本文件（56 个 `.py/.md/.txt/.ini/.bat/.env.example` 等）。
- 命中 7 处，逐一人工核对，**全部为误报**：
  - `sk-xxxx` / `你的密钥` —— 文档占位符；
  - `sk-TEST-KEY` —— 测试 mock 常量；
  - `api_key` 相关 —— 代码中的字段名 / `api_key=settings.llm_api_key` / `api_key = os.getenv(...)` 等正常代码；
  - 检测脚本自身 `api[_-]?key` 正则源码。
- 未发现真实 API Key、Bearer Token、手机号、邮箱、身份证号、银行卡号、IP 或真实票据内容。

---

## 五、演示数据公开性检查

- `demo_data/` 共 21 个文件（7 组场景的 PDF / PNG / XLSX），全部由 `scripts/generate_demo_data.py` 生成。
- 全部文件含「模拟票据｜非真实业务凭证」标记（PNG 通过脚本水印常量 `MARK` 生成）。
- 全部为虚构公司 / 供应商 / 商品 / 税号，不含真实企业名称、联系方式、个人信息或真实发票号码。
- 结论：**可公开，不构成真实税务或付款凭证**（README「重要声明」已明确）。

---

## 六、依赖完整性

`requirements.txt` 现有条目：

```
streamlit>=1.40            # Web 界面
pymupdf>=1.24              # PDF 文本处理
openpyxl>=3.1              # Excel 读取与报告生成
pillow>=10.0               # 图片处理
pydantic>=2.7              # 结构化数据校验
python-dotenv>=1.0         # 环境变量配置
requests>=2.31             # LLM API 调用
rapidocr-onnxruntime>=1.2.3  # 本地中文 OCR 引擎
pytest>=8.0                # 测试
pytest-cov>=4.1            # 覆盖率（本轮补充）
```

- 当前 `.venv` 实测：pytest **9.2.0**、pytest-cov **7.1.0**，均满足 `>=` 约束。
- README 两条测试命令在 `pip install -r requirements.txt` 后均可用：
  - `.venv\Scripts\python.exe -m pytest` ✅
  - `.venv\Scripts\python.exe -m pytest --cov=invoice_matching --cov-report=term-missing` ✅（依赖 pytest-cov，已装）
- 运行类依赖（streamlit / pymupdf / openpyxl / pillow / pydantic / python-dotenv / requests / rapidocr-onnxruntime）均已列入。

---

## 七、README 完整性

- 结构完整：业务背景 → 核心能力 → 技术栈 → 目录结构 → 安装与启动 → 演示场景 → 测试 → 局限性 → 安全与合规。
- 图片路径：`![首页：业务总览](docs/screenshots/01_业务总览.png)` 指向的文件真实存在（69KB 有效 PNG）；其余 4 张为注释占位，不破坏渲染。
- 命令一致性：README 中绝对路径与 `.venv\Scripts\python.exe` 用法均与当前目录结构一致；测试数（92）与覆盖率（88%）与实际一致。
- 真实 AI 说明：第 5 节给出 DeepSeek 配置与 `scripts/smoke_test_llm.py` 命令，明确「不打印 API Key」。
- 场景 B 实测结果、快速演示（3～5 分钟）小节均已补入。

---

## 八、预计提交文件清单（80 个）

> 79 个项目文件 + 本清单自身（`docs/github_release_checklist.md`）= 80 个未跟踪文件，首次提交全部入库。

### 根目录（7）
```
.env.example  .gitignore  README.md  app.py  pytest.ini  requirements.txt  run.bat
```

### demo_data/（21，七组虚构演示票据）
```
scenario_A/GRN_A_1.xlsx  scenario_A/Invoice_A_1.pdf  scenario_A/PO_A.pdf
scenario_B/GRN_B_1.png   scenario_B/Invoice_B_1.xlsx scenario_B/PO_B.pdf
scenario_C/GRN_C_1.pdf   scenario_C/Invoice_C_1.pdf  scenario_C/PO_C.pdf
scenario_D/GRN_D_1.xlsx  scenario_D/Invoice_D_1.pdf  scenario_D/Invoice_D_2.pdf  scenario_D/PO_D.xlsx
scenario_E/GRN_E_1.png   scenario_E/Invoice_E_1.pdf  scenario_E/PO_E.pdf
scenario_F/GRN_F_1.pdf   scenario_F/Invoice_F_1.xlsx scenario_F/PO_F.pdf
scenario_G/Invoice_G_1.pdf  scenario_G/PO_G.pdf
```

### docs/（12）
```
ai_extraction.md  architecture.md  demo_script.md  final_quality_audit.md
github_release_checklist.md  matching_rules.md  quality_audit_report.md
resume_description.md  user_guide.md  workflow.md
screenshots/README.md  screenshots/01_业务总览.png
```

### scripts/（2）
```
generate_demo_data.py  smoke_test_llm.py
```

### src/invoice_matching/（27）
```
__init__.py  anomalies.py  config.py  db.py  detection.py  document_import.py
logging_config.py  models.py  pipeline.py  report.py  review.py  schemas.py
ai/__init__.py  ai/extractor.py  ai/llm_provider.py  ai/offline_parser.py  ai/prompts.py
extraction/__init__.py  extraction/base.py  extraction/excel_extractor.py  extraction/ocr.py  extraction/pdf_extractor.py
processing/__init__.py  processing/aliases.py  processing/matching.py  processing/standardize.py  processing/validate.py
```

### tests/（11）
```
conftest.py  test_ai_extraction.py  test_app.py  test_detection.py  test_e2e.py
test_extraction.py  test_llm_provider.py  test_matching.py  test_report.py
test_review_db.py  test_standardize.py
```

**合计：80 个。**

---

## 九、仍需人工处理的项目（发布前/后由你完成）

1. **其余 4 张界面截图（02～05）未采集**：`docs/screenshots/` 目前只有 `01_业务总览.png`。其余页面截图请按 `docs/screenshots/README.md` 命名补入，并取消 `README.md` 中对应注释。（不影响发布，属增强项）
2. **发布动作本身**：GitHub 建仓、首次 `git add` / `commit` / `push`、在仓库 About 中填写简介与标签、选择 License——需你本人执行（本轮按要求未执行任何 git 写操作）。
3. **真实 LLM 密钥在本地 `.env`**：不会被提交。他人克隆后如需真实 AI 提取，需自行复制 `.env.example` 为 `.env` 并填写 DeepSeek 三项参数。
4. **可选 CI**：当前无 GitHub Actions 配置；如需，可加一条 `pip install -r requirements.txt && pytest` 的 workflow（注意 AppTest 全量约 3～4 分钟）。

---

## 十、GitHub 仓库简介与标签建议

### 简介（中文，用于 About description）

> AI 智能票据审核与采购对账系统：上传采购订单（PO）、供应商发票（Invoice）、收货记录（GRN），自动完成文本/OCR 提取、真实 LLM 结构化识别、三单匹配与异常检测、人工审核留痕，并导出 Excel 对账报告。个人独立开发的企业自动化原型。

### Description（英文）

> AI invoice processing & three-way matching system: extract PO/Invoice/GRN via text/OCR + LLM, run three-way matching & anomaly detection with human-in-the-loop review, and export Excel reconciliation reports.

### 建议标签（Topics）

```
python  streamlit  ocr  rapidocr  llm  deepseek  openai-compatible-api
pydantic  sqlite  three-way-matching  invoice-processing  procurement
finance-automation  human-in-the-loop  pytest
```

---

## 十一、如实声明（不夸大）

- 本项目为**个人独立开发的学习/求职原型**，未上线、无真实客户、无商业部署、无营收数据。
- 真实验收覆盖：一次真实 DeepSeek 冒烟测试（字段验证 7/7）+ 一组演示场景（场景 B）端到端实操 + 92 项 pytest 全通过 + 88% 行覆盖率（覆盖率沿用上一轮带 `--cov` 的实测，本轮复跑 `pytest` 确认 92 项通过）。
- **未声称所有生产环境功能已验证**：多用户并发、权限隔离、真实税务查验、ERP/付款对接均不在本项目范围。
