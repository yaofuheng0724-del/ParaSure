import builtins
import json
import sys
from pathlib import Path

from paramsure import cli
from paramsure.config import AgentConfig


def test_read_prompt_falls_back_to_input(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "prompt_toolkit", None)
    monkeypatch.setattr(builtins, "input", lambda prompt_text: f"fallback:{prompt_text}")

    assert cli.read_prompt("paramsure> ") == "fallback:paramsure> "


def test_doctor_command_reports_core_statuses(tmp_path: Path, capsys) -> None:
    params_dir = tmp_path / "params"
    params_dir.mkdir()
    artifacts_dir = tmp_path / "artifacts"
    config_path = tmp_path / "config.json"
    AgentConfig(
        api_key="secret",
        product_params_dir=str(params_dir),
    ).save(config_path)

    rc = cli.main([
        "--config",
        str(config_path),
        "doctor",
        "--artifacts-dir",
        str(artifacts_dir),
    ])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ParaSure Doctor" in out
    assert "Python:" in out
    assert "LLM config:" in out
    assert "Product params:" in out
    assert "Evidence dir:" in out


def test_evidence_summary_command_counts_sessions_and_artifacts(tmp_path: Path, capsys) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "demo.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "payload": {"content": "secret text"}}),
                json.dumps({"type": "tool_observation", "payload": {"name": "list_products"}}),
                json.dumps({"type": "tool_observation", "payload": {"name": "verify_web_readonly", "observation": {"ok": False, "error": "boom"}}}),
                json.dumps({"type": "final", "payload": {"content": "done"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts" / "REQ-1"
    artifacts.mkdir(parents=True)
    (artifacts / "evidence.json").write_text(
        json.dumps({"requirement_id": "REQ-1", "failed_reason": "", "keyword_matches": ["sso"]}),
        encoding="utf-8",
    )
    (artifacts / "screenshot.png").write_bytes(b"png")

    rc = cli.main([
        "evidence",
        "summary",
        "--sessions-dir",
        str(sessions),
        "--artifacts-dir",
        str(tmp_path / "artifacts"),
    ])

    out = capsys.readouterr().out
    assert rc == 0
    assert "ParaSure Evidence Summary" in out
    assert "Sessions: 1" in out
    assert "Tool observations: 2" in out
    assert "Tool failures: 1" in out
    assert "Evidence bundles: 1" in out
    assert "Screenshots: 1" in out
    assert "secret text" not in out
