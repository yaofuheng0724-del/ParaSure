import json
import importlib.util
from pathlib import Path

from paramsure import cli
from paramsure.models import TenderRequirement, VerificationConfig
from paramsure.verifier import WebVerifier
from paramsure.web_models import VerificationIntent
from paramsure.web_scripts import WebTestScriptRunner, find_product_web_tests, load_web_test_manifest


def _write_manifest(root: Path) -> Path:
    product_dir = root / "leichi"
    product_dir.mkdir(parents=True)
    manifest = {
        "product": "雷池- Web应用防火墙",
        "slug": "leichi",
        "aliases": ["雷池", "WAF"],
        "readonly_blocklist": ["保存", "删除", "新增", "提交", "启用", "禁用"],
        "scripts": [
            {
                "name": "discover",
                "type": "discover",
                "path": "discover.py",
                "capabilities": ["discovery"],
            },
            {
                "name": "verify_sso",
                "type": "verify",
                "path": "verify_sso.py",
                "capabilities": ["sso", "oidc", "cas", "单点登录"],
            },
        ],
    }
    (product_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (product_dir / "discover.py").write_text("print('discover')\n", encoding="utf-8")
    (product_dir / "verify_sso.py").write_text(_script_source(), encoding="utf-8")
    return product_dir / "manifest.json"


def _script_source() -> str:
    return """
import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--base-url", required=True)
parser.add_argument("--cdp-url", default="")
parser.add_argument("--requirement-id", required=True)
parser.add_argument("--requirement-text", required=True)
parser.add_argument("--out-dir", required=True)
args = parser.parse_args()

out_dir = Path(args.out_dir)
out_dir.mkdir(parents=True, exist_ok=True)
(out_dir / "screenshot.png").write_bytes(b"fake png")
(out_dir / "page_excerpt.txt").write_text("认证管理 单点登录 SSO OIDC 配置", encoding="utf-8")
(out_dir / "evidence.json").write_text(json.dumps({
    "product": "雷池- Web应用防火墙",
    "requirement_id": args.requirement_id,
    "requirement_text": args.requirement_text,
    "final_url": args.base_url.rstrip("/") + "/system/auth/sso",
    "screenshot_path": str(out_dir / "screenshot.png"),
    "evidence_path": str(out_dir / "evidence.json"),
    "page_excerpt": "认证管理 单点登录 SSO OIDC 配置",
    "keyword_matches": ["sso", "oidc"],
    "dom_matches": ["认证管理 > 单点登录", "OIDC 配置"],
    "steps": ["script verify_sso"],
}, ensure_ascii=False), encoding="utf-8")
"""


def test_web_test_manifest_selects_verify_script_for_requirement(tmp_path: Path) -> None:
    manifest = load_web_test_manifest(_write_manifest(tmp_path))
    intent = VerificationIntent(
        product="雷池- Web应用防火墙",
        requirement_id="REQ-1",
        requirement_text="要求支持SSO/OIDC登录",
        keywords=("sso", "oidc"),
    )

    script = manifest.select_script(intent)

    assert script is not None
    assert script.name == "verify_sso"
    assert script.path.name == "verify_sso.py"


def test_find_product_web_tests_matches_product_alias(tmp_path: Path) -> None:
    _write_manifest(tmp_path)

    manifest = find_product_web_tests("WAF", tmp_path)

    assert manifest is not None
    assert manifest.product == "雷池- Web应用防火墙"


def test_web_test_script_runner_invokes_contract_and_reads_evidence(tmp_path: Path) -> None:
    manifest = load_web_test_manifest(_write_manifest(tmp_path / "web_tests"))
    intent = VerificationIntent(
        product=manifest.product,
        requirement_id="REQ-1",
        requirement_text="要求支持SSO/OIDC登录",
        keywords=("sso", "oidc"),
    )

    bundle = WebTestScriptRunner(
        VerificationConfig(enabled=True, base_url="http://example.test", cdp_url="http://127.0.0.1:9222"),
        tmp_path / "artifacts",
    ).run(intent, manifest)

    assert bundle.failed_reason == ""
    assert bundle.final_url == "http://example.test/system/auth/sso"
    assert bundle.screenshot_path.endswith("screenshot.png")
    assert "认证管理" in bundle.page_excerpt
    assert "verify_sso" in " ".join(bundle.steps)


def test_web_test_script_runner_resolves_relative_evidence_dir_from_caller_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    manifest = load_web_test_manifest(_write_manifest(Path("web_tests")))
    intent = VerificationIntent(
        product=manifest.product,
        requirement_id="REQ-1",
        requirement_text="要求支持SSO/OIDC登录",
        keywords=("sso", "oidc"),
    )

    bundle = WebTestScriptRunner(
        VerificationConfig(enabled=True, base_url="http://example.test", evidence_dir="artifacts"),
        Path("fallback-artifacts"),
    ).run(intent, manifest)

    assert bundle.failed_reason == ""
    assert (tmp_path / "artifacts" / "REQ-1" / "evidence.json").exists()
    assert not (manifest.root / "artifacts").exists()


def test_cli_web_test_command_runs_product_script(tmp_path: Path, capsys) -> None:
    _write_manifest(tmp_path / "web_tests")
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "web_tests_dir": str(tmp_path / "web_tests"),
                "chrome": {"cdp_url": "http://127.0.0.1:9222"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    args = cli.build_parser().parse_args(
        [
            "--config",
            str(config_path),
            "web-test",
            "雷池- Web应用防火墙",
            "--requirement",
            "要求支持SSO/OIDC登录",
            "--web-url",
            "http://example.test",
            "--out-dir",
            str(tmp_path / "artifacts"),
        ]
    )

    assert cli.dispatch(args) == 0
    output = capsys.readouterr().out
    assert "Web已确认" in output
    assert (tmp_path / "artifacts" / "manual" / "evidence.json").exists()


def test_web_verifier_prefers_product_script_before_generic_playwright(tmp_path: Path, monkeypatch) -> None:
    _write_manifest(tmp_path / "web_tests")
    monkeypatch.setattr("paramsure.verifier.import_module", lambda name: (_ for _ in ()).throw(ImportError("missing")))

    outcome = WebVerifier(
        VerificationConfig(
            enabled=True,
            base_url="http://example.test",
            cdp_url="http://127.0.0.1:9222",
            web_tests_dir=str(tmp_path / "web_tests"),
        ),
        tmp_path / "artifacts",
        product="雷池- Web应用防火墙",
    ).verify(TenderRequirement(requirement_id="REQ-1", title="", description="要求支持SSO/OIDC登录"))

    assert outcome.confirmed is True
    assert outcome.evidence_path.endswith("evidence.json")


def test_builtin_leichi_web_test_manifest_is_valid() -> None:
    manifest = find_product_web_tests("雷池- Web应用防火墙", Path("web_tests"))

    assert manifest is not None
    assert manifest.slug == "leichi"
    assert {script.name for script in manifest.scripts} >= {"discover", "verify_sso"}


def test_builtin_leichi_manifest_resolves_script_paths_from_project_root() -> None:
    manifest = find_product_web_tests("雷池- Web应用防火墙", Path("web_tests"))
    assert manifest is not None
    script = manifest.select_script(
        VerificationIntent(
            product=manifest.product,
            requirement_id="REQ-1",
            requirement_text="要求支持LDAP认证登录",
            keywords=("ldap",),
        )
    )

    assert script is not None
    assert script.path.is_absolute()
    assert script.path.exists()
    assert script.path.parent.name == "leichi"


def test_builtin_leichi_scripts_ignore_internal_https_certificates() -> None:
    discover = Path("web_tests/leichi/discover.py").read_text(encoding="utf-8")
    verify_sso = Path("web_tests/leichi/verify_sso.py").read_text(encoding="utf-8")

    assert "ignore_https_errors=True" in discover
    assert "ignore_https_errors=True" in verify_sso


def test_builtin_leichi_verify_script_detects_login_page() -> None:
    verify_sso = Path("web_tests/leichi/verify_sso.py").read_text(encoding="utf-8")

    assert "def _login_failure_reason" in verify_sso
    assert "You are not logged on" in verify_sso
    assert "failed_reason" in verify_sso


def test_builtin_leichi_verify_script_captures_network_responses() -> None:
    verify_sso = Path("web_tests/leichi/verify_sso.py").read_text(encoding="utf-8")

    assert "network_events" in verify_sso
    assert "network.log" in verify_sso
    assert "page.on(\"response\"" in verify_sso


def test_builtin_leichi_verify_script_reloads_after_login() -> None:
    verify_sso = Path("web_tests/leichi/verify_sso.py").read_text(encoding="utf-8")

    assert "reload after login" in verify_sso
    assert "def _post_login_url" in verify_sso
    assert "/statistic/overview" in verify_sso


def test_builtin_leichi_verify_script_falls_back_when_cdp_unavailable() -> None:
    verify_sso = Path("web_tests/leichi/verify_sso.py").read_text(encoding="utf-8")

    assert "connect_over_cdp failed" in verify_sso
    assert "launch headless chromium" in verify_sso


def test_builtin_leichi_verify_script_keeps_oidc_unconfirmed_without_specific_evidence() -> None:
    module = _load_leichi_verify_module()
    page_text = "\n".join(
        [
            "前端资源证据: LDAP 认证",
            "前端资源证据: RADIUS 认证",
            "前端资源证据: 认证方式列表",
            "认证方式是一个列表，从列表第一项开始查找，若认证失败则尝试下一项。",
        ]
    )

    keyword_matches, dom_matches, failed_reason = module._judge_capability_evidence("要求支持SSO/OIDC登录", page_text)

    assert keyword_matches == ()
    assert dom_matches == ()
    assert "未发现 OIDC/CAS/SAML/SSO" in failed_reason


def test_builtin_leichi_verify_script_confirms_ldap_with_contextual_evidence() -> None:
    module = _load_leichi_verify_module()
    page_text = "\n".join(
        [
            "前端资源证据: LDAP 认证",
            "前端资源证据: 第三方接入",
            "系统设置 用户管理 用户安全 认证方式 LDAP 认证 RADIUS 认证",
        ]
    )

    keyword_matches, dom_matches, failed_reason = module._judge_capability_evidence("要求支持LDAP认证登录", page_text)

    assert failed_reason == ""
    assert "LDAP" in keyword_matches
    assert any("LDAP 认证" in item for item in dom_matches)


def test_builtin_leichi_static_evidence_scans_beyond_first_js_chunk() -> None:
    module = _load_leichi_verify_module()

    class FakeResponse:
        ok = True

        def __init__(self, body: str) -> None:
            self.body = body

        def text(self) -> str:
            return self.body

    class FakeRequest:
        def get(self, url: str, timeout: int) -> FakeResponse:
            if url.endswith("vendor.js"):
                return FakeResponse("loginWithPassword loginWithCert")
            return FakeResponse("getLdapConfig /api/RADIUSConfigV2API systemUsersThirdParty")

    class FakeLocator:
        def evaluate_all(self, script: str) -> list[str]:
            return [
                "https://example.test/static/js/vendor.js",
                "https://example.test/static/js/app.js",
            ]

    class FakePage:
        request = FakeRequest()

        def locator(self, selector: str) -> FakeLocator:
            return FakeLocator()

    evidence = module._collect_static_auth_evidence(FakePage(), [])

    assert "前端资源证据: 密码认证" in evidence
    assert "前端资源证据: LDAP 认证" in evidence
    assert "前端资源证据: RADIUS 认证" in evidence


def test_builtin_leichi_verify_script_uses_actual_auth_routes() -> None:
    verify_sso = Path("web_tests/leichi/verify_sso.py").read_text(encoding="utf-8")

    assert "/system/users/config" in verify_sso
    assert "/system/users/third-party" in verify_sso
    assert "STATIC_EVIDENCE_MARKERS" in verify_sso


def test_builtin_leichi_verify_script_reads_password_from_runtime_only(monkeypatch) -> None:
    module = _load_leichi_verify_module()
    monkeypatch.setenv("PARAMSURE_WEB_USERNAME", "admin")
    monkeypatch.setenv("PARAMSURE_WEB_PASSWORD", "secret-from-env")
    args = type("Args", (), {"username": "", "password_stdin": False})()

    assert module._credentials(args) == ("admin", "secret-from-env")
    assert "secret-from-env" not in Path("web_tests/leichi/verify_sso.py").read_text(encoding="utf-8")


def test_builtin_leichi_verify_script_supports_password_stdin(monkeypatch) -> None:
    module = _load_leichi_verify_module()
    monkeypatch.delenv("PARAMSURE_WEB_USERNAME", raising=False)
    monkeypatch.delenv("PARAMSURE_WEB_PASSWORD", raising=False)
    monkeypatch.setattr("sys.stdin", type("FakeStdin", (), {"readline": lambda self: "secret-from-stdin\n"})())
    args = type("Args", (), {"username": "admin", "password_stdin": True})()

    assert module._credentials(args) == ("admin", "secret-from-stdin")


def _load_leichi_verify_module():
    path = Path("web_tests/leichi/verify_sso.py")
    spec = importlib.util.spec_from_file_location("leichi_verify_sso_for_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module
