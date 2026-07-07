from __future__ import annotations

from pathlib import Path

from .models import MatchCandidate, TenderRequirement, Verdict, VerificationDecision, VerificationNeed


def decide_from_candidates(
    requirement: TenderRequirement,
    product: str,
    candidates: list[MatchCandidate],
    material_threshold: float = 0.24,
    weak_threshold: float = 0.15,
) -> VerificationDecision:
    best = candidates[0] if candidates else None
    if best and best.score >= material_threshold:
        parameter = best.parameter
        return VerificationDecision(
            requirement=requirement,
            product=product,
            initial_verdict=Verdict.MATERIAL_MATCH,
            confidence=best.score,
            needs_web_verification=False,
            verification_need=VerificationNeed.NOT_NEEDED,
            reason="产品招标参数库中已有较明确的相似功能证据。",
            evidence_summary=parameter.evidence_text[:500],
            evidence_location=f"{Path(parameter.source_file).name} / {parameter.sheet_name} / 第{parameter.row_number}行",
            matched_feature=parameter.feature or parameter.module,
            candidates=candidates,
        )
    if best and best.score >= weak_threshold:
        parameter = best.parameter
        return VerificationDecision(
            requirement=requirement,
            product=product,
            initial_verdict=Verdict.UNKNOWN,
            confidence=best.score,
            needs_web_verification=True,
            verification_need=VerificationNeed.RECOMMENDED,
            reason="参数库存在弱相关候选，但不足以支撑售前承诺，建议进入演示环境二次验证。",
            evidence_summary=parameter.evidence_text[:500],
            evidence_location=f"{Path(parameter.source_file).name} / {parameter.sheet_name} / 第{parameter.row_number}行",
            matched_feature=parameter.feature or parameter.module,
            candidates=candidates,
        )
    return VerificationDecision(
        requirement=requirement,
        product=product,
        initial_verdict=Verdict.UNKNOWN,
        confidence=0.0,
        needs_web_verification=True,
        verification_need=VerificationNeed.REQUIRED,
        reason="产品招标参数库未找到可支撑证据，需要演示环境或API进行二次确认。",
        candidates=candidates,
    )
