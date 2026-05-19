from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .bootstrap import auto_index_product_params
from .config import AgentConfig
from .context import build_product_context
from .decision import decide_from_candidates
from .models import MatchCandidate, ProductContext, VerificationDecision, VerificationNeed
from .nl_input import parse_natural_language_requirements
from .retriever import ParameterRetriever
from .store import ParameterStore
from .verifier import WebVerifier
from .models import VerificationConfig, Verdict, TenderRequirement


@dataclass
class AssessmentReport:
    product: str
    source_text: str
    product_context: ProductContext | None
    decisions: list[VerificationDecision] = field(default_factory=list)
    needs_clarification: bool = False
    clarification_reason: str = ""

    @property
    def pending_verifications(self) -> list[VerificationDecision]:
        return [decision for decision in self.decisions if decision.needs_web_verification]


class V2Workflow:
    def __init__(self, store: ParameterStore, config: AgentConfig, artifact_dir: Path) -> None:
        self.store = store
        self.config = config
        self.artifact_dir = artifact_dir
        auto_index_product_params(self.store, self.config.product_params_path())

    def assess_natural_language(self, text: str) -> AssessmentReport:
        available_products = [name for name, _ in self.store.products()]
        parsed = parse_natural_language_requirements(text, available_products)
        if not parsed.product:
            return AssessmentReport(
                product="",
                source_text=text,
                product_context=None,
                needs_clarification=True,
                clarification_reason="未能从输入中识别目标产品，请先指定产品名称。",
            )

        parameters = self.store.by_product(parsed.product)
        product_context = build_product_context(parsed.product, parameters)
        retriever = ParameterRetriever(parameters)
        decisions: list[VerificationDecision] = []
        for req in parsed.requirements:
            candidates = retriever.search(req, limit=5)
            decisions.append(decide_from_candidates(req, parsed.product, candidates))
        return AssessmentReport(
            product=parsed.product,
            source_text=text,
            product_context=product_context,
            decisions=decisions,
        )

    def render_assessment(self, report: AssessmentReport) -> str:
        if report.needs_clarification:
            return report.clarification_reason
        lines = [
            f"目标产品：{report.product}",
            f"产品上下文：{report.product_context.summary if report.product_context else ''}",
            "第一阶段资料核验结果：",
        ]
        for decision in report.decisions:
            status = decision.initial_verdict.value
            lines.append(
                f"- [{status}] {decision.requirement.text}"
                + (f" | 证据：{decision.evidence_location}" if decision.evidence_location else "")
                + (f" | 原因：{decision.reason}" if decision.reason else "")
            )
        pending = report.pending_verifications
        if pending:
            lines.append("需要二次验证的条目：")
            for index, decision in enumerate(pending, start=1):
                need = decision.verification_need.value
                lines.append(f"  {index}. {decision.requirement.text} [{need}]")
        else:
            lines.append("当前无需二次验证。")
        return "\n".join(lines)

    def prompt_for_verification(self, report: AssessmentReport) -> str:
        if not report.pending_verifications:
            return ""
        lines = [
            "我已经完成第一阶段资料核验，以下条目建议进行 Web/API 二次验证：",
        ]
        for index, decision in enumerate(report.pending_verifications, start=1):
            lines.append(
                f"{index}. {decision.requirement.text}"
                + (f" | 依据：{decision.evidence_location}" if decision.evidence_location else "")
                + f" | 建议：{decision.verification_need.value}"
            )
        lines.append("是否继续进行第二阶段 Web/API 验证？[y/N]")
        return "\n".join(lines)

    def verify_pending(self, report: AssessmentReport, web_url: str) -> list[VerificationDecision]:
        verification_config = VerificationConfig(
            enabled=True,
            base_url=web_url,
            cdp_url=self.config.cdp_url(),
            playbook_dir=str(self.config.web_playbooks_path()),
        )
        verifier = WebVerifier(verification_config, self.artifact_dir, product=report.product)
        verified: list[VerificationDecision] = []
        for decision in report.pending_verifications:
            outcome = verifier.verify(decision.requirement)
            verified.append(
                VerificationDecision(
                    requirement=decision.requirement,
                    product=decision.product,
                    initial_verdict=Verdict.WEB_CONFIRMED if outcome.confirmed else decision.initial_verdict,
                    confidence=outcome.confidence or decision.confidence,
                    needs_web_verification=False,
                    verification_need=VerificationNeed.NOT_NEEDED,
                    reason=outcome.summary or decision.reason,
                    evidence_summary=outcome.summary or decision.evidence_summary,
                    evidence_location=web_url,
                    matched_feature=decision.matched_feature,
                    candidates=decision.candidates,
                )
            )
        return verified
