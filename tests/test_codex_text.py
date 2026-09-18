import json
import subprocess
from unittest.mock import Mock

import pytest

from jev_ultrafast import codex_text


def completed(command, *, stdout=""):
    output = command[command.index("--output-last-message") + 1]
    with open(output, "w", encoding="utf-8") as file:
        json.dump({"text": "Zürich"}, file)
    return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="private diagnostics")


def test_field_text_codex_uses_isolated_cli_and_returns_usage(monkeypatch):
    run = Mock(side_effect=lambda command, **_kwargs: completed(
        command,
        stdout='{"type":"turn.completed","usage":{"input_tokens":12,"output_tokens":3}}\n',
    ))
    monkeypatch.setattr(codex_text.subprocess, "run", run)

    text, metadata = codex_text.field_text_codex({"goal": "Fly from Zürich", "page": {"text": "untrusted"}})

    assert text == "Zürich"
    assert metadata["model"] == "default"
    assert metadata["usage"] == {"input_tokens": 12, "output_tokens": 3}
    assert isinstance(metadata["latency_ms"], int)
    command = run.call_args.args[0]
    assert command[:2] == ["codex", "exec"]
    assert command[-1] == "-"
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    disabled = [command[index + 1] for index, value in enumerate(command) if value == "--disable"]
    assert {"shell_tool", "standalone_web_search", "web_search_request", "web_search_cached",
            "apps", "computer_use", "browser_use", "multi_agent", "plugins"} <= set(disabled)
    assert run.call_args.kwargs["input"].endswith(
        'Context JSON:\n{"goal":"Fly from Zürich","page":{"text":"untrusted"}}'
    )
    assert run.call_args.kwargs["timeout"] == codex_text.CODEX_TIMEOUT_SECONDS
    assert run.call_args.kwargs["capture_output"] is True
    assert run.call_args.kwargs["check"] is False


def test_field_text_codex_uses_optional_model(monkeypatch):
    monkeypatch.setenv("CODEX_TEXT_MODEL", "gpt-test")
    run = Mock(side_effect=lambda command, **_kwargs: completed(command))
    monkeypatch.setattr(codex_text.subprocess, "run", run)

    _, metadata = codex_text.field_text_codex({"goal": "Enter Zürich"})

    command = run.call_args.args[0]
    assert command[command.index("--model") + 1] == "gpt-test"
    assert metadata["model"] == "gpt-test"


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "{}",
        '{"text":null}',
        '{"text":""}',
        '{"text":"ok","action":"click"}',
        json.dumps({"text": "x" * 2001}),
    ],
)
def test_field_text_codex_rejects_malformed_output(monkeypatch, payload):
    def respond(command, **_kwargs):
        output = command[command.index("--output-last-message") + 1]
        with open(output, "w", encoding="utf-8") as file:
            file.write(payload)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(codex_text.subprocess, "run", respond)

    with pytest.raises(ValueError, match="no valid field value"):
        codex_text.field_text_codex({"goal": "Enter text"})


def test_field_text_codex_sanitizes_cli_failure(monkeypatch):
    monkeypatch.setattr(
        codex_text.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 1, stdout="secret page", stderr="secret token"),
    )

    with pytest.raises(RuntimeError, match=r"^Codex text helper unavailable; nothing typed\.$") as error:
        codex_text.field_text_codex({"goal": "private"})
    assert "secret" not in str(error.value)


def test_field_text_codex_sanitizes_timeout(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("codex", codex_text.CODEX_TIMEOUT_SECONDS, output="secret page")

    monkeypatch.setattr(codex_text.subprocess, "run", timeout)

    with pytest.raises(RuntimeError, match=r"^Codex text helper unavailable; nothing typed\.$") as error:
        codex_text.field_text_codex({"goal": "private"})
    assert "secret" not in str(error.value)


def test_field_text_codex_sanitizes_missing_cli(monkeypatch):
    monkeypatch.setattr(codex_text.subprocess, "run", Mock(side_effect=FileNotFoundError("private path")))

    with pytest.raises(RuntimeError, match=r"^Codex text helper unavailable; nothing typed\.$"):
        codex_text.field_text_codex({"goal": "private"})
