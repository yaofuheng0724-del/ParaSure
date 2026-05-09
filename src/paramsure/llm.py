from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import AgentConfig


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResult:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw_message: dict[str, Any] = field(default_factory=dict)


class OpenAICompatibleClient:
    def __init__(self, config: AgentConfig):
        config.validate_for_llm()
        self.config = config

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> LLMResult:
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60, context=self._ssl_context()) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM 请求失败: HTTP {exc.code}: {body[:1000]}") from exc
        except urllib.error.URLError as exc:
            if _is_certificate_error(exc):
                raise RuntimeError(
                    "LLM 请求失败: SSL 证书校验失败。"
                    "如果使用内网 HTTPS 网关，请运行 "
                    "`./paramsure config set ssl.ca_file /path/to/internal-ca.pem` "
                    "或设置 PARAMSURE_SSL_CA_FILE 指向可信 CA 证书。"
                ) from exc
            raise RuntimeError(f"LLM 请求失败: {exc}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"LLM 响应缺少 choices: {data}")
        message = choices[0].get("message") or {}
        return LLMResult(
            content=message.get("content") or "",
            tool_calls=self._parse_tool_calls(message),
            raw_message=message,
        )

    def _ssl_context(self) -> ssl.SSLContext | None:
        ca_file = self.config.ssl_ca_file()
        if not ca_file:
            return None
        path = Path(ca_file).expanduser()
        if not path.is_file():
            raise RuntimeError(f"LLM SSL CA 证书文件不存在: {path}")
        return ssl.create_default_context(cafile=str(path))

    @staticmethod
    def _parse_tool_calls(message: dict[str, Any]) -> list[ToolCall]:
        calls: list[ToolCall] = []
        for item in message.get("tool_calls") or []:
            function = item.get("function") or {}
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            calls.append(
                ToolCall(
                    id=item.get("id") or function.get("name") or "tool_call",
                    name=function.get("name") or "",
                    arguments=args,
                )
            )
        return calls


def _is_certificate_error(exc: urllib.error.URLError) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return True
    if isinstance(reason, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(reason):
        return True
    return "CERTIFICATE_VERIFY_FAILED" in str(exc)
