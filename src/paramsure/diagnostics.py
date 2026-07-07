from __future__ import annotations

import importlib.util
import platform
from dataclasses import dataclass
from pathlib import Path

from .config import AgentConfig


@dataclass(frozen=True)
class DiagnosticCheck:
    name: str
    ok: bool
    detail: str


def run_diagnostics(config: AgentConfig, artifacts_dir: Path) -> list[DiagnosticCheck]:
    params_path = config.product_params_path()
    artifacts_ok = artifacts_dir.exists() or artifacts_dir.parent.exists()
    return [
        DiagnosticCheck("Python", True, platform.python_version()),
        DiagnosticCheck("LLM config", bool(config.api_key and config.base_url and config.model), _llm_detail(config)),
        DiagnosticCheck("Product params", params_path.exists(), str(params_path)),
        DiagnosticCheck("Playwright", importlib.util.find_spec("playwright") is not None, "python package"),
        DiagnosticCheck("Chrome CDP", bool(config.cdp_url()), config.cdp_url() or "not configured"),
        DiagnosticCheck("Evidence dir", artifacts_ok, str(artifacts_dir)),
    ]


def _llm_detail(config: AgentConfig) -> str:
    key_state = "configured" if config.api_key else "missing api_key"
    return f"{config.model} @ {config.base_url} ({key_state})"
