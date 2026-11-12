"""真实 LLM 冒烟测试脚本（独立于业务，可手动验收真实模型调用）。

设计约束：
- 使用项目现有 LLM Provider（build_provider / OpenAiCompatibleProvider）与数据提取模块
  （parse_json / schema_to_result / validate_document_schema / prompts）。
- 从现有 config 读取 API 参数，不在此处硬编码任何密钥。
- 仅当 LLM_ENABLED=1 且 LLM_BASE_URL/LLM_API_KEY/LLM_MODEL 齐备时才发起真实远程调用
  （与 pipeline 的启用条件一致，遵守“明确配置并启用后才允许真实请求”的安全要求）。
- 输入为完全虚构的供应商发票文本（含“模拟票据｜非真实业务凭证”标识），不含真实票据。
- 不调用离线解析器（不 import parse_offline），也不在失败时回退离线结果冒充真实调用。
- 不输出 API Key、Authorization 请求头或其他秘密；失败原因一律脱敏。
- 任何异常都返回失败退出码（1），只有全部校验通过才输出“成功”。

运行：.venv/Scripts/python.exe scripts/smoke_test_llm.py
"""
from __future__ import annotations

import re
import sys
from decimal import Decimal
from pathlib import Path

# 使脚本可从任意工作目录运行：把 src 加入 sys.path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pydantic import ValidationError  # noqa: E402

from invoice_matching.ai.extractor import parse_json, schema_to_result  # noqa: E402
from invoice_matching.ai.llm_provider import LlmError, build_provider  # noqa: E402
from invoice_matching.ai.prompts import SYSTEM_PROMPT, build_user_prompt  # noqa: E402
from invoice_matching.config import settings  # noqa: E402
from invoice_matching.models import DocumentType, ExtractionMethod, Invoice  # noqa: E402
from invoice_matching.schemas import validate_document_schema  # noqa: E402

# 完全虚构的发票文本（模拟票据｜非真实业务凭证），不含任何真实企业/个人信息
SAMPLE_TEXT = """模拟票据｜非真实业务凭证
文档类型：供应商发票（Invoice）
发票代码：3100999999
发票号码：DEMO-INV-20261109
开票日期：2026-11-09
销售方名称：测试科技有限公司
销售方税号：91310000FAKE0000A
购买方名称：示例采购有限公司
购买方税号：91310000BUYER000A
关联采购订单号：PO-DEMO-2026-001
商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：
ITEM-KB-001 | 机械键盘 | 87键 | 件 | 10 | 200.00 | 2000.00 | 13% | 260.00 | 2260.00
合计金额：2260.00"""


def _redact(text: str) -> str:
    """脱敏：移除真实密钥、Bearer 令牌、api_key=xxx 等敏感内容。"""
    t = str(text)
    key = settings.llm_api_key
    if key:
        t = t.replace(key, "***")
    t = re.sub(r"(Bearer\s+)\S+", r"\1***", t)
    t = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)\S+", r"\1***", t)
    return t


def _fail(msg: str) -> int:
    print(f"结果：失败 —— {msg}")
    return 1


def main() -> int:
    print("=" * 64)
    print("真实 LLM 冒烟测试")
    print("=" * 64)

    # 1. 配置就绪检查（不打印密钥）
    if not settings.llm_enabled:
        return _fail("LLM_ENABLED 未开启，按安全要求拒绝发起真实调用")
    if not settings.llm_configured:
        return _fail("LLM 未配置（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL 未就绪）")

    print(f"模型名称：{settings.llm_model}")
    print(f"服务地址：{_redact(settings.llm_base_url)}")
    print(f"超时：{settings.llm_timeout}s / 结构化重试：{settings.llm_max_retries} 次")

    provider = build_provider()
    if provider is None:
        return _fail("build_provider() 返回 None，无法发起真实调用")

    # 2. 使用现有 prompts 模块构造消息
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(SAMPLE_TEXT)},
    ]

    # 3. 真实远程调用（失败视为失败，绝不回退离线、绝不显示成功）
    try:
        raw = provider.chat(messages, temperature=0.0)
    except Exception as exc:  # noqa: BLE001 —— 这里只是统一脱敏，不改变失败结论
        return _fail(f"网络/服务调用失败：{_redact(str(exc))}")

    # 4. 解析 LLM 返回的 JSON
    try:
        obj = parse_json(raw)
    except LlmError as exc:
        return _fail(f"返回内容不是有效 JSON：{_redact(str(exc))}")

    # 5. Pydantic Schema 校验（现有 DocumentSchema）
    try:
        schema = validate_document_schema(obj)
    except ValidationError as exc:
        print("Schema 验证：未通过")
        return _fail(f"Schema 校验错误：{_redact(str(exc))[:600]}")
    print("Schema 验证：通过（Pydantic DocumentSchema）")

    # 6. 转统一数据模型（现有 extractor.schema_to_result）
    result = schema_to_result(schema, raw_text=SAMPLE_TEXT)
    if result.method != ExtractionMethod.AI:
        return _fail(f"提取方式不是 AI（实际={result.method.value}）")
    if result.document_type != DocumentType.INVOICE or not isinstance(result.data, Invoice):
        return _fail(f"文档类型不是发票（实际={result.document_type}）")

    # 7. 关键字段验证（虚构数据，逐项比对）
    data: Invoice = result.data
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, actual: object) -> None:
        checks.append((name, ok, f"实际={actual}"))

    check("发票号码", data.invoice_number == "DEMO-INV-20261109", data.invoice_number)
    check("供应商", data.seller_name == "测试科技有限公司", data.seller_name)
    if data.lines:
        ln = data.lines[0]
        check("商品名称", ln.name == "机械键盘", ln.name)
        check("数量", ln.quantity == Decimal("10"), ln.quantity)
        check("单价", ln.unit_price == Decimal("200"), ln.unit_price)
        check("金额", ln.amount == Decimal("2000"), ln.amount)
        check("税率", ln.tax_rate == Decimal("0.13"), ln.tax_rate)
    else:
        check("商品明细", False, "无商品行")

    print("-" * 64)
    passed = 0
    for name, ok, detail in checks:
        print(f"[{'通过' if ok else '未通过'}] {name}：{detail}")
        passed += int(ok)
    print("-" * 64)

    if passed != len(checks):
        return _fail(f"字段验证未全部通过（{passed}/{len(checks)}）")

    print(f"请求是否成功：成功")
    print(f"Schema 验证：通过")
    print(f"字段验证：{passed}/{len(checks)} 全部通过")
    print(f"提取方式：{result.method.value}")
    print("结果：通过 —— 真实 LLM 结构化提取可用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
