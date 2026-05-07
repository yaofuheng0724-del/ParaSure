from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .excel_io import load_tender_requirements, write_results
from .models import ComplianceResult, EvidenceSource, TenderRequirement, Verdict, VerificationConfig
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


def build_default_registry(store: ParameterStore, artifact_dir: Path) -> ToolRegistry:
    registry = ToolRegistry()

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

    def verify_web_readonly(args: dict[str, Any]) -> dict[str, Any]:
        config = VerificationConfig(
            enabled=True,
            cdp_url=args.get("cdp_url", ""),
            browser_state=Path(args["browser_state"]) if args.get("browser_state") else None,
            base_url=args["web_url"],
        )
        requirement = TenderRequirement(
            requirement_id=str(args.get("requirement_id", "manual")),
            title="",
            description=args["requirement_text"],
        )
        outcome = WebVerifier(config, artifact_dir).verify(requirement)
        return {
            "confirmed": outcome.confirmed,
            "confidence": outcome.confidence,
            "summary": outcome.summary,
            "artifact": outcome.artifact,
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
            "verify_web_readonly",
            "通过产品Web演示环境进行只读页面验证，优先复用CDP连接的本地已登录Chrome。",
            object_schema(
                {
                    "requirement_text": {"type": "string"},
                    "requirement_id": {"type": "string"},
                    "web_url": {"type": "string"},
                    "cdp_url": {"type": "string"},
                    "browser_state": {"type": "string"},
                },
                ["requirement_text", "web_url"],
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
