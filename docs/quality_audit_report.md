# 质量审计报告

> 本报告基于实际执行的测试与验证结果，不使用删除测试等手段伪造通过。

## 1. 执行环境

- 操作系统：Windows 11 Home（10.0.26200）
- Python：3.13.13
- 测试框架：pytest 8 + pytest-cov
- 执行日期：2026-11-09

## 2. 测试结果总览

```
45 passed, 2 warnings in ~5s
TOTAL 行覆盖率：85%
```

**结论：45 项测试全部通过，行覆盖率 85%（≥80% 达标）。**

## 3. 分模块覆盖率

| 模块 | 行覆盖率 | 说明 |
|------|---------|------|
| models.py | 96% | 数据模型 |
| config.py | 98% | 配置 |
| processing/matching.py | 92% | 三单匹配引擎 |
| processing/standardize.py | 91% | 标准化 |
| db.py | 90% | SQLite 持久化 |
| document_import.py | 91% | 导入 |
| review.py | 89% | 人工审核 |
| processing/validate.py | 84% | 金额验证 |
| report.py | 78% | 报告（着色分支未全测） |
| extraction/ocr.py | 55% | PaddleOCR/Tesseract 可选分支未测 |
| ai/llm_provider.py | 54% | 真实 HTTP 调用用 mock，网络分支未测 |

低覆盖区域均为**可选引擎/真实网络调用分支**，核心业务逻辑覆盖充分。

## 4. 需求测试点覆盖对照

| # | 需求测试点 | 状态 |
|---|-----------|------|
| 1 | PDF 文本提取 | ✅ `test_pdf_text_extraction` |
| 2 | Excel 数据读取 | ✅ `test_excel_reading` |
| 3 | 图片格式检查 | ✅ `test_image_format_check` / `test_file_size_limit` |
| 4 | OCR 接口调用及异常处理 | ✅ `test_ocr_unavailable_raises` / `test_ocr_engine_recognizes_image`（真实识别） |
| 5 | AI JSON 输出结构校验 | ✅ `test_validate_document_schema_*` |
| 6 | AI 字段缺失处理 | ✅ `test_validate_document_schema_missing_fields_default_null` / `test_offline_parser_missing_field_nulls` |
| 7 | 金额 Decimal 计算 | ✅ `test_quantize_money_rounding` / `test_parse_decimal_*` |
| 8 | 商品别名匹配 | ✅ `test_alias_registry_*` / `test_alias_matching` |
| 9 | 供应商信息差异 | ✅ `test_supplier_name_and_tax_mismatch` |
| 10 | 数量超出实际收货量 | ✅ `test_invoice_qty_over_receipt` |
| 11 | 超出采购订单数量 | ✅ `test_receipt_over_po_qty` |
| 12 | 单价不一致 | ✅ `test_price_diff` |
| 13 | 税额计算差异 | ✅ 验证层 `LINE_TAX_MISMATCH`（端到端场景 F） |
| 14 | 发票金额计算差异 | ✅ `test_e2e_qty_anomaly` / 场景 F |
| 15 | 重复发票检查 | ✅ `test_duplicate_invoice` |
| 16 | 缺失文件处理 | ✅ `MISSING_DOCUMENT`（pipeline）+ `test_po_not_found_and_missing_number` |
| 17 | 部分收货 | ✅ `test_partial_receipt_no_anomaly` |
| 18 | 人工修正记录 | ✅ `test_apply_correction_*` / `test_record_correction_manual` |
| 19 | SQLite 持久化 | ✅ `test_save_and_load_business_document` / `test_duplicate_hash_rejected` |
| 20 | Excel 对账报告实际内容 | ✅ `test_report_sheets_and_anomaly_content` |
| 21 | 完整三单对账端到端流程 | ✅ `test_e2e_full_match` / `test_e2e_qty_anomaly` |
| — | Streamlit 界面测试 | ✅ `test_app_runs_without_exception`（AppTest） |

## 5. 端到端场景验证（真实文件）

使用 `scripts/generate_demo_data.py` 生成的真实 PDF/PNG/XLSX 文件，对 7 组场景跑通完整流水线，异常结果符合预期：

| 场景 | 预期异常 | 实际 |
|------|----------|------|
| A 三单一致 | 无 | ✅ 无异常，1 行匹配一致 |
| B 数量异常 | QTY_OVER_RECEIPT | ✅ |
| C 价格异常 | PRICE_DIFF | ✅ |
| D 重复发票 | DUPLICATE_INVOICE | ✅ |
| E 税号不一致 | SUPPLIER_TAX_MISMATCH | ✅ |
| F 金额计算错误 | LINE_AMOUNT/TAX/TOTAL_MISMATCH | ✅ |
| G 缺失收货 | ITEM_NO_GRN | ✅ |

## 6. 附加验证

- ✅ 所有模块可正常导入（无导入错误）。
- ✅ Streamlit 应用 headless 启动返回 HTTP 200。
- ✅ RapidOCR 本地初始化约 0.6s，真实识别中文图片成功。
- ✅ Excel 报告可被 openpyxl 重新打开，包含实际异常代码。

## 7. 遗留风险与局限

1. `ai/llm_provider.py` 的真实网络调用未在测试中直连真实服务（按要求使用 mock）；已通过 Provider 抽象与单元测试覆盖解析/重试逻辑。
2. OCR 对竖线分隔符存在误识别（`|`→`/`），已做分隔符容错，极端模糊票据仍需人工复核。
3. PaddleOCR / Tesseract 引擎分支未做真实集成测试（本机未安装对应依赖），默认 RapidOCR 已实测可用。
4. Streamlit 界面仅做「无异常运行」冒烟测试，交互式点击路径未自动化到每个表单。

## 8. 结论

系统核心业务逻辑（导入、提取、标准化、验证、三单匹配、异常检测、持久化、人工审核、报告）均有自动化测试覆盖且全部通过；真实文件端到端验证符合预期；达到交付标准。未完成或受限部分已在上述局限中如实说明。
