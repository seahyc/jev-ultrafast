"""Generate field text with an existing Codex CLI login."""

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path

from .questions import TEXT_VALUE

CODEX_TIMEOUT_SECONDS = 45
_INVALID_OUTPUT = "Text helper returned no valid field value; nothing typed."
_UNAVAILABLE = "Codex text helper unavailable; nothing typed."
_SCHEMA = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}


def _usage(stdout):
    """Extract aggregate usage without retaining event or prompt content."""
    usage = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
    return usage


def _validated_text(raw):
    try:
        output = json.loads(raw)
        value = output["text"]
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        raise ValueError(_INVALID_OUTPUT) from None
    return value


def field_text_codex(context):
    """Return schema-validated field text and call metadata from ``codex exec``."""
    model = os.environ.get("CODEX_TEXT_MODEL") or "default"
    prompt = f"{TEXT_VALUE}\n\nContext JSON:\n{json.dumps(context, ensure_ascii=False, separators=(',', ':'))}"
    started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="jev-codex-text-") as directory:
        workdir = Path(directory)
        schema_path = workdir / "schema.json"
        output_path = workdir / "output.json"
        schema_path.write_text(json.dumps(_SCHEMA), encoding="utf-8")
        command = [
            "codex",
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--strict-config",
            "-c", "skills.include_instructions=false",
            "-c", "project_doc_max_bytes=0",
            "-c", 'web_search="disabled"',
            "--sandbox",
            "read-only",
            "--disable",
            "shell_tool",
            "--disable",
            "standalone_web_search",
            "--disable",
            "web_search_request",
            "--disable",
            "web_search_cached",
            "--skip-git-repo-check",
            "--cd",
            str(workdir),
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "--json",
            "--color",
            "never",
        ]
        for feature in (
            "apps", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
            "computer_use", "in_app_browser", "multi_agent", "multi_agent_v2", "plugins",
            "remote_plugin", "hooks", "memories", "image_generation", "view_image",
            "skill_search", "tool_suggest", "code_mode_host", "code_mode", "code_mode_only",
        ):
            command.extend(["--disable", feature])
        if os.environ.get("CODEX_TEXT_MODEL"):
            command.extend(["--model", os.environ["CODEX_TEXT_MODEL"]])
        command.append("-")

        try:
            result = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=CODEX_TIMEOUT_SECONDS,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError(_UNAVAILABLE) from None
        if result.returncode != 0 or not output_path.is_file():
            raise RuntimeError(_UNAVAILABLE)
        try:
            raw = output_path.read_text(encoding="utf-8")
        except OSError:
            raise RuntimeError(_UNAVAILABLE) from None

    return _validated_text(raw), {
        "model": model,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": _usage(result.stdout),
    }
