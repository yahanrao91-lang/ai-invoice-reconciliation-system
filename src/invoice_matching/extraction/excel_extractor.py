"""Excel 提取：使用 openpyxl 读取单元格数据。"""
from __future__ import annotations

from pathlib import Path

from ..logging_config import get_logger

log = get_logger(__name__)


def extract_excel(path: Path) -> tuple[str, dict[str, list[list[str]]]]:
    from openpyxl import load_workbook

    wb = load_workbook(str(path), data_only=True, read_only=True)
    sheets: dict[str, list[list[str]]] = {}
    text_parts: list[str] = []
    try:
        for ws in wb.worksheets:
            rows: list[list[str]] = []
            text_parts.append(f"【工作表：{ws.title}】")
            for row in ws.iter_rows(values_only=True):
                vals = ["" if v is None else str(v).strip() for v in row]
                if any(v for v in vals):
                    rows.append(vals)
                    text_parts.append(" | ".join(vals))
            sheets[ws.title] = rows
    finally:
        wb.close()
    return "\n".join(text_parts), sheets
