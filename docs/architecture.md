# 系统架构与模块职责

## 1. 总体架构

采用分层模块化架构，AI 模块与业务规则模块严格分离。大模型只负责「信息提取」，绝不参与金额计算或最终审核决定；所有匹配/计算/异常判定由确定性业务规则引擎完成。

```
┌─────────────────────────────────────────────────────────────┐
│                    Web 可视化层（Streamlit）                  │
│   首页总览 / 文档管理 / AI提取 / 三单匹配 / 人工审核 / 报告     │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────┐
│                     端到端编排层 pipeline.py                  │
│   导入 → 提取 → 标准化 → 验证 → 匹配 → 异常 → 持久化 → 报告    │
└──────────┬───────────────┬───────────────┬──────────────────┘
           │               │               │
┌──────────▼──────┐ ┌──────▼───────┐ ┌─────▼──────────────┐
│ 文档导入层       │ │ 文本提取/OCR │ │ 数据持久化层 SQLite   │
│ document_import │ │ extraction/  │ │ db.py               │
└─────────────────┘ └──────┬───────┘ └─────────────────────┘
                           │
                ┌──────────▼──────────┐
                │  AI 信息提取层 ai/   │
                │  LLM Provider +      │
                │  提取器 + 离线解析   │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ 数据标准化层         │
                │ processing/         │
                │ standardize/aliases │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ 业务数据验证层       │
                │ processing/validate │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ 三单匹配引擎         │
                │ processing/matching │
                │  + 异常检测 anomalies│
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │ 人工审核层 review    │
                │ 报告生成层 report    │
                └─────────────────────┘
```

## 2. 模块职责

| # | 模块 | 文件 | 职责 |
|---|------|------|------|
| 1 | 文档导入层 | `document_import.py` | 类型/大小校验、安全文件名、SHA-256、重复检测 |
| 2 | 文本提取与 OCR 层 | `extraction/` | PDF 文本/扫描件 OCR、图片 OCR、Excel 读取、OCR 抽象 |
| 3 | AI 信息提取层 | `ai/` | LLM Provider 接口、结构化提取、JSON Schema 校验、离线解析 |
| 4 | 数据标准化层 | `processing/standardize.py` | 标点/名称/单位/日期/税率统一、Decimal 金额 |
| 5 | 业务数据验证层 | `processing/validate.py` | 金额=数量×单价、税额、价税合计、总金额一致性 |
| 6 | 三单匹配引擎 | `processing/matching.py` | 供应商/订单/商品/数量/单价/金额核对、重复发票 |
| 7 | 异常检测层 | `anomalies.py` | 统一异常模型（code/severity/message/entity/evidence） |
| 8 | 人工审核层 | `review.py` | 修正（留痕）、确认/驳回、审计日志 |
| 9 | 数据持久化层 | `db.py` | SQLite 表结构、事务、索引、去重约束 |
| 10 | 报告生成层 | `report.py` | openpyxl 七张工作表、着色、筛选、冻结 |
| 11 | Web 可视化层 | `app.py` | Streamlit 全中文六页界面 |

## 3. 关键设计决策

### 3.1 AI 与业务规则分离

- `ai/extractor.py` 只负责把文本转成结构化 JSON（`schemas.py` 校验）。
- 所有金额计算、数量/单价比较、异常判定均在 `processing/` 下用 `Decimal` 完成。
- 大模型不计算金额、不做「通过/不通过」决定。

### 3.2 OCR 选型（记录）

- 需求优先评估 PaddleOCR。实测 `paddlepaddle` 在 Python 3.13 下 wheel 兼容性不稳定、体积大。
- 采用 **RapidOCR（rapidocr-onnxruntime）**：与 PaddleOCR 同源的 PP-OCR 中文模型（ONNX 格式），自包含、轻量、Python 3.13 兼容良好（本机初始化约 0.6s）。
- OCR 抽象为 `OcrEngine` 协议 + `OcrManager`，支持 `rapidocr` / `paddleocr` / `tesseract` 切换。
- **OCR 不可用时显式抛 `OcrUnavailableError` 或在提取结果中标记 `ocr_unavailable`，绝不静默跳过。**

### 3.3 LLM 多厂商解耦

- `ai/llm_provider.py` 定义 `LlmProvider` 协议，`OpenAiCompatibleProvider` 实现标准 `/chat/completions`。
- 配置 `LLM_BASE_URL / LLM_API_KEY / LLM_MODEL` 即可切换兼容服务，不绑定单一厂商。
- 真实调用需 `LLM_ENABLED=1`（用户主动启用）；未配置时进入**离线演示模式**（`ai/offline_parser.py`），并明确标识提取方式。

## 4. 数据模型与持久化

统一数据模型见 `models.py`：`PurchaseOrder`、`Invoice`、`GoodsReceiptNote`、`TradeLine`、`GrnLine`，缺失字段一律 `None`，金额字段 `Decimal`，每个实体支持 `to_dict/from_dict` 用于 JSON 持久化与追溯。

SQLite 表（`db.py`）：

| 表 | 说明 |
|----|------|
| `reconciliation_tasks` | 对账任务 |
| `documents` | 原始文档（含 SHA-256，`UNIQUE(file_hash, task_id)` 防重复） |
| `extraction_results` | 文档提取结果（方法/字段完整度参考值/结构化 JSON/证据/缺失字段） |
| `business_documents` | 结构化业务单据（PO/Invoice/GRN，标量列 + `data_json`） |
| `line_items` | 单据行明细（外键到 `business_documents`） |
| `line_matches` | 商品匹配结果 |
| `anomalies` | 异常记录（open/confirmed/rejected） |
| `review_records` | 人工审核记录（修改前后值/原因/时间/操作人） |
| `audit_logs` | 系统操作审计日志 |
| `aliases` | 商品别名映射（`UNIQUE(canonical, alias)`） |

所有关键表带外键与索引，重要写入使用事务。
