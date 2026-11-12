"""pytest 共享 fixtures。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from invoice_matching.config import BusinessRules  # noqa: E402
from invoice_matching.db import Database  # noqa: E402


@pytest.fixture
def rules() -> BusinessRules:
    return BusinessRules()


@pytest.fixture
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def no_ocr(monkeypatch):
    """禁用 OCR 以加速测试（PDF 文本提取、Excel 等场景不需要 OCR）。"""
    monkeypatch.setattr("invoice_matching.config.settings.ocr_enabled", False)


@pytest.fixture
def po_text() -> str:
    return """模拟票据｜非真实业务凭证
文档类型：采购订单（PO）
采购订单编号：PO-TEST-001
订单日期：2026-01-05
供应商名称：华东精密制造有限公司
供应商税号：91310000FAKE000A
采购方名称：示例采购有限公司
采购方税号：91310000BUYER00A
商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：
ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | 200.00 | 20000.00 | 13% | 2600.00 | 22600.00
合计金额：22600.00"""


@pytest.fixture
def invoice_text() -> str:
    return """模拟票据｜非真实业务凭证
文档类型：供应商发票（Invoice）
发票代码：3100160000
发票号码：INV-TEST-001
开票日期：2026-01-10
销售方名称：华东精密制造有限公司
销售方税号：91310000FAKE000A
购买方名称：示例采购有限公司
购买方税号：91310000BUYER00A
关联采购订单号：PO-TEST-001
商品明细（商品编号 | 商品名称 | 规格 | 单位 | 数量 | 单价 | 金额 | 税率 | 税额 | 价税合计）：
ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | 200.00 | 20000.00 | 13% | 2600.00 | 22600.00
合计金额：22600.00"""


@pytest.fixture
def grn_text() -> str:
    return """模拟票据｜非真实业务凭证
文档类型：收货记录（GRN）
收货单编号：GRN-TEST-001
关联采购订单号：PO-TEST-001
收货日期：2026-01-20
供应商名称：华东精密制造有限公司
供应商税号：91310000FAKE000A
商品明细（商品编号 | 商品名称 | 规格 | 单位 | 计划收货数量 | 实际收货数量）：
ITEM-001 | 不锈钢轴承 | 6204 | 件 | 100 | 100"""
