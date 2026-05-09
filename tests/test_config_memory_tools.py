from pathlib import Path

from paramsure.config import AgentConfig
from paramsure.memory import SessionMemory
from paramsure.store import ParameterStore
from paramsure.tools import build_default_registry


def test_config_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AgentConfig(base_url="http://example.com/v1", api_key="secret", model="demo-model", temperature=0.2)
    config.save(path)
    loaded = AgentConfig.load(path)
    assert loaded.base_url == "http://example.com/v1"
    assert loaded.api_key == "secret"
    assert loaded.model == "demo-model"
    assert loaded.temperature == 0.2
    assert loaded.product_params_dir == "data/product_params"
    assert loaded.ssl_ca_file() == ""


def test_config_ssl_ca_file_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AgentConfig(ssl={"ca_file": "/tmp/internal-ca.pem"})
    config.save(path)
    loaded = AgentConfig.load(path)
    assert loaded.ssl_ca_file() == "/tmp/internal-ca.pem"


def test_config_ssl_ca_file_env_override(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "config.json"
    AgentConfig(ssl={"ca_file": "/tmp/config-ca.pem"}).save(path)
    monkeypatch.setenv("PARAMSURE_SSL_CA_FILE", "/tmp/env-ca.pem")
    loaded = AgentConfig.load(path)
    assert loaded.ssl_ca_file() == "/tmp/env-ca.pem"


def test_session_memory_writes_jsonl(tmp_path: Path) -> None:
    memory = SessionMemory(root=tmp_path, session_id="demo")
    memory.append("user", {"content": "hello"})
    memory.append("tool_observation", {"tool": "list_products"})
    text = memory.path.read_text(encoding="utf-8")
    assert '"type": "user"' in text
    assert '"type": "tool_observation"' in text
    assert "list_products" in memory.recent_summary()


def test_tool_registry_lists_products(tmp_path: Path) -> None:
    store = ParameterStore(tmp_path / "db.sqlite")
    registry = build_default_registry(store, tmp_path / "artifacts")
    result = registry.call("list_products", {})
    assert result["ok"] is True
    assert "products" in result["result"]
