from __future__ import annotations

import json
import re
from importlib import import_module
from pathlib import Path

from .models import VerificationConfig
from .web_models import VerificationIntent, WebEvidenceBundle
from .web_playbook import WebPlaybook


class PlaybookWebRunner:
    def __init__(self, config: VerificationConfig, artifact_dir: Path, playwright_module=None):
        self.config = config
        self.artifact_dir = artifact_dir
        self.playwright_module = playwright_module

    def run(self, intent: VerificationIntent, playbook: WebPlaybook) -> WebEvidenceBundle:
        if not self.config.enabled:
            return self._failed(intent, "未启用Web验证")
        if not self.config.base_url:
            return self._failed(intent, "未配置产品Web地址")
        playwright = self.playwright_module
        if playwright is None:
            try:
                playwright = import_module("playwright.sync_api")
            except Exception:
                return self._failed(
                    intent,
                    "ParaSure 的 .venv 未安装 playwright。请运行 ./paramsure 让依赖自动安装，或执行 .venv/bin/python -m pip install -e .",
                )

        sync_playwright = playwright.sync_playwright
        playwright_error = getattr(playwright, "Error", Exception)
        run_dir = self._run_dir(intent)
        screenshot = run_dir / "screenshot.png"
        steps: list[str] = []
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
                self._run_entry_actions(page, playbook, steps)
                self._try_global_search(page, intent, playbook, steps)
                page_text = page.locator("body").inner_text(timeout=8000)
                page.screenshot(path=str(screenshot), full_page=True)
                final_url = getattr(page, "url", self.config.base_url)
                browser.close()
        except playwright_error as exc:
            message = str(exc)
            if "Executable doesn't exist" in message or "playwright install" in message:
                return self._failed(intent, "Playwright 浏览器未安装。请执行 .venv/bin/python -m playwright install chromium 后重试。")
            return self._failed(intent, f"Web验证失败: {exc}", tuple(steps))
        except Exception as exc:  # noqa: BLE001
            return self._failed(intent, f"Web验证失败: {exc}", tuple(steps))

        keyword_matches = _keyword_matches(intent.keywords, page_text)
        dom_matches = _context_lines(page_text, keyword_matches + intent.suggested_paths)
        bundle = WebEvidenceBundle(
            product=intent.product,
            requirement_id=intent.requirement_id,
            requirement_text=intent.requirement_text,
            final_url=final_url,
            screenshot_path=str(screenshot),
            evidence_path=str(run_dir / "evidence.json"),
            page_excerpt=page_text[: playbook.max_excerpt_chars],
            keyword_matches=keyword_matches,
            dom_matches=dom_matches,
            steps=tuple(steps),
        )
        self._persist(bundle, run_dir)
        return bundle

    def _run_entry_actions(self, page, playbook: WebPlaybook, steps: list[str]) -> None:
        for action in playbook.entry_actions:
            action_type = action.get("type")
            if action_type == "goto":
                page.goto(self.config.base_url, wait_until="domcontentloaded", timeout=15000)
                steps.append(f"goto {self.config.base_url}")
                continue
            if action_type == "click":
                label = str(action.get("text", ""))
                if playbook.is_blocked_click(label):
                    steps.append(f"blocked click {label}")
                    continue
                steps.append(f"skip unsupported click {label}")

    @staticmethod
    def _try_global_search(
        page,
        intent: VerificationIntent,
        playbook: WebPlaybook,
        steps: list[str],
    ) -> None:
        query = intent.keywords[0] if intent.keywords else intent.requirement_text[:30]
        if not query:
            return
        for selector in playbook.search_selectors:
            try:
                locator = page.locator(selector)
                if hasattr(locator, "first"):
                    locator = locator.first()
                if not hasattr(locator, "fill") or not hasattr(locator, "press"):
                    continue
                locator.fill(query)
                locator.press("Enter")
                steps.append(f"search {selector} {query}")
                return
            except Exception:  # noqa: BLE001 - selector misses are normal across products.
                continue

    def _failed(
        self,
        intent: VerificationIntent,
        reason: str,
        steps: tuple[str, ...] = (),
    ) -> WebEvidenceBundle:
        run_dir = self._run_dir(intent)
        bundle = WebEvidenceBundle(
            product=intent.product,
            requirement_id=intent.requirement_id,
            requirement_text=intent.requirement_text,
            evidence_path=str(run_dir / "evidence.json"),
            failed_reason=reason,
            steps=steps,
        )
        self._persist(bundle, run_dir)
        return bundle

    def _run_dir(self, intent: VerificationIntent) -> Path:
        root = Path(getattr(self.config, "evidence_dir", "") or self.artifact_dir)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", intent.requirement_id).strip("_") or "manual"
        path = root / safe_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _persist(bundle: WebEvidenceBundle, run_dir: Path) -> None:
        (run_dir / "evidence.json").write_text(
            json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if bundle.page_excerpt:
            (run_dir / "page_excerpt.txt").write_text(bundle.page_excerpt, encoding="utf-8")


def _keyword_matches(keywords: tuple[str, ...], page_text: str) -> tuple[str, ...]:
    lowered = page_text.casefold()
    return tuple(dict.fromkeys(keyword for keyword in keywords if keyword and keyword.casefold() in lowered))


def _context_lines(page_text: str, needles: tuple[str, ...]) -> tuple[str, ...]:
    matches: list[str] = []
    lowered_needles = [needle.casefold() for needle in needles if needle]
    if not lowered_needles:
        return ()
    for line in page_text.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if not clean:
            continue
        lowered = clean.casefold()
        if any(needle in lowered for needle in lowered_needles):
            matches.append(clean)
    return tuple(dict.fromkeys(matches[:8]))
