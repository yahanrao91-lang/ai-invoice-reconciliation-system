"""提取层共享数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..models import ExtractionMethod


@dataclass
class PageContent:
    """单页提取内容：保留页码、来源、提取方式、置信度参考值。"""

    page_no: int
    text: str
    method: ExtractionMethod
    confidence: float = 1.0
    source: str = ""
    warning: str = ""


@dataclass
class ExtractedText:
    """一份文档的提取结果。"""

    text: str
    pages: list[PageContent]
    method: ExtractionMethod
    confidence: float
    extra: dict = field(default_factory=dict)
