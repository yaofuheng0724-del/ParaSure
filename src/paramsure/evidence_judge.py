from __future__ import annotations

from .models import Verdict
from .web_models import EvidenceJudgement, VerificationIntent, WebEvidenceBundle


def judge_web_evidence(intent: VerificationIntent, bundle: WebEvidenceBundle) -> EvidenceJudgement:
    if bundle.failed_reason:
        return EvidenceJudgement(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            reason=f"Web验证失败: {bundle.failed_reason}",
            evidence_summary=bundle.page_excerpt[:500],
            evidence_location=bundle.final_url,
            web_artifact=bundle.screenshot_path,
            evidence_path=bundle.evidence_path,
        )

    if not bundle.dom_matches:
        return EvidenceJudgement(
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            reason="仅命中关键词，缺少可审计页面上下文，不能确认产品支持该参数。",
            evidence_summary=bundle.page_excerpt[:500],
            evidence_location=bundle.final_url,
            web_artifact=bundle.screenshot_path,
            evidence_path=bundle.evidence_path,
        )

    if not bundle.keyword_matches:
        return EvidenceJudgement(
            verdict=Verdict.UNKNOWN,
            confidence=0.35,
            reason="页面存在相关上下文，但未命中需求关键词，需要人工复核。",
            evidence_summary=_summary(bundle),
            evidence_location=bundle.final_url,
            web_artifact=bundle.screenshot_path,
            evidence_path=bundle.evidence_path,
        )

    confidence = min(0.72 + 0.03 * len(bundle.dom_matches) + 0.02 * len(bundle.keyword_matches), 0.88)
    return EvidenceJudgement(
        verdict=Verdict.WEB_CONFIRMED,
        confidence=confidence,
        reason="演示环境页面存在可审计功能上下文，并命中需求关键词。",
        evidence_summary=_summary(bundle),
        evidence_location=bundle.final_url,
        web_artifact=bundle.screenshot_path,
        evidence_path=bundle.evidence_path,
    )


def _summary(bundle: WebEvidenceBundle) -> str:
    dom = "；".join(bundle.dom_matches[:5])
    excerpt = bundle.page_excerpt[:360]
    if dom and excerpt:
        return f"{dom}。页面摘录：{excerpt}"
    return dom or excerpt

