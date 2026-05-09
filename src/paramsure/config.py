from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path


DEFAULT_CONFIG_PATH = Path(".paramsure/config.json")
DEFAULT_EXAMPLE_CONFIG_PATH = Path("paramsure.example.json")


@dataclass
class AgentConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    temperature: float = 0.1
    max_tool_rounds: int = 12
    product_params_dir: str = "data/product_params"
    chrome: dict[str, str] = field(default_factory=lambda: {"cdp_url": "http://127.0.0.1:9222"})
    ssl: dict[str, str] = field(default_factory=lambda: {"ca_file": ""})
    environments: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = DEFAULT_CONFIG_PATH, initialize: bool = True) -> "AgentConfig":
        if initialize:
            cls.ensure_exists(path)
        data = {}
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        config = cls(**{key: value for key, value in data.items() if key in cls.__dataclass_fields__})
        config.base_url = os.getenv("PARAMSURE_BASE_URL", config.base_url)
        config.api_key = os.getenv("PARAMSURE_API_KEY", os.getenv("OPENAI_API_KEY", config.api_key))
        config.model = os.getenv("PARAMSURE_MODEL", config.model)
        config.ssl = config.ssl if isinstance(config.ssl, dict) else {"ca_file": ""}
        config.ssl.setdefault("ca_file", "")
        config.ssl["ca_file"] = os.getenv("PARAMSURE_SSL_CA_FILE", config.ssl["ca_file"])
        return config

    @classmethod
    def ensure_exists(cls, path: Path = DEFAULT_CONFIG_PATH) -> None:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        if DEFAULT_EXAMPLE_CONFIG_PATH.exists():
            path.write_text(DEFAULT_EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
            return
        cls().save(path)

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

    def product_params_path(self) -> Path:
        return Path(self.product_params_dir)

    def cdp_url(self) -> str:
        return self.chrome.get("cdp_url", "") if isinstance(self.chrome, dict) else ""

    def ssl_ca_file(self) -> str:
        return self.ssl.get("ca_file", "") if isinstance(self.ssl, dict) else ""

    def web_url_for(self, product: str) -> str:
        if not isinstance(self.environments, dict):
            return ""
        env = self.environments.get(product) or {}
        return env.get("web_url", "")
