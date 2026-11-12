"""异常检测结果模型。"""
from __future__ import annotations

from dataclasses import asdict, dataclass


class Severity:
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    INFO = "INFO"


@dataclass
class Anomaly:
    code: str
    severity: str
    message: str
    entity_type: str = ""   # po / invoice / grn / line
    entity_ref: str = ""    # 单据编号
    field: str = ""
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
