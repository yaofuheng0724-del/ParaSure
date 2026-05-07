from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(".paramsure/config.json")


@dataclass
class AgentConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    temperature: float = 0.1
    max_tool_rounds: int = 12

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH) -> "AgentConfig":
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        config = cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})
        config.base_url = os.getenv("PARAMSURE_BASE_URL", config.base_url)
        config.api_key = os.getenv("PARAMSURE_API_KEY", os.getenv("OPENAI_API_KEY", config.api_key))
        config.model = os.getenv("PARAMSURE_MODEL", config.model)
        return config

    def save(self, path: Path = DEFAULT_CONFIG_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def validate_for_llm(self) -> None:
        if not self.api_key:
            raise ValueError("未配置 LLM API Key。请运行 /config set api_key <key> 或设置 PARAMSURE_API_KEY。")
        if not self.base_url:
            raise ValueError("未配置 LLM base_url。")
        if not self.model:
            raise ValueError("未配置 LLM model。")
