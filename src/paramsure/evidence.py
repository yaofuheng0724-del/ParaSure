from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvidenceSummary:
    sessions: int
    events: int
    tool_observations: int
    tool_failures: int
    evidence_bundles: int
    screenshots: int
    failed_bundles: int
    tool_names: tuple[str, ...]


def summarize_evidence(sessions_dir: Path, artifacts_dir: Path) -> EvidenceSummary:
    session_files = sorted(sessions_dir.glob("*.jsonl")) if sessions_dir.exists() else []
    events = 0
    tool_observations = 0
    tool_failures = 0
    tool_names: set[str] = set()

    for path in session_files:
        for event in _iter_jsonl(path):
            events += 1
            if event.get("type") != "tool_observation":
                continue
            tool_observations += 1
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            name = str(payload.get("name") or payload.get("tool") or "")
            if name:
                tool_names.add(name)
            observation = payload.get("observation")
            if isinstance(observation, dict) and observation.get("ok") is False:
                tool_failures += 1

    evidence_files = sorted(artifacts_dir.rglob("evidence.json")) if artifacts_dir.exists() else []
    screenshots = len(list(artifacts_dir.rglob("screenshot.png"))) if artifacts_dir.exists() else 0
    failed_bundles = 0
    for path in evidence_files:
        data = _read_json(path)
        if data.get("failed_reason"):
            failed_bundles += 1

    return EvidenceSummary(
        sessions=len(session_files),
        events=events,
        tool_observations=tool_observations,
        tool_failures=tool_failures,
        evidence_bundles=len(evidence_files),
        screenshots=screenshots,
        failed_bundles=failed_bundles,
        tool_names=tuple(sorted(tool_names)),
    )


def _iter_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            rows.append(event)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
