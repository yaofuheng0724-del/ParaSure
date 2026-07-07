from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .web_models import DEFAULT_READONLY_BLOCKLIST


@dataclass(frozen=True)
class WebPlaybook:
    product: str
    entry_actions: tuple[dict[str, Any], ...]
    evidence_rules: dict[str, Any]
    search_selectors: tuple[str, ...] = ()
    menu_selectors: tuple[str, ...] = ()
    readonly_blocklist: tuple[str, ...] = DEFAULT_READONLY_BLOCKLIST
    max_excerpt_chars: int = 1200
    raw: dict[str, Any] = field(default_factory=dict)

    def is_blocked_click(self, label: str) -> bool:
        normalized = label.casefold()
        return any(word.casefold() in normalized for word in self.readonly_blocklist if word)


def load_playbook(path: Path) -> WebPlaybook:
    data = _load_structured_file(path)
    if not isinstance(data, dict):
        raise ValueError("playbook must be a JSON/YAML object")
    _require_key(data, "product")
    _require_key(data, "entry_actions")
    _require_key(data, "evidence_rules")
    entry_actions = data["entry_actions"]
    if not isinstance(entry_actions, list) or not entry_actions:
        raise ValueError("entry_actions must be a non-empty list")
    evidence_rules = data["evidence_rules"]
    if not isinstance(evidence_rules, dict) or not evidence_rules:
        raise ValueError("evidence_rules must be a non-empty object")
    readonly_blocklist = tuple(data.get("readonly_blocklist") or DEFAULT_READONLY_BLOCKLIST)
    playbook = WebPlaybook(
        product=str(data["product"]),
        entry_actions=tuple(dict(action) for action in entry_actions),
        evidence_rules=dict(evidence_rules),
        search_selectors=tuple(str(item) for item in data.get("search_selectors", ())),
        menu_selectors=tuple(str(item) for item in data.get("menu_selectors", ())),
        readonly_blocklist=readonly_blocklist,
        max_excerpt_chars=int(data.get("max_excerpt_chars", 1200)),
        raw=data,
    )
    for action in playbook.entry_actions:
        if action.get("type") == "click" and playbook.is_blocked_click(str(action.get("text", ""))):
            raise ValueError(f"entry_actions contains blocked readonly action: {action.get('text')}")
    return playbook


def find_playbook(product: str, playbook_dir: Path) -> WebPlaybook | None:
    if not playbook_dir.exists():
        return None
    for path in sorted([*playbook_dir.glob("*.json"), *playbook_dir.glob("*.yaml"), *playbook_dir.glob("*.yml")]):
        playbook = load_playbook(path)
        if playbook.product == product:
            return playbook
    return None


def _load_structured_file(path: Path) -> Any:
    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(text)
    if suffix in {".yaml", ".yml"}:
        try:
            import yaml  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise ValueError("YAML playbooks require PyYAML; use JSON playbooks in this environment") from exc
        return yaml.safe_load(text)
    raise ValueError(f"unsupported playbook file type: {path.suffix}")


def _require_key(data: dict[str, Any], key: str) -> None:
    if key not in data:
        raise ValueError(f"playbook missing required key: {key}")

