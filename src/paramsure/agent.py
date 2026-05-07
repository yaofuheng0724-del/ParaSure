from __future__ import annotations

from typing import Any

from .llm import OpenAICompatibleClient
from .memory import SessionMemory
from .prompts import SYSTEM_PROMPT, user_context_prompt
from .store import ParameterStore
from .tools import ToolRegistry, build_default_registry, tool_result_to_content


class AgentRuntime:
    """LLM-driven plan/act/observe/evaluate loop."""

    def __init__(
        self,
        llm: OpenAICompatibleClient,
        store: ParameterStore,
        memory: SessionMemory,
        artifact_dir: Path,
        max_tool_rounds: int = 12,
    ) -> None:
        self.llm = llm
        self.store = store
        self.memory = memory
        self.registry: ToolRegistry = build_default_registry(store, artifact_dir)
        self.max_tool_rounds = max_tool_rounds

    def run_turn(self, user_input: str) -> str:
        self.memory.append("user", {"content": user_input})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": user_context_prompt(self.memory.recent_summary())},
            {"role": "user", "content": user_input},
        ]
        tools = self.registry.schemas()

        for round_index in range(self.max_tool_rounds):
            result = self.llm.chat(messages, tools=tools)
            self.memory.append(
                "assistant",
                {
                    "round": round_index,
                    "content": result.content,
                    "tool_calls": [
                        {"id": call.id, "name": call.name, "arguments": call.arguments} for call in result.tool_calls
                    ],
                },
            )
            if not result.tool_calls:
                final = result.content.strip() or "已完成。"
                self.memory.append("final", {"content": final})
                return final

            assistant_message: dict[str, Any] = {
                "role": "assistant",
                "content": result.content,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": _json_dumps(call.arguments)},
                    }
                    for call in result.tool_calls
                ],
            }
            messages.append(assistant_message)

            for call in result.tool_calls:
                observation = self.registry.call(call.name, call.arguments)
                self.memory.append(
                    "tool_observation",
                    {"id": call.id, "name": call.name, "arguments": call.arguments, "observation": observation},
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": tool_result_to_content(observation),
                    }
                )

        final = "工具调用轮次已达到上限，当前任务未完全完成。请查看会话记忆并缩小任务范围后继续。"
        self.memory.append("final", {"content": final})
        return final


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
