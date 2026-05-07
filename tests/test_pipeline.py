from pathlib import Path

from openpyxl import Workbook

from paramsure.excel_io import load_product_parameters
from paramsure.pipeline import ParaSurePipeline
from paramsure.store import ParameterStore


def _make_product_excel(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["模块", "功能项", "描述", "响应"])
    ws.append(["检测能力", "SQL注入检测", "支持检测SQL注入漏洞", ""])
    wb.save(path)


def _make_tender_excel(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(["序号", "指标项", "详细描述"])
    ws.append(["1", "SQL注入检测", "要求支持检测SQL注入漏洞"])
    wb.save(path)


def test_pipeline_generates_output(tmp_path: Path) -> None:
    product_excel = tmp_path / "慧鉴-智能源代码审计产品招标参数.xlsx"
    tender_excel = tmp_path / "客户参数.xlsx"
    output_excel = tmp_path / "result.xlsx"
    _make_product_excel(product_excel)
    _make_tender_excel(tender_excel)

    store = ParameterStore(tmp_path / "db.sqlite")
    store.add_parameters(load_product_parameters(product_excel))

    results = ParaSurePipeline(store, tmp_path / "artifacts").evaluate_excel(
        tender_file=tender_excel,
        product="慧鉴-智能源代码审计产品",
        output=output_excel,
    )
    assert results
    assert output_excel.exists()
