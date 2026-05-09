import types

from paramsure.models import TenderRequirement, VerificationConfig
from paramsure.verifier import WebVerifier


def _requirement() -> TenderRequirement:
    return TenderRequirement(requirement_id="1", title="", description="支持SSO登录")


def test_web_verifier_reports_missing_playwright_package(tmp_path, monkeypatch) -> None:
    def fake_import_module(name):
        if name == "playwright.sync_api":
            raise ImportError("missing")
        raise AssertionError(name)

    monkeypatch.setattr("paramsure.verifier.import_module", fake_import_module)

    outcome = WebVerifier(VerificationConfig(enabled=True, base_url="https://example.com"), tmp_path).verify(
        _requirement()
    )

    assert outcome.confirmed is False
    assert ".venv 未安装 playwright" in outcome.summary


def test_web_verifier_reports_missing_browser_executable(tmp_path, monkeypatch) -> None:
    class FakePlaywrightError(Exception):
        pass

    class FakeChromium:
        def launch(self, headless=False):
            raise FakePlaywrightError("Executable doesn't exist. Please run: playwright install")

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_module = types.SimpleNamespace(sync_playwright=lambda: FakeManager(), Error=FakePlaywrightError)
    monkeypatch.setattr("paramsure.verifier.import_module", lambda name: fake_module)

    outcome = WebVerifier(VerificationConfig(enabled=True, base_url="https://example.com"), tmp_path).verify(
        _requirement()
    )

    assert outcome.confirmed is False
    assert ".venv/bin/python -m playwright install chromium" in outcome.summary
