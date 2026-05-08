from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Verdict(str, Enum):
    MATERIAL_MATCH = "资料已满足"
    WEB_CONFIRMED = "Web已确认"
    UNSUPPORTED = "不满足"
    UNKNOWN = "未确认"


class EvidenceSource(str, Enum):
    MATERIAL = "产品参数库"
    WEB = "Web演示环境"
    API = "只读API"
    NONE = "无"


class VerificationNeed(str, Enum):
    NOT_NEEDED = "无需二次验证"
    RECOMMENDED = "建议二次验证"
    REQUIRED = "需要二次验证"


@dataclass(frozen=True)
class ProductParameter:
    product: str
    module: str
    feature: str
    description: str
    version: str = ""
    edition: str = ""
    remarks: str = ""
    source_file: str = ""
    sheet_name: str = ""
    row_number: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def evidence_text(self) -> str:
        parts = [self.module, self.feature, self.description, self.version, self.edition, self.remarks]
        return " ".join(part for part in parts if part).strip()


@dataclass(frozen=True)
class TenderRequirement:
    requirement_id: str
    title: str
    description: str
    source_file: str = ""
    sheet_name: str = ""
    row_number: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(part for part in [self.title, self.description] if part).strip()


@dataclass(frozen=True)
class MatchCandidate:
    parameter: ProductParameter
    score: float
    matched_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class NaturalLanguageRequirementSet:
    product: str
    requirements: list[TenderRequirement]
    source_text: str


@dataclass
class ProductContext:
    product: str
    parameter_count: int
    modules: list[str] = field(default_factory=list)
    sample_features: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class VerificationDecision:
    requirement: TenderRequirement
    product: str
    initial_verdict: Verdict
    confidence: float
    needs_web_verification: bool
    verification_need: VerificationNeed
    reason: str
    evidence_summary: str = ""
    evidence_location: str = ""
    matched_feature: str = ""
    candidates: list[MatchCandidate] = field(default_factory=list)


@dataclass
class VerificationConfig:
    enabled: bool = False
    cdp_url: str = ""
    browser_state: Path | None = None
    base_url: str = ""
    search_hint: str = ""
    api_base_url: str = ""
    api_token: str = ""


@dataclass
class ComplianceResult:
    requirement: TenderRequirement
    product: str
    verdict: Verdict
    confidence: float
    evidence_source: EvidenceSource
    matched_feature: str = ""
    evidence_summary: str = ""
    evidence_location: str = ""
    web_artifact: str = ""
    api_summary: str = ""
    risk_note: str = ""
    response_suggestion: str = ""
    candidates: list[MatchCandidate] = field(default_factory=list)
