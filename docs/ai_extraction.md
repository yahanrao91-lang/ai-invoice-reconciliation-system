# AI 文档提取原理

## 1. 目标与边界

AI 模块的唯一职责是「把非结构化文本转成结构化 JSON」，不做金额计算、不做审核结论。

强制约束：

- 只依据给定文本提取，绝不编造金额/数量/税率。
- 缺失字段输出 `null` 并列入 `missing_fields`。
- 有歧义内容列入 `needs_review`。
- 每个重要字段在 `evidence` 中给出原始文本片段。
- 输出必须通过 Pydantic JSON Schema 校验，失败有限重试并记录原因。
- 真实调用必须由用户主动启用（`LLM_ENABLED=1`），否则进入离线模式。

## 2. LLM Provider 抽象

`ai/llm_provider.py` 定义协议，`OpenAiCompatibleProvider` 调用标准 `/chat/completions`：

```python
class LlmProvider(Protocol):
    def chat(self, messages: list[dict], temperature: float = 0.0) -> str: ...
```

配置项（环境变量 / `.env`）：

| 变量 | 说明 |
|------|------|
| `LLM_BASE_URL` | 兼容服务地址，如 `https://.../v1` |
| `LLM_API_KEY` | 密钥（仅本地 .env） |
| `LLM_MODEL` | 模型名称 |
| `LLM_ENABLED` | 是否启用真实调用（0/1） |
| `LLM_TIMEOUT` | 超时秒数 |
| `LLM_MAX_RETRIES` | 校验失败重试次数 |

不绑定单一厂商，支持国内可达的 OpenAI-Compatible 模型服务。

## 3. Prompt 设计

`ai/prompts.py` 的系统提示要点：

1. 角色设定：严谨的票据数据提取助手。
2. 硬规则：只依据文本、缺失置 null、歧义入 needs_review、数值不带千分位/货币符号、税率用小数、日期 YYYY-MM-DD、字段级 evidence、只输出 JSON。
3. 输出结构：与 `schemas.DocumentSchema` 对齐的 JSON 示例。

用户提示为：

```
请提取以下票据文本中的结构化信息：

<document_text>
{全文}
</document_text>
```

## 4. JSON Schema 校验与转换

- `schemas.py` 定义 `DocumentSchema`（Pydantic v2），字段全部可选、缺失即 `None`。
- `extractor.parse_json()` 健壮解析：剥离 Markdown 代码块、必要时截取首个 `{...}` 对象。
- `extractor.extract_with_llm_retry()` 在 `LlmError / ValidationError / ValueError` 时有限重试，全部失败抛出 `LlmError`（含失败原因）。
- `extractor.schema_to_result()` 将 Schema 转换为领域模型（`PurchaseOrder / Invoice / GoodsReceiptNote`），浮点值经 `Decimal(str(x))` + 量化，避免精度损失；`tax_rate` 统一为小数（13 → 0.13）。
- 可信度参考值 = `max(0.2, 1.0 - 0.1 × missing_fields 数量)`，仅作参考。

## 5. 离线演示模式

未配置 API Key 或 `LLM_ENABLED=0` 时，`ai/offline_parser.py` 提供确定性规则解析：

- 关键词识别文档类型（发票 → 收货 → 采购订单）。
- 正则/标签提取表头字段（`标签：值`）。
- 表格行解析：兼容 `|`、`/`、全角 `／` 分隔符（OCR 常把竖线识别为斜线）。
- 无法识别类型时返回人工录入提示，**绝不伪装成真实 LLM 调用**。

提取方式始终通过 `ExtractionResult.method` 与界面「提取方式」字段显式标识：`text / ocr / ai / offline / manual`。

## 6. 证据与追溯

`ExtractionResult` 携带：

- `evidence`：字段名 → 原始文本片段。
- `missing_fields` / `needs_review`：缺失与待确认清单。
- `raw_text`：完整提取文本。
- `confidence`：可信度参考值。

这些随提取结果一并持久化到 `extraction_results` 表，供界面展示与追溯。
