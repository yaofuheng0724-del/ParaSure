import builtins
import sys

from paramsure import cli


def test_read_prompt_falls_back_to_input(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "prompt_toolkit", None)
    monkeypatch.setattr(builtins, "input", lambda prompt_text: f"fallback:{prompt_text}")

    assert cli.read_prompt("paramsure> ") == "fallback:paramsure> "
