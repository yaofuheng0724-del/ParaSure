from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from urllib import request

from .evidence_judge import judge_web_evidence
from .models import TenderRequirement, VerificationConfig, Verdict
from .text import top_terms
from .web_models import VerificationIntent
from .web_playbook import WebPlaybook, find_playbook
from .web_runner import PlaybookWebRunner


@dataclass
class VerificationOutcome:
    confirmed: bool
    confidence: float
    summary: str = ""
    artifact: str = ""
    evidence_path: str = ""


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


class PlaybookWebVerifier:
    def __init__(self, config: VerificationConfig, artifact_dir: Path, product: str = ""):
        self.config = config
        self.artifact_dir = artifact_dir
        self.product = product

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

        playbook = find_playbook(self.product, Path(self.config.playbook_dir)) if self.product else None
        playbook = playbook or _default_playbook(self.product, self.config.readonly_blocklist)
        intent = VerificationIntent(
            product=self.product,
            requirement_id=requirement.requirement_id,
            requirement_text=requirement.text,
            keywords=top_terms(requirement.text, 8),
            readonly_blocklist=self.config.readonly_blocklist,
        )
        bundle = PlaybookWebRunner(self.config, self.artifact_dir, playwright_module=playwright).run(intent, playbook)
        judgement = judge_web_evidence(intent, bundle)
        return VerificationOutcome(
            confirmed=judgement.verdict == Verdict.WEB_CONFIRMED,
            confidence=judgement.confidence,
            summary=f"{judgement.reason} {judgement.evidence_summary}".strip(),
            artifact=judgement.web_artifact,
            evidence_path=judgement.evidence_path,
        )


class WebVerifier(PlaybookWebVerifier):
    """Backward-compatible facade for the V3 playbook-based verifier."""


def _default_playbook(product: str, readonly_blocklist: tuple[str, ...]) -> WebPlaybook:
    return WebPlaybook(
        product=product,
        entry_actions=({"type": "goto"},),
        evidence_rules={"min_dom_matches": 1},
        readonly_blocklist=readonly_blocklist,
    )
