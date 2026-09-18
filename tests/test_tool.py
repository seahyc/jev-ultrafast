"""Offline tool contracts; no model calls or real browser required."""
from unittest.mock import Mock

import pytest

from jev_ultrafast import model, tool
from jev_ultrafast.browser import Browser


def summary_agent():
    decision = {
        "choice": "e1",
        "operation": "CLICK",
        "target": "1",
        "confidence": 0.8,
        "probabilities": {"e1": 0.8, "e2": 0.2},
        "operation_probabilities": {"CLICK": 0.8, "WAIT": 0.2},
        "target_probabilities": {"1": 0.8, "2": 0.2},
        "usage": {"input_tokens": 100, "output_tokens": 7},
        "latency_ms": 25,
        "request": {"secret-sized": "payload"},
        "raw_answers": {"operation": "payload"},
    }
    actions = [
        {"id": "e1", "kind": "click", "label": "Search", "role": "button", "node": 10},
        {"id": "e2", "kind": "click", "label": "Other", "role": "button", "node": 11},
    ]
    state = {
        "status": "predicted",
        "page": {
            "url": "https://example.test/",
            "title": "Example",
            "text": "x" * 7000,
            "fingerprint": "page-fingerprint",
            "actions": actions,
        },
        "elements": [{"index": "1", "label": "Search"}],
        "decision": decision,
        "decisions": [
            decision,
            {"usage": {"input_tokens": 40, "output_tokens": 3}, "latency_ms": 15},
        ],
        "text_calls": [
            {
                "model": "text-a",
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
                "latency_ms": 30,
            },
            {
                "model": "text-b",
                "usage": {"input_tokens": 8, "output_tokens": 2},
                "latency_ms": 20,
            },
        ],
        "history": [{"step": 1, "action": "Previous", "usage": {"input_tokens": 9}}],
        "elapsed_ms": 123,
    }
    agent = Mock()
    agent.snapshot.return_value = state
    agent.browser.target = "tab-1"
    return agent, state


def test_tool_rejects_unknown_command():
    agent = Mock()
    with pytest.raises(ValueError, match="Use run"):
        tool.handle(agent, {"command": "tick"})
    agent.command.assert_not_called()


def test_explicit_act_passes_callers_fingerprint(monkeypatch):
    agent = Mock()
    monkeypatch.setattr(tool, "summary", lambda _agent, **_kwargs: {})
    tool.handle(agent, {"command": "act", "fingerprint": "reviewed-page"})
    agent.command.assert_called_once_with("act", {"fingerprint": "reviewed-page"})


def test_default_summary_is_compact_but_keeps_action_and_aggregate_usage():
    agent, state = summary_agent()

    result = tool.summary(agent)

    assert result["fingerprint"] == "page-fingerprint"
    assert result["url"] == "https://example.test/"
    assert result["title"] == "Example"
    assert result["status"] == "predicted"
    assert len(result["text"]) == 6000
    assert result["selected_action"] == state["page"]["actions"][0]
    assert result["decision"] == {
        "choice": "e1",
        "operation": "CLICK",
        "confidence": 0.8,
        "usage": {"input_tokens": 100, "output_tokens": 7},
        "latency_ms": 25,
    }
    assert "probabilities" not in result["decision"]
    assert "elements" not in result
    assert "actions" not in result
    assert result["last_action"] == state["history"][-1]
    assert result["usage"] == {
        "jev": {"calls": 2, "input_tokens": 140, "output_tokens": 10, "latency_ms": 40},
        "text_model": {"calls": 2, "input_tokens": 20, "output_tokens": 6, "latency_ms": 50},
    }


def test_verbose_summary_preserves_full_old_payload():
    agent, state = summary_agent()

    result = tool.summary(agent, verbose=True)

    assert result["elements"] == state["elements"]
    assert result["actions"] == state["page"]["actions"]
    assert result["decision"] == {
        key: value for key, value in state["decision"].items() if key not in {"request", "raw_answers"}
    }
    assert result["decision"]["probabilities"] == {"e1": 0.8, "e2": 0.2}


def test_json_verbose_request_controls_handle_summary(monkeypatch):
    agent, state = summary_agent()
    agent.state = state
    agent.browser.observe.return_value = state["page"]

    compact = tool.handle(agent, {"command": "observe"})
    verbose = tool.handle(agent, {"command": "observe", "verbose": True})

    assert "actions" not in compact
    assert verbose["actions"] == state["page"]["actions"]


def test_codex_provider_does_not_need_text_api_key(monkeypatch):
    import jev_ultrafast.codex_text as helper
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "codex")
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    generate = Mock(return_value=("London", {}))
    monkeypatch.setattr(helper, "field_text_codex", generate)
    assert model.field_text({"goal": "London"}) == ("London", {})


def test_attach_does_not_navigate_resize_or_close_users_tab(monkeypatch):
    import jev_ultrafast.cdp_transport as transport
    wire = Mock(side_effect=[{"targetId": "existing"}, {"sessionId": "existing"}, {}])
    monkeypatch.setattr(transport, "ChromeCDP", Mock(return_value=wire))
    browser = Browser(None, browser="dia", tab="existing")
    browser.close()
    assert [call.args[0] for call in wire.call_args_list] == [
        "Jev.resolveTab", "Target.attachToTarget", "Jev.release",
    ]
    wire.close.assert_called_once()


def test_unknown_provider_stops(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_PROVIDER", "typo")
    with pytest.raises(ValueError, match="Unknown TEXT_MODEL_PROVIDER"):
        model.field_text({})
