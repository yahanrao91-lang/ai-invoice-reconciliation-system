"""标准化与数值解析测试。"""
from decimal import Decimal

from invoice_matching.processing.aliases import AliasRegistry
from invoice_matching.processing.standardize import (
    normalize_date,
    normalize_tax_no,
    normalize_text,
    normalize_unit,
    parse_decimal,
    parse_tax_rate,
    quantize_money,
)


def test_parse_decimal_currency_and_commas():
    assert parse_decimal("¥1,234.56") == Decimal("1234.56")
    assert parse_decimal("22600.00") == Decimal("22600.00")
    assert parse_decimal("(100.00)") == Decimal("-100.00")
    assert parse_decimal(None) is None
    assert parse_decimal("无") is None


def test_parse_tax_rate_percentage_and_fraction():
    assert parse_tax_rate("13%") == Decimal("0.13")
    assert parse_tax_rate("0.13") == Decimal("0.13")
    assert parse_tax_rate(13) == Decimal("0.13")
    assert parse_tax_rate(None) is None


def test_normalize_unit():
    assert normalize_unit("个") == "件"
    assert normalize_unit("kg") == "千克"
    assert normalize_unit("件") == "件"


def test_normalize_date():
    assert normalize_date("2026年1月5日") == "2026-01-05"
    assert normalize_date("2026/01/05") == "2026-01-05"


def test_normalize_text_fullwidth():
    assert normalize_text("　全角：逗号，括号（） ") == "全角:逗号,括号()"


def test_normalize_tax_no():
    assert normalize_tax_no(" 91310000 fake 000A ") == "91310000FAKE000A"


def test_quantize_money_rounding():
    assert quantize_money(Decimal("22600.004")) == Decimal("22600.00")
    assert quantize_money(Decimal("22600.006")) == Decimal("22600.01")


def test_alias_registry_resolve_and_keys():
    reg = AliasRegistry()
    reg.add_alias("ITEM-001", "轴承")
    assert reg.resolve("轴承") == "ITEM-001"
    assert "轴承" in reg.keys_for("ITEM-001")
    assert reg.resolve("不存在") == "不存在"
