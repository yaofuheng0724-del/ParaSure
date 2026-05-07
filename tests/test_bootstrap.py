from pathlib import Path

from openpyxl import Workbook

from paramsure.bootstrap import auto_index_product_params
from paramsure.store import ParameterStore


def _make_product_excel(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["模块", "功能项", "描述"])
    ws.append(["检测能力", "XSS检测", "支持跨站脚本XSS检测"])
    wb.save(path)


def test_auto_index_skips_unchanged_files(tmp_path: Path) -> None:
    params_dir = tmp_path / "data"
    params_dir.mkdir()
    _make_product_excel(params_dir / "雷池- Web应用防火墙招标参数.xlsx")
    store = ParameterStore(tmp_path / "db.sqlite")

    first = auto_index_product_params(store, params_dir)
    second = auto_index_product_params(store, params_dir)

    assert first["indexed"] == 1
    assert second["indexed"] == 0
    assert second["skipped"] == 1
    assert store.products()
