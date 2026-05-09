from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from urllib import request

from .models import TenderRequirement, VerificationConfig
from .text import top_terms


@dataclass
class VerificationOutcome:
    confirmed: bool
    confidence: float
    summary: str = ""
    artifact: str = ""


class ApiVerifier:
    def __init__(self, config: VerificationConfig):
        self.config = config

    def verify(self, requirement: TenderRequirement) -> VerificationOutcome:
        if not self.config.api_base_url or not self.config.api_token:
            return VerificationOutcome(False, 0.0, "未配置API Token或API地址")
        # Prototype-level read-only health check. Product-specific endpoint
        # mappings should be registered later under this boundary.
        url = self.config.api_base_url.rstrip("/")
        req = request.Request(url, headers={"Authorization": f"Bearer {self.config.api_token}"}, method="GET")
        try:
            with request.urlopen(req, timeout=8) as resp:
                status = getattr(resp, "status", 0)
                body = resp.read(512).decode("utf-8", errors="ignore")
            confirmed = 200 <= status < 300
            return VerificationOutcome(confirmed, 0.45 if confirmed else 0.0, f"GET {url} -> HTTP {status}; {body[:160]}")
        except Exception as exc:  # noqa: BLE001 - verification failures must be captured as evidence.
            return VerificationOutcome(False, 0.0, f"API验证失败: {exc}")


class WebVerifier:
    def __init__(self, config: VerificationConfig, artifact_dir: Path):
        self.config = config
        self.artifact_dir = artifact_dir

    def verify(self, requirement: TenderRequirement) -> VerificationOutcome:
        if not self.config.enabled:
            return VerificationOutcome(False, 0.0, "未启用Web验证")
        try:
            playwright = import_module("playwright.sync_api")
        except Exception:
            return VerificationOutcome(
                False,
                0.0,
                "ParaSure 的 .venv 未安装 playwright。请运行 ./paramsure 让依赖自动安装，或执行 .venv/bin/python -m pip install -e .",
            )
        sync_playwright = playwright.sync_playwright
        playwright_error = getattr(playwright, "Error", Exception)

        if not self.config.base_url:
            return VerificationOutcome(False, 0.0, "未配置产品Web地址")

        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        screenshot = self.artifact_dir / f"web-check-{requirement.requirement_id}.png"
        keywords = top_terms(requirement.text, 6)
        try:
            with sync_playwright() as p:
                if self.config.cdp_url:
                    browser = p.chromium.connect_over_cdp(self.config.cdp_url)
                    context = browser.contexts[0] if browser.contexts else browser.new_context()
                else:
                    browser = p.chromium.launch(headless=False)
                    context_args = {}
                    if self.config.browser_state:
                        context_args["storage_state"] = str(self.config.browser_state)
                    context = browser.new_context(**context_args)
                page = context.new_page()
                page.goto(self.config.base_url, wait_until="domcontentloaded", timeout=15000)
                page_text = page.locator("body").inner_text(timeout=8000)
                page.screenshot(path=str(screenshot), full_page=True)
                browser.close()
            matched = [term for term in keywords if term and term in page_text]
            if matched:
                return VerificationOutcome(
                    True,
                    min(0.65 + 0.03 * len(matched), 0.82),
                    f"页面文本命中关键词: {', '.join(matched)}",
                    str(screenshot),
                )
            return VerificationOutcome(False, 0.0, "Web页面未命中关键功能词", str(screenshot))
        except playwright_error as exc:
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message:
                return VerificationOutcome(
                    False,
                    0.0,
                    "Playwright 浏览器未安装。请执行 .venv/bin/python -m playwright install chromium 后重试。",
                )
            return VerificationOutcome(False, 0.0, f"Web验证失败: {exc}")
        except Exception as exc:  # noqa: BLE001
            return VerificationOutcome(False, 0.0, f"Web验证失败: {exc}")
