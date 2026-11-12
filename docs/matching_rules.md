# 三单匹配规则与容差

## 1. 原则

- 所有金额使用 `Decimal`，容差集中配置于 `config.BusinessRules`。
- 匹配依据必须显式记录（`item_no / name_spec / name_only / alias / none`）。
- 模糊匹配不视为 100% 确认，进入人工审核。
- 系统输出的是审核建议，不是付款授权。

## 2. 集中容差配置（config.py）

```python
@dataclass(frozen=True)
class BusinessRules:
    price_tolerance_rate: Decimal = Decimal("0.01")   # 单价相对容差 1%
    amount_tolerance: Decimal = Decimal("0.02")       # 金额相对容差 2%
    tax_rate_tolerance: Decimal = Decimal("0.0001")   # 税率容差
    allow_partial_delivery: bool = True               # 允许部分收货
    allow_partial_invoice: bool = True                # 允许分批开票
    allow_over_receipt: bool = False                  # 是否允许收货超订单
```

## 3. 核对规则明细

### 3.1 供应商信息核对

| 检查 | 异常码 |
|------|--------|
| PO 供应商名称 vs 发票销售方名称 | `SUPPLIER_NAME_MISMATCH` |
| PO 供应商税号 vs 发票销售方税号 | `SUPPLIER_TAX_MISMATCH` |
| PO 供应商 vs 收货记录供应商（名称/税号） | 同上 |

### 3.2 采购订单核对

| 检查 | 异常码 |
|------|--------|
| 发票/收货缺少关联订单号 | `PO_NUMBER_MISSING` |
| 关联订单号在任务中不存在 | `PO_NOT_FOUND` |

### 3.3 商品匹配（优先编号）

1. `item_no` 相等 → 依据 `item_no`（最可靠）。
2. 名称 + 规格相等 → 依据 `name_spec`。
3. 别名映射命中 → 依据 `alias`（候选匹配，需人工确认依据）。
4. 仅名称相等 → 依据 `name_only`（弱匹配）。
5. 全部不中 → `ITEM_NOT_IN_PO`，进入待人工确认。

### 3.4 数量核对

支持部分收货与分批开票：收货记录按商品聚合实收数量。

| 检查 | 异常码 | 严重度 |
|------|--------|--------|
| 发票数量 > 实收数量 | `QTY_OVER_RECEIPT` | HIGH |
| 实收数量 > 订单数量（且不允许超收） | `QTY_OVER_PO` | HIGH |
| 发票商品无对应收货记录 | `ITEM_NO_GRN` | HIGH |

### 3.5 单价核对

比较 PO 单价与发票单价，超出 `price_tolerance_rate`（默认 1%）→ `PRICE_DIFF`。

### 3.6 金额核对（Decimal）

| 检查 | 异常码 |
|------|--------|
| 行金额 ≠ 数量 × 单价 | `LINE_AMOUNT_MISMATCH` |
| 税额 ≠ 金额 × 税率 | `LINE_TAX_MISMATCH` |
| 价税合计 ≠ 金额 + 税额 | `LINE_TOTAL_MISMATCH` |
| PO 明细合计 ≠ PO 总金额 | `PO_TOTAL_MISMATCH` |
| 发票明细合计 ≠ 发票合计金额 | `INVOICE_TOTAL_MISMATCH` |
| PO 金额 ≠ 发票合计 | `PO_INVOICE_AMOUNT_DIFF` |

金额比较容差：`max(0.01, |基准| × amount_tolerance)`。

### 3.7 重复发票识别

| 键 | 说明 |
|----|------|
| 发票号码 | 任务内 + 历史（`_invoice_key`） |
| 文件 SHA-256 | 导入层去重 |

命中 → `DUPLICATE_INVOICE`（CRITICAL）。

### 3.8 缺失文件

文档提取失败/待录入 → `MISSING_DOCUMENT`（HIGH）。

## 4. 匹配结果状态

每行匹配结果归入以下状态之一：

| 状态 | 触发 |
|------|------|
| 匹配一致 | 无异常 |
| 存在数量差异 | `QTY_*` / `ITEM_NO_GRN` |
| 存在价格差异 | `PRICE_DIFF` |
| 供应商信息不一致 | 供应商异常 |
| 待人工确认 | `ITEM_NOT_IN_PO` / 匹配依据为 none |
| 重复发票 | `DUPLICATE_INVOICE` |

不同问题分别记录，不合并为一个模糊失败状态。

## 5. 异常严重程度

| 级别 | 含义 |
|------|------|
| CRITICAL | 重复发票等必须阻断的问题 |
| HIGH | 数量/价格/金额/供应商/缺失等实质差异 |
| MEDIUM | 订单号缺失、商品无法匹配等需人工确认项 |
| INFO | 提示性信息 |

**禁止未经审核自动确认存在重大异常（CRITICAL/HIGH）的发票。**
