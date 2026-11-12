"""数据标准化：中文标点、名称、单位、日期、金额（Decimal）、税率。"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CENTS = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def parse_decimal(value) -> Decimal | None:
    """解析金额/数量；支持千分位、货币符号、括号负数。无法解析返回 None。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    s = str(value).strip()
    s = s.replace(",", "").replace("，", "").replace("¥", "").replace("￥", "").replace("元", "")
    s = s.strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s in {"", "-", "None", "null", "无", "/"}:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    return -d if neg else d


def parse_tax_rate(value) -> Decimal | None:
    """解析税率；13 或 13% 归一为 0.13。"""
    if value is None:
        return None
    s = str(value).strip().replace("%", "").strip()
    if s in {"", "无", "None", "null"}:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None
    if abs(d) > 1:
        d = d / Decimal("100")
    return d


def quantize_money(d: Decimal | None, places: int = 2) -> Decimal | None:
    if d is None:
        return None
    q = Decimal(1).scaleb(-places)
    return d.quantize(q, rounding=ROUND_HALF_UP)


def quantize_qty(d: Decimal | None, places: int = 4) -> Decimal | None:
    return quantize_money(d, places)


def normalize_text(s) -> str:
    if s is None:
        return ""
    t = str(s)
    # 全角空格与空白统一
    t = re.sub(r"\s+", " ", t).replace("　", " ").strip()
    # 中文常见全角括号/冒号/逗号转半角，便于一致比较
    t = (
        t.replace("（", "(")
        .replace("）", ")")
        .replace("：", ":")
        .replace("，", ",")
        .replace("；", ";")
        .replace("“", '"')
        .replace("”", '"')
        .replace("－", "-")
        .replace("—", "-")
    )
    return t.strip()


def normalize_name(s) -> str | None:
    t = normalize_text(s)
    return t if t else None


def normalize_item_no(s) -> str | None:
    t = normalize_text(s).upper()
    return t if t else None


_UNIT_MAP = {
    "件": "件", "个": "件", "只": "件", "支": "件", "pcs": "件", "pc": "件",
    "台": "台", "套": "套", "组": "套",
    "米": "米", "m": "米",
    "千克": "千克", "公斤": "千克", "kg": "千克",
    "克": "克", "g": "克",
    "吨": "吨", "t": "吨",
    "箱": "箱", "盒": "盒", "瓶": "瓶",
    "张": "张", "本": "本", "卷": "卷", "袋": "袋",
}


def normalize_unit(s) -> str | None:
    if s is None:
        return None
    t = normalize_text(s).lower()
    return _UNIT_MAP.get(t, t if t else None)


def normalize_date(s) -> str | None:
    """统一日期为 YYYY-MM-DD。"""
    if s is None:
        return None
    t = str(s).strip()
    t = t.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-").replace(".", "-")
    m = re.search(r"(\d{4})\s*-\s*(\d{1,2})\s*-\s*(\d{1,2})", t)
    if m:
        y, mo, d = m.groups()
        return f"{int(y):04d}-{int(mo):02d}-{int(d):02d}"
    return t or None


def normalize_supplier(s) -> str | None:
    return normalize_name(s)


def normalize_tax_no(s) -> str | None:
    if s is None:
        return None
    t = re.sub(r"\s+", "", str(s)).upper()
    return t if t else None
