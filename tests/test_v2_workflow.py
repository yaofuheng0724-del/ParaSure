from pathlib import Path

from openpyxl import Workbook

from paramsure.bootstrap import auto_index_product_params
from paramsure.config import AgentConfig
from paramsure.context import build_product_context
from paramsure.nl_input import parse_natural_language_requirements
from paramsure.store import ParameterStore
from paramsure.workflow import V2Workflow


def _make_product_excel(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.append(["模块", "功能项", "描述"])
    ws.append(["认证管理", "SSO登录", "支持用户登录对接SSO，支持OIDC协议"])
    ws.append(["安全防护", "Web应用防护", "支持SQL注入、XSS等Web攻击防护"])
    wb.save(path)


def test_parse_natural_language_requirement_detects_product() -> None:
    parsed = parse_natural_language_requirements(
        "用户登录支持对接SSO、至少支持CAS、OIDC协议的一种，这条参数长亭的雷池web应用防火墙是否支持",
        ["雷池- Web应用防火墙"],
    )
    assert parsed.product == "雷池- Web应用防火墙"
    assert parsed.requirements
    assert "SSO" in parsed.requirements[0].text


def test_product_context_is_product_scoped(tmp_path: Path) -> None:
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    product_file = params_dir / "雷池- Web应用防火墙招标参数.xlsx"
    _make_product_excel(product_file)
    store = ParameterStore(tmp_path / "db.sqlite")
    auto_index_product_params(store, params_dir)
    context = build_product_context("雷池- Web应用防火墙", store.by_product("雷池- Web应用防火墙"))
    assert context.product == "雷池- Web应用防火墙"
    assert context.parameter_count == 2
    assert any("SSO" in feature for feature in context.sample_features)


def test_workflow_marks_weak_or_missing_items_for_verification(tmp_path: Path) -> None:
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    _make_product_excel(params_dir / "雷池- Web应用防火墙招标参数.xlsx")
    store = ParameterStore(tmp_path / "db.sqlite")
    config = AgentConfig(product_params_dir=str(params_dir))
    workflow = V2Workflow(store, config, tmp_path / "artifacts")

    report = workflow.assess_natural_language("是否支持硬件国密加密机对接，这条参数雷池是否支持")

    assert report.product == "雷池- Web应用防火墙"
    assert report.decisions
    assert report.pending_verifications
