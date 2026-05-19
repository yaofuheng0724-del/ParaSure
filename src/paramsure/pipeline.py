from __future__ import annotations

from pathlib import Path
from typing import Any

from .excel_io import load_tender_requirements, write_results
from .models import ComplianceResult, EvidenceSource, TenderRequirement, Verdict, VerificationConfig
from .retriever import ParameterRetriever
from .store import ParameterStore
from .verifier import ApiVerifier, WebVerifier


class ParaSurePipeline:
    """Deterministic fallback pipeline retained as an agent tool."""

    def __init__(self, store: ParameterStore, artifact_dir: Path):
        self.store = store
        self.artifact_dir = artifact_dir

    def evaluate_excel(
        self,
        tender_file: Path,
        product: str,
        output: Path,
        verification: VerificationConfig | None = None,
        material_threshold: float = 0.24,
        uncertain_threshold: float = 0.15,
    ) -> list[ComplianceResult]:
        verification = verification or VerificationConfig()
        requirements = load_tender_requirements(tender_file)
        parameters = self.store.by_product(product)
        if not parameters:
            raise ValueError(f"知识库中未找到产品: {product}")
        retriever = ParameterRetriever(parameters)
        web = WebVerifier(verification, self.artifact_dir, product=product)
        api = ApiVerifier(verification)

        results: list[ComplianceResult] = []
        for requirement in requirements:
            candidates = retriever.search(requirement, limit=5)
            best = candidates[0] if candidates else None
            if best and best.score >= material_threshold:
                results.append(self._material_result(requirement, product, best, candidates))
                continue

            verification_result = None
            if verification.api_base_url and verification.api_token:
                api_result = api.verify(requirement)
                if api_result.confirmed:
                    verification_result = ComplianceResult(
                        requirement=requirement,
                        product=product,
                        verdict=Verdict.WEB_CONFIRMED,
                        confidence=api_result.confidence,
                        evidence_source=EvidenceSource.API,
                        matched_feature=best.parameter.feature if best else "",
                        evidence_summary=api_result.summary,
                        evidence_location=verification.api_base_url,
                        api_summary=api_result.summary,
                        risk_note="API仅完成只读确认，建议人工复核接口语义与参数原文的一致性。",
                        response_suggestion="可响应支持，依据演示环境API只读验证结果确认。",
                        candidates=candidates,
                    )
            if verification_result is None and verification.enabled:
                web_result = web.verify(requirement)
                if web_result.confirmed:
                    verification_result = ComplianceResult(
                        requirement=requirement,
                        product=product,
                        verdict=Verdict.WEB_CONFIRMED,
                        confidence=web_result.confidence,
                        evidence_source=EvidenceSource.WEB,
                        matched_feature=best.parameter.feature if best else "",
                        evidence_summary=web_result.summary,
                        evidence_location=verification.base_url,
                        web_artifact=web_result.artifact,
                        web_evidence=web_result.evidence_path,
                        risk_note="Web验证基于页面文本命中，建议在正式应答前补充截图或产品手册证据。",
                        response_suggestion="可响应支持，依据演示环境页面核验结果确认。",
                        candidates=candidates,
                    )
                else:
                    verification_result = self._web_unknown_result(
                        requirement,
                        product,
                        best,
                        candidates,
                        verification.base_url,
                        web_result,
                    )
            if verification_result is not None:
                results.append(verification_result)
                continue

            results.append(self._unknown_result(requirement, product, best, candidates, uncertain_threshold))

        write_results(output, results)
        return results

    @staticmethod
    def _material_result(requirement: TenderRequirement, product: str, best: Any, candidates: Any) -> ComplianceResult:
        parameter = best.parameter
        location = f"{Path(parameter.source_file).name} / {parameter.sheet_name} / 第{parameter.row_number}行"
        return ComplianceResult(
            requirement=requirement,
            product=product,
            verdict=Verdict.MATERIAL_MATCH,
            confidence=best.score,
            evidence_source=EvidenceSource.MATERIAL,
            matched_feature=parameter.feature or parameter.module,
            evidence_summary=parameter.evidence_text[:500],
            evidence_location=location,
            risk_note="资料库已找到相似功能参数，正式投标前建议核对版本/型号适用范围。",
            response_suggestion="可响应支持，产品参数中已有对应或相似能力描述。",
            candidates=candidates,
        )

    @staticmethod
    def _unknown_result(
        requirement: TenderRequirement,
        product: str,
        best: Any,
        candidates: Any,
        uncertain_threshold: float,
    ) -> ComplianceResult:
        if best and best.score >= uncertain_threshold:
            parameter = best.parameter
            return ComplianceResult(
                requirement=requirement,
                product=product,
                verdict=Verdict.UNKNOWN,
                confidence=best.score,
                evidence_source=EvidenceSource.NONE,
                matched_feature=parameter.feature or parameter.module,
                evidence_summary=parameter.evidence_text[:500],
                evidence_location=f"{Path(parameter.source_file).name} / {parameter.sheet_name} / 第{parameter.row_number}行",
                risk_note="资料存在弱相关候选，但不足以直接证明满足；建议通过演示环境或产品专家确认。",
                response_suggestion="建议暂按需确认响应，补充截图、产品手册或演示验证证据后再定稿。",
                candidates=candidates,
            )
        return ComplianceResult(
            requirement=requirement,
            product=product,
            verdict=Verdict.UNKNOWN,
            confidence=0.0,
            evidence_source=EvidenceSource.NONE,
            risk_note="产品参数库和当前验证工具均未找到可支撑证据。",
            response_suggestion="建议标记为待确认，不直接承诺满足。",
            candidates=candidates,
        )

    @staticmethod
    def _web_unknown_result(
        requirement: TenderRequirement,
        product: str,
        best: Any,
        candidates: Any,
        web_url: str,
        web_result: Any,
    ) -> ComplianceResult:
        matched_feature = best.parameter.feature if best else ""
        material_summary = best.parameter.evidence_text[:500] if best else ""
        evidence_summary = web_result.summary or material_summary
        return ComplianceResult(
            requirement=requirement,
            product=product,
            verdict=Verdict.UNKNOWN,
            confidence=web_result.confidence or 0.0,
            evidence_source=EvidenceSource.WEB,
            matched_feature=matched_feature,
            evidence_summary=evidence_summary,
            evidence_location=web_url,
            web_artifact=web_result.artifact,
            web_evidence=web_result.evidence_path,
            risk_note="已执行Web二次验证，但页面证据不足以确认支持；建议人工复核或补充API/产品手册证据。",
            response_suggestion="建议暂按未确认响应，补充可审计证据后再承诺支持。",
            candidates=candidates,
        )
