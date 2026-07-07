import json
from pathlib import Path

import pytest

from paramsure.evidence_judge import judge_web_evidence
from paramsure.models import TenderRequirement, Verdict, VerificationConfig, VerificationDecision, VerificationNeed
from paramsure.web_runner import PlaybookWebRunner
from paramsure.web_models import VerificationIntent, WebEvidenceBundle
from paramsure.web_playbook import load_playbook


def _decision() -> VerificationDecision:
    requirement = TenderRequirement(
        requirement_id="REQ-1",
        title="",
        description="用户登录支持对接SSO，至少支持CAS、OIDC协议的一种",
    )
    return VerificationDecision(
        requirement=requirement,
        product="雷池- Web应用防火墙",
        initial_verdict=Verdict.UNKNOWN,
        confidence=0.0,
        needs_web_verification=True,
        verification_need=VerificationNeed.REQUIRED,
        reason="产品参数库未找到可支撑证据",
    )


def test_verification_intent_is_built_from_pending_decision() -> None:
    intent = VerificationIntent.from_decision(_decision(), readonly_blocklist=("保存", "删除"))

    assert intent.product == "雷池- Web应用防火墙"
    assert intent.requirement_id == "REQ-1"
    assert intent.requirement_text.startswith("用户登录支持对接SSO")
    assert {"sso", "cas", "oidc"} <= set(intent.keywords)
    assert "保存" in intent.readonly_blocklist


def test_playbook_loader_rejects_missing_evidence_rules(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps(
            {
                "product": "雷池- Web应用防火墙",
                "entry_actions": [{"type": "goto"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="evidence_rules"):
        load_playbook(path)


def test_playbook_readonly_guard_blocks_risky_clicks(tmp_path: Path) -> None:
    path = tmp_path / "leichi.json"
    path.write_text(
        json.dumps(
            {
                "product": "雷池- Web应用防火墙",
                "entry_actions": [{"type": "goto"}],
                "evidence_rules": {"min_dom_matches": 1},
                "readonly_blocklist": ["保存", "删除", "新增", "提交", "启用", "禁用"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    playbook = load_playbook(path)

    assert playbook.is_blocked_click("保存配置") is True
    assert playbook.is_blocked_click("查看日志") is False


def test_judge_does_not_confirm_keyword_only_evidence() -> None:
    intent = VerificationIntent.from_decision(_decision())
    bundle = WebEvidenceBundle(
        product=intent.product,
        requirement_id=intent.requirement_id,
        requirement_text=intent.requirement_text,
        final_url="http://example.test/",
        page_excerpt="SSO OIDC CAS",
        keyword_matches=("sso", "oidc"),
    )

    judgement = judge_web_evidence(intent, bundle)

    assert judgement.verdict == Verdict.UNKNOWN
    assert judgement.confidence == 0.0
    assert "页面上下文" in judgement.reason


def test_judge_confirms_structured_page_evidence() -> None:
    intent = VerificationIntent.from_decision(_decision())
    bundle = WebEvidenceBundle(
        product=intent.product,
        requirement_id=intent.requirement_id,
        requirement_text=intent.requirement_text,
        final_url="http://example.test/system/auth/sso",
        screenshot_path="/tmp/screenshot.png",
        page_excerpt="认证管理 单点登录 SSO OIDC 配置",
        keyword_matches=("sso", "oidc"),
        dom_matches=("认证管理 > 单点登录", "OIDC 配置"),
        steps=("goto http://example.test/", "open 认证管理 > 单点登录"),
    )

    judgement = judge_web_evidence(intent, bundle)

    assert judgement.verdict == Verdict.WEB_CONFIRMED
    assert judgement.confidence >= 0.72
    assert "认证管理 > 单点登录" in judgement.evidence_summary


def test_playbook_runner_writes_evidence_bundle(tmp_path: Path, monkeypatch) -> None:
    class FakeLocator:
        def __init__(self, text: str):
            self.text = text

        def inner_text(self, timeout: int = 0) -> str:
            return self.text

    class FakePage:
        url = "http://example.test/system/auth/sso"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            self.url = url.rstrip("/") + "/system/auth/sso"

        def locator(self, selector: str):
            assert selector == "body"
            return FakeLocator("认证管理\n单点登录\nSSO OIDC 配置\n只读查看")

        def screenshot(self, path: str, full_page: bool) -> None:
            Path(path).write_bytes(b"fake png")

    class FakeContext:
        def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            return None

    class FakeChromium:
        def connect_over_cdp(self, cdp_url: str):
            assert cdp_url == "http://127.0.0.1:9222"
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_module = type(
        "FakePlaywrightModule",
        (),
        {"sync_playwright": lambda: FakeManager(), "Error": Exception},
    )
    monkeypatch.setattr("paramsure.web_runner.import_module", lambda name: fake_module)

    playbook_path = tmp_path / "leichi.json"
    playbook_path.write_text(
        json.dumps(
            {
                "product": "雷池- Web应用防火墙",
                "entry_actions": [{"type": "goto"}],
                "evidence_rules": {"min_dom_matches": 1},
                "max_excerpt_chars": 80,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    playbook = load_playbook(playbook_path)
    intent = VerificationIntent.from_decision(_decision())

    bundle = PlaybookWebRunner(
        VerificationConfig(enabled=True, base_url="http://example.test", cdp_url="http://127.0.0.1:9222"),
        tmp_path / "artifacts",
    ).run(intent, playbook)

    assert bundle.failed_reason == ""
    assert bundle.final_url == "http://example.test/system/auth/sso"
    assert "SSO OIDC 配置" in bundle.page_excerpt
    assert {"sso", "oidc"} <= set(bundle.keyword_matches)
    assert bundle.dom_matches
    assert Path(bundle.screenshot_path).exists()
    evidence = json.loads(Path(bundle.evidence_path).read_text(encoding="utf-8"))
    assert evidence["requirement_id"] == "REQ-1"


def test_playbook_runner_uses_search_selectors_readonly(tmp_path: Path, monkeypatch) -> None:
    class FakeSearchLocator:
        def __init__(self, page):
            self.page = page

        def first(self):
            return self

        def fill(self, value: str) -> None:
            self.page.search_value = value

        def press(self, key: str) -> None:
            assert key == "Enter"
            self.page.url = "http://example.test/search?q=" + self.page.search_value

    class FakeBodyLocator:
        def __init__(self, page):
            self.page = page

        def inner_text(self, timeout: int = 0) -> str:
            if self.page.search_value:
                return "搜索结果\n认证管理\n单点登录\nSSO OIDC 配置"
            return "首页"

    class FakePage:
        url = "http://example.test/"

        def __init__(self):
            self.search_value = ""

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            self.url = url

        def locator(self, selector: str):
            if selector == "body":
                return FakeBodyLocator(self)
            if selector == "input[placeholder*='搜索']":
                return FakeSearchLocator(self)
            raise AssertionError(selector)

        def screenshot(self, path: str, full_page: bool) -> None:
            Path(path).write_bytes(b"fake png")

    class FakeContext:
        def new_page(self):
            return FakePage()

    class FakeBrowser:
        contexts = [FakeContext()]

        def close(self) -> None:
            return None

    class FakeChromium:
        def connect_over_cdp(self, cdp_url: str):
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_module = type(
        "FakePlaywrightModule",
        (),
        {"sync_playwright": lambda: FakeManager(), "Error": Exception},
    )
    monkeypatch.setattr("paramsure.web_runner.import_module", lambda name: fake_module)

    playbook_path = tmp_path / "leichi.json"
    playbook_path.write_text(
        json.dumps(
            {
                "product": "雷池- Web应用防火墙",
                "entry_actions": [{"type": "goto"}],
                "search_selectors": ["input[placeholder*='搜索']"],
                "evidence_rules": {"min_dom_matches": 1},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    bundle = PlaybookWebRunner(
        VerificationConfig(enabled=True, base_url="http://example.test", cdp_url="http://127.0.0.1:9222"),
        tmp_path / "artifacts",
    ).run(VerificationIntent.from_decision(_decision()), load_playbook(playbook_path))

    assert any(step.startswith("search input[placeholder*='搜索']") for step in bundle.steps)
    assert "搜索结果" in bundle.page_excerpt
    assert {"sso", "oidc"} <= set(bundle.keyword_matches)
