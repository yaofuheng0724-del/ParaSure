from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .config import AgentConfig
from .context import build_product_context
from .decision import decide_from_candidates
from .excel_io import load_tender_requirements, write_results
from .models import ComplianceResult, EvidenceSource, TenderRequirement, Verdict, VerificationConfig
from .nl_input import parse_natural_language_requirements
from .pipeline import ParaSurePipeline
from .retriever import ParameterRetriever
from .store import ParameterStore
from .verifier import ApiVerifier, WebVerifier


ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def openai_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def schemas(self) -> list[dict[str, Any]]:
        return [tool.openai_schema() for tool in self._tools.values()]

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in self._tools:
            return {"ok": False, "error": f"未知工具: {name}"}
        try:
            payload = self._tools[name].handler(arguments)
            return {"ok": True, "tool": name, "result": payload}
        except Exception as exc:  # noqa: BLE001 - tool failures are observations.
            return {"ok": False, "tool": name, "error": str(exc)}


def object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def build_default_registry(store: ParameterStore, artifact_dir: Path, config: AgentConfig | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    agent_config = config or AgentConfig.load()

    def list_products(_: dict[str, Any]) -> dict[str, Any]:
        return {"products": [{"name": name, "count": count} for name, count in store.products()]}

    def parse_tender_excel(args: dict[str, Any]) -> dict[str, Any]:
        requirements = load_tender_requirements(Path(args["path"]))
        return {
            "count": len(requirements),
            "requirements": [
                {
                    "requirement_id": req.requirement_id,
                    "text": req.text,
                    "sheet": req.sheet_name,
                    "row": req.row_number,
                }
                for req in requirements[: int(args.get("limit", 20))]
            ],
        }

    def parse_natural_language(args: dict[str, Any]) -> dict[str, Any]:
        available_products = [name for name, _ in store.products()]
        parsed = parse_natural_language_requirements(args["text"], available_products)
        return {
            "product": parsed.product,
            "requirements": [
                {"requirement_id": req.requirement_id, "text": req.text} for req in parsed.requirements
            ],
            "source_text": parsed.source_text,
            "needs_product_clarification": not bool(parsed.product),
        }

    def load_product_context(args: dict[str, Any]) -> dict[str, Any]:
        product = args["product"]
        parameters = store.by_product(product)
        context = build_product_context(product, parameters, sample_limit=int(args.get("sample_limit", 30)))
        return {
            "product": context.product,
            "parameter_count": context.parameter_count,
            "modules": context.modules,
            "sample_features": context.sample_features,
            "summary": context.summary,
        }

    def search_product_parameters(args: dict[str, Any]) -> dict[str, Any]:
        parameters = store.by_product(args["product"])
        requirement = TenderRequirement(
            requirement_id=str(args.get("requirement_id", "manual")),
            title="",
            description=args["requirement_text"],
        )
        candidates = ParameterRetriever(parameters).search(requirement, limit=int(args.get("limit", 5)))
        return {
            "candidates": [
                {
                    "score": round(candidate.score, 4),
                    "matched_terms": list(candidate.matched_terms),
                    "product": candidate.parameter.product,
                    "module": candidate.parameter.module,
                    "feature": candidate.parameter.feature,
                    "description": candidate.parameter.description,
                    "evidence_location": f"{Path(candidate.parameter.source_file).name} / {candidate.parameter.sheet_name} / 第{candidate.parameter.row_number}行",
                }
                for candidate in candidates
            ]
        }

    def initial_material_assessment(args: dict[str, Any]) -> dict[str, Any]:
        product = args["product"]
        parameters = store.by_product(product)
        retriever = ParameterRetriever(parameters)
        decisions = []
        for index, item in enumerate(args["requirements"], start=1):
            req = TenderRequirement(
                requirement_id=str(item.get("requirement_id") or index),
                title="",
                description=item["text"],
            )
            candidates = retriever.search(req, limit=int(args.get("limit", 5)))
            decision = decide_from_candidates(req, product, candidates)
            decisions.append(
                {
                    "requirement_id": req.requirement_id,
                    "requirement_text": req.text,
                    "initial_verdict": decision.initial_verdict.value,
                    "confidence": round(decision.confidence, 4),
                    "needs_web_verification": decision.needs_web_verification,
                    "verification_need": decision.verification_need.value,
                    "reason": decision.reason,
                    "matched_feature": decision.matched_feature,
                    "evidence_summary": decision.evidence_summary,
                    "evidence_location": decision.evidence_location,
                }
            )
        return {"product": product, "decisions": decisions}

    def verify_web_readonly(args: dict[str, Any]) -> dict[str, Any]:
        product = args.get("product", "")
        web_url = args.get("web_url") or (agent_config.web_url_for(product) if product else "")
        cdp_url = args.get("cdp_url") or agent_config.cdp_url()
        verification_config = VerificationConfig(
            enabled=True,
            cdp_url=cdp_url,
            browser_state=Path(args["browser_state"]) if args.get("browser_state") else None,
            base_url=web_url,
            playbook_dir=str(agent_config.web_playbooks_path()),
        )
        requirement = TenderRequirement(
            requirement_id=str(args.get("requirement_id", "manual")),
            title="",
            description=args["requirement_text"],
        )
        outcome = WebVerifier(verification_config, artifact_dir, product=product).verify(requirement)
        return {
            "confirmed": outcome.confirmed,
            "confidence": outcome.confidence,
            "summary": outcome.summary,
            "artifact": outcome.artifact,
            "evidence_path": outcome.evidence_path,
            "web_url": web_url,
            "cdp_url": cdp_url,
        }

    def verify_api_readonly(args: dict[str, Any]) -> dict[str, Any]:
        config = VerificationConfig(api_base_url=args["api_base_url"], api_token=args["api_token"])
        requirement = TenderRequirement(
            requirement_id=str(args.get("requirement_id", "manual")),
            title="",
            description=args["requirement_text"],
        )
        outcome = ApiVerifier(config).verify(requirement)
        return {
            "confirmed": outcome.confirmed,
            "confidence": outcome.confidence,
            "summary": outcome.summary,
        }

    def run_compliance_check(args: dict[str, Any]) -> dict[str, Any]:
        verification = VerificationConfig(
            enabled=bool(args.get("web_url")),
            cdp_url=args.get("cdp_url", ""),
            browser_state=Path(args["browser_state"]) if args.get("browser_state") else None,
            base_url=args.get("web_url", ""),
            api_base_url=args.get("api_base_url", ""),
            api_token=args.get("api_token", ""),
            playbook_dir=str(agent_config.web_playbooks_path()),
        )
        results = ParaSurePipeline(store, artifact_dir).evaluate_excel(
            Path(args["tender_file"]),
            args["product"],
            Path(args["output_file"]),
            verification=verification,
        )
        counts: dict[str, int] = {}
        for result in results:
            counts[result.verdict.value] = counts.get(result.verdict.value, 0) + 1
        return {"output_file": args["output_file"], "count": len(results), "verdict_counts": counts}

    def write_compliance_matrix(args: dict[str, Any]) -> dict[str, Any]:
        results: list[ComplianceResult] = []
        product = args["product"]
        for idx, item in enumerate(args["results"], start=1):
            requirement = TenderRequirement(
                requirement_id=str(item.get("requirement_id") or idx),
                title="",
                description=item["requirement_text"],
            )
            verdict = Verdict(item.get("verdict", Verdict.UNKNOWN.value))
            source = EvidenceSource(item.get("evidence_source", EvidenceSource.NONE.value))
            results.append(
                ComplianceResult(
                    requirement=requirement,
                    product=product,
                    verdict=verdict,
                    confidence=float(item.get("confidence", 0.0)),
                    evidence_source=source,
                    matched_feature=item.get("matched_feature", ""),
                    evidence_summary=item.get("evidence_summary", ""),
                    evidence_location=item.get("evidence_location", ""),
                    web_artifact=item.get("web_artifact", ""),
                    web_evidence=item.get("web_evidence", ""),
                    api_summary=item.get("api_summary", ""),
                    risk_note=item.get("risk_note", ""),
                    response_suggestion=item.get("response_suggestion", ""),
                )
            )
        write_results(Path(args["output_file"]), results)
        return {"output_file": args["output_file"], "count": len(results)}

    registry.register(
        ToolSpec(
            "list_products",
            "列出本地产品参数知识库中的产品名称和参数数量。",
            object_schema({}),
            list_products,
        )
    )
    registry.register(
        ToolSpec(
            "parse_tender_excel",
            "解析客户招标参数Excel，返回需求条目数量和前若干条文本。",
            object_schema(
                {
                    "path": {"type": "string", "description": "客户招标参数Excel路径"},
                    "limit": {"type": "integer", "description": "最多返回多少条样例", "default": 20},
                },
                ["path"],
            ),
            parse_tender_excel,
        )
    )
    registry.register(
        ToolSpec(
            "parse_natural_language_requirements",
            "从用户自然语言中解析目标产品和少量参数需求。适合2-3条参数的对话式核验。",
            object_schema(
                {
                    "text": {"type": "string", "description": "用户自然语言核验请求。"},
                },
                ["text"],
            ),
            parse_natural_language,
        )
    )
    registry.register(
        ToolSpec(
            "load_product_context",
            "只加载目标产品的产品级上下文包，避免把全产品库暴露给LLM。",
            object_schema(
                {
                    "product": {"type": "string"},
                    "sample_limit": {"type": "integer", "default": 30},
                },
                ["product"],
            ),
            load_product_context,
        )
    )
    registry.register(
        ToolSpec(
            "search_product_parameters",
            "在指定产品的参数知识库中检索与客户需求相近的功能参数证据。",
            object_schema(
                {
                    "product": {"type": "string"},
                    "requirement_text": {"type": "string"},
                    "requirement_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 5},
                },
                ["product", "requirement_text"],
            ),
            search_product_parameters,
        )
    )
    registry.register(
        ToolSpec(
            "initial_material_assessment",
            "对一组需求只基于目标产品招标参数库做第一阶段核验，并判断是否建议Web/API二次验证。",
            object_schema(
                {
                    "product": {"type": "string"},
                    "requirements": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "requirement_id": {"type": "string"},
                                "text": {"type": "string"},
                            },
                            "required": ["text"],
                        },
                    },
                    "limit": {"type": "integer", "default": 5},
                },
                ["product", "requirements"],
            ),
            initial_material_assessment,
        )
    )
    registry.register(
        ToolSpec(
            "verify_web_readonly",
            "通过产品Web演示环境进行只读页面验证，优先复用CDP连接的本地已登录Chrome。",
            object_schema(
                {
                    "requirement_text": {"type": "string"},
                    "requirement_id": {"type": "string"},
                    "product": {"type": "string", "description": "可选。提供产品名时可自动从配置查找对应 web_url。"},
                    "web_url": {"type": "string"},
                    "cdp_url": {"type": "string"},
                    "browser_state": {"type": "string"},
                },
                ["requirement_text"],
            ),
            verify_web_readonly,
        )
    )
    registry.register(
        ToolSpec(
            "verify_api_readonly",
            "调用只读API确认演示环境可访问性或接口证据。",
            object_schema(
                {
                    "requirement_text": {"type": "string"},
                    "requirement_id": {"type": "string"},
                    "api_base_url": {"type": "string"},
                    "api_token": {"type": "string"},
                },
                ["requirement_text", "api_base_url", "api_token"],
            ),
            verify_api_readonly,
        )
    )
    registry.register(
        ToolSpec(
            "run_compliance_check",
            "运行当前确定性核验工具链，生成Excel符合性矩阵。适合批量Excel核验任务。",
            object_schema(
                {
                    "tender_file": {"type": "string"},
                    "product": {"type": "string"},
                    "output_file": {"type": "string"},
                    "web_url": {"type": "string"},
                    "cdp_url": {"type": "string"},
                    "browser_state": {"type": "string"},
                    "api_base_url": {"type": "string"},
                    "api_token": {"type": "string"},
                },
                ["tender_file", "product", "output_file"],
            ),
            run_compliance_check,
        )
    )
    registry.register(
        ToolSpec(
            "write_compliance_matrix",
            "根据Agent已复核的结构化结果写出Excel符合性矩阵。",
            object_schema(
                {
                    "product": {"type": "string"},
                    "output_file": {"type": "string"},
                    "results": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "结构化符合性结果列表。",
                    },
                },
                ["product", "output_file", "results"],
            ),
            write_compliance_matrix,
        )
    )
    return registry


def tool_result_to_content(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, indent=2)
