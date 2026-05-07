from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class SessionMemory:
    root: Path = Path(".paramsure/sessions")
    session_id: str = field(default_factory=lambda: uuid4().hex[:12])

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8") if not self.path.exists() else None

    @property
    def path(self) -> Path:
        return self.root / f"{self.session_id}.jsonl"

    def append(self, event_type: str, payload: dict) -> None:
        event = {
            "time": utc_now(),
            "type": event_type,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, ensure_ascii=False) + "\n")

    def recent_summary(self, limit: int = 12) -> str:
        if not self.path.exists():
            return ""
        lines = self.path.read_text(encoding="utf-8").splitlines()[-limit:]
        summaries = []
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            summaries.append(f"- {event.get('type')}: {json.dumps(event.get('payload', {}), ensure_ascii=False)[:500]}")
        return "\n".join(summaries)
