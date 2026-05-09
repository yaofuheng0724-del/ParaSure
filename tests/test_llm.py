import json
import urllib.error

import pytest

from paramsure.config import AgentConfig
from paramsure.llm import OpenAICompatibleClient


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")


def test_llm_uses_custom_ca_file(tmp_path, monkeypatch) -> None:
    ca_file = tmp_path / "internal-ca.pem"
    ca_file.write_text("demo", encoding="utf-8")
    captured = {}

    def fake_create_default_context(*, cafile):
        captured["cafile"] = cafile
        return "ssl-context"

    def fake_urlopen(req, timeout, context):
        captured["timeout"] = timeout
        captured["context"] = context
        return _FakeResponse()

    monkeypatch.setattr("paramsure.llm.ssl.create_default_context", fake_create_default_context)
    monkeypatch.setattr("paramsure.llm.urllib.request.urlopen", fake_urlopen)

    config = AgentConfig(base_url="https://example.com/v1", api_key="secret", ssl={"ca_file": str(ca_file)})
    result = OpenAICompatibleClient(config).chat([{"role": "user", "content": "hi"}])

    assert result.content == "ok"
    assert captured["cafile"] == str(ca_file)
    assert captured["context"] == "ssl-context"
    assert captured["timeout"] == 60


def test_llm_missing_ca_file_fails_before_request(tmp_path, monkeypatch) -> None:
    called = False

    def fake_urlopen(*args, **kwargs):
        nonlocal called
        called = True

    missing = tmp_path / "missing.pem"
    config = AgentConfig(base_url="https://example.com/v1", api_key="secret", ssl={"ca_file": str(missing)})

    monkeypatch.setattr("paramsure.llm.urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="LLM SSL CA 证书文件不存在"):
        OpenAICompatibleClient(config).chat([{"role": "user", "content": "hi"}])
    assert called is False


def test_llm_certificate_error_mentions_ca_config(monkeypatch) -> None:
    def fake_urlopen(*args, **kwargs):
        raise urllib.error.URLError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    config = AgentConfig(base_url="https://example.com/v1", api_key="secret")
    monkeypatch.setattr("paramsure.llm.urllib.request.urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="ssl.ca_file"):
        OpenAICompatibleClient(config).chat([{"role": "user", "content": "hi"}])
