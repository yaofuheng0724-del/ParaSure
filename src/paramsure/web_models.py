from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .models import Verdict, VerificationDecision
from .text import top_terms


DEFAULT_READONLY_BLOCKLIST = (
    "保存",
    "删除",
    "新增",
    "提交",
    "启用",
    "禁用",
    "下发",
    "发布",
    "重启",
    "清空",
    "导入",
    "上传",
    "save",
    "delete",
    "create",
    "submit",
    "enable",
    "disable",
    "restart",
    "upload",
)


@dataclass(frozen=True)
class VerificationIntent:
    product: str
    requirement_id: str
    requirement_text: str
    keywords: tuple[str, ...]
    suggested_paths: tuple[str, ...] = ()
    readonly_blocklist: tuple[str, ...] = DEFAULT_READONLY_BLOCKLIST

    @classmethod
    def from_decision(
        cls,
        decision: VerificationDecision,
        readonly_blocklist: tuple[str, ...] | None = None,
    ) -> "VerificationIntent":
        suggested_paths: list[str] = []
        if decision.matched_feature:
            suggested_paths.append(decision.matched_feature)
        for candidate in decision.candidates[:3]:
            feature = candidate.parameter.feature or candidate.parameter.module
            if feature and feature not in suggested_paths:
                suggested_paths.append(feature)
        return cls(
            product=decision.product,
            requirement_id=decision.requirement.requirement_id,
            requirement_text=decision.requirement.text,
            keywords=top_terms(decision.requirement.text, 8),
            suggested_paths=tuple(suggested_paths),
            readonly_blocklist=readonly_blocklist or DEFAULT_READONLY_BLOCKLIST,
        )


@dataclass(frozen=True)
class WebEvidenceBundle:
    product: str
    requirement_id: str
    requirement_text: str
    final_url: str = ""
    screenshot_path: str = ""
    evidence_path: str = ""
    page_excerpt: str = ""
    keyword_matches: tuple[str, ...] = ()
    dom_matches: tuple[str, ...] = ()
    steps: tuple[str, ...] = ()
    failed_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EvidenceJudgement:
    verdict: Verdict
    confidence: float
    reason: str
    evidence_summary: str = ""
    evidence_location: str = ""
    web_artifact: str = ""
    evidence_path: str = ""

