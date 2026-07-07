from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import VerificationConfig
from .web_models import DEFAULT_READONLY_BLOCKLIST, VerificationIntent, WebEvidenceBundle


@dataclass(frozen=True)
class WebTestScript:
    name: str
    type: str
    path: Path
    capabilities: tuple[str, ...]


@dataclass(frozen=True)
class WebTestManifest:
    product: str
    slug: str
    root: Path
    aliases: tuple[str, ...]
    readonly_blocklist: tuple[str, ...]
    scripts: tuple[WebTestScript, ...]

    def matches_product(self, product: str) -> bool:
        normalized = product.casefold()
        names = (self.product, self.slug, *self.aliases)
        return any(name.casefold() == normalized for name in names)

    def select_script(self, intent: VerificationIntent) -> WebTestScript | None:
        verify_scripts = [script for script in self.scripts if script.type == "verify"]
        if not verify_scripts:
            return None
        haystack = " ".join((intent.requirement_text, *intent.keywords)).casefold()
        for script in verify_scripts:
            if any(capability.casefold() in haystack for capability in script.capabilities):
                return script
        return verify_scripts[0]


class WebTestScriptRunner:
    def __init__(
        self,
        config: VerificationConfig,
        artifact_dir: Path,
        python_executable: str | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.config = config
        self.artifact_dir = artifact_dir
        self.python_executable = python_executable or sys.executable
        self.timeout_seconds = timeout_seconds

    def run(self, intent: VerificationIntent, manifest: WebTestManifest) -> WebEvidenceBundle:
        if not self.config.enabled:
            return self._failed(intent, "未启用Web验证")
        if not self.config.base_url:
            return self._failed(intent, "未配置产品Web地址")
        script = manifest.select_script(intent)
        if script is None:
            return self._failed(intent, f"产品脚本库未找到可执行验证脚本: {manifest.product}")
        out_dir = self._run_dir(intent)
        command = [
            self.python_executable,
            str(script.path),
            "--base-url",
            self.config.base_url,
            "--requirement-id",
            intent.requirement_id,
            "--requirement-text",
            intent.requirement_text,
            "--out-dir",
            str(out_dir),
        ]
        if self.config.cdp_url:
            command.extend(["--cdp-url", self.config.cdp_url])
        try:
            result = subprocess.run(
                command,
                cwd=str(manifest.root),
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001
            return self._failed(intent, f"产品验证脚本执行失败: {exc}")

        if result.returncode != 0:
            reason = "\n".join(part for part in [result.stdout.strip(), result.stderr.strip()] if part)
            return self._failed(intent, f"产品验证脚本返回非零状态 {result.returncode}: {reason[:500]}")

        evidence_path = out_dir / "evidence.json"
        if not evidence_path.exists():
            return self._failed(intent, "产品验证脚本未生成 evidence.json")
        try:
            data = json.loads(evidence_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return self._failed(intent, f"产品验证脚本生成的 evidence.json 不合法: {exc}")
        return _bundle_from_evidence(data, intent, evidence_path)

    def _run_dir(self, intent: VerificationIntent) -> Path:
        root = Path(getattr(self.config, "evidence_dir", "") or self.artifact_dir).resolve()
        safe_id = _safe_requirement_id(intent.requirement_id)
        path = root / safe_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _failed(self, intent: VerificationIntent, reason: str) -> WebEvidenceBundle:
        out_dir = self._run_dir(intent)
        bundle = WebEvidenceBundle(
            product=intent.product,
            requirement_id=intent.requirement_id,
            requirement_text=intent.requirement_text,
            evidence_path=str(out_dir / "evidence.json"),
            failed_reason=reason,
        )
        (out_dir / "evidence.json").write_text(json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return bundle


def load_web_test_manifest(path: Path) -> WebTestManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("web test manifest must be a JSON object")
    for key in ("product", "slug", "scripts"):
        if key not in data:
            raise ValueError(f"web test manifest missing required key: {key}")
    root = path.parent.resolve()
    scripts = tuple(_script_from_data(root, item) for item in data["scripts"])
    if not scripts:
        raise ValueError("web test manifest scripts must not be empty")
    return WebTestManifest(
        product=str(data["product"]),
        slug=str(data["slug"]),
        root=root,
        aliases=tuple(str(item) for item in data.get("aliases", ())),
        readonly_blocklist=tuple(data.get("readonly_blocklist") or DEFAULT_READONLY_BLOCKLIST),
        scripts=scripts,
    )


def find_product_web_tests(product: str, web_tests_dir: Path) -> WebTestManifest | None:
    if not web_tests_dir.exists():
        return None
    for manifest_path in sorted(web_tests_dir.glob("*/manifest.json")):
        manifest = load_web_test_manifest(manifest_path)
        if manifest.matches_product(product):
            return manifest
    return None


def _script_from_data(root: Path, data: dict[str, Any]) -> WebTestScript:
    for key in ("name", "type", "path"):
        if key not in data:
            raise ValueError(f"web test script missing required key: {key}")
    path = (root / str(data["path"])).resolve()
    if not path.exists():
        raise ValueError(f"web test script file does not exist: {path}")
    return WebTestScript(
        name=str(data["name"]),
        type=str(data["type"]),
        path=path,
        capabilities=tuple(str(item) for item in data.get("capabilities", ())),
    )


def _bundle_from_evidence(data: dict[str, Any], intent: VerificationIntent, evidence_path: Path) -> WebEvidenceBundle:
    return WebEvidenceBundle(
        product=str(data.get("product") or intent.product),
        requirement_id=str(data.get("requirement_id") or intent.requirement_id),
        requirement_text=str(data.get("requirement_text") or intent.requirement_text),
        final_url=str(data.get("final_url") or ""),
        screenshot_path=str(data.get("screenshot_path") or ""),
        evidence_path=str(data.get("evidence_path") or evidence_path),
        page_excerpt=str(data.get("page_excerpt") or ""),
        keyword_matches=tuple(str(item) for item in data.get("keyword_matches", ())),
        dom_matches=tuple(str(item) for item in data.get("dom_matches", ())),
        steps=tuple(str(item) for item in data.get("steps", ())),
        failed_reason=str(data.get("failed_reason") or ""),
    )


def _safe_requirement_id(requirement_id: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_.-]+", "_", requirement_id).strip("_") or "manual"
