"""Offline autonomous policy/budget contracts. No model calls."""
from unittest.mock import Mock

import pytest

from jev_ultrafast import autonomous as auto

PAGE = {"url": "http://127.0.0.1:8888/", "fingerprint": "page", "actions": []}
SCOPE = {auto.origin(PAGE["url"])}


@pytest.mark.parametrize("label", ["Send", "Submit", "Pay now", "Delete account", "Confirm", "Continue"])
def test_consequential_or_unclear_action_pauses(label):
    assert auto.approval_reason({"kind": "click", "role": "button", "label": label}, PAGE, SCOPE)


def test_read_only_navigation_is_origin_bounded():
    action = {"kind": "click", "role": "link", "label": "Article", "href": "http://127.0.0.1:8888/article"}
    assert auto.approval_reason(action, PAGE, SCOPE) is None
    action["href"] = "https://outside.test/"
    assert "scope" in auto.approval_reason(action, PAGE, SCOPE)


def test_allowed_control_requires_exact_kind_role_and_label():
    action = {"kind": "click", "role": "button", "label": "Next"}
    allowed = [{"kind": "click", "role": "button", "label": "Next"}]
    assert auto.approval_reason(action, PAGE, SCOPE, allowed) is None
    for key, wrong in [("kind", "fill"), ("role", "link"), ("label", "Previous")]:
        changed = {**allowed[0], key: wrong}
        assert auto.approval_reason(action, PAGE, SCOPE, [changed])


def test_allowed_control_cannot_override_consequential_or_origin_rules():
    send = {"kind": "click", "role": "button", "label": "Send"}
    assert auto.approval_reason(send, PAGE, SCOPE, [send])
    link = {"kind": "click", "role": "link", "label": "Next", "href": "https://outside.test/"}
    allowed = [{key: link[key] for key in ("kind", "role", "label")}]
    assert "scope" in auto.approval_reason(link, PAGE, SCOPE, allowed)
    link.pop("href")
    assert "cannot be verified" in auto.approval_reason(link, PAGE, SCOPE, allowed)


def test_action_budget_ends_autonomous_loop(monkeypatch):
    agent = Mock()
    agent.state = {"status": "ready", "page": PAGE.copy(), "history": []}
    agent.browser.observe.return_value = PAGE
    def command(name, *_args):
        if name == "predict":
            agent.state["decision"] = {"choice": "wait", "operation": "WAIT", "latency_ms": 0}
            agent.state["page"] = {**PAGE, "actions": [{"id": "wait", "kind": "wait"}]}
        else:
            agent.state["history"].append({"kind": "wait"})
    agent.command.side_effect = command
    result = auto.run_goal(agent, max_steps=2)
    assert result["status"] == "budget_exhausted"
    assert result["actions_executed"] == 2
    assert agent.command.call_count == 4


def test_pause_occurs_before_execution_or_text_generation(monkeypatch):
    action = {"id": "send", "kind": "click", "role": "button", "label": "Send"}
    page = {**PAGE, "actions": [action]}
    agent = Mock()
    agent.state = {"status": "ready", "page": page, "history": []}
    agent.browser.observe.return_value = page
    def command(name):
        assert name == "predict"
        agent.state["decision"] = {"choice": "send", "operation": "CLICK"}
    agent.command.side_effect = command
    generate = Mock()
    monkeypatch.setattr(auto, "field_text", generate)
    result = auto.run_goal(agent)
    assert result["status"] == "needs_review"
    agent.command.assert_called_once_with("predict")
    generate.assert_not_called()


def test_budget_rejects_nan_and_unbounded_values():
    for value in [float("nan"), float("inf"), 0, 601]:
        with pytest.raises(ValueError):
            auto.run_goal(Mock(), max_seconds=value)


@pytest.mark.parametrize(
    "controls",
    [
        {},
        [{"kind": "click", "role": "button"}],
        [{"kind": "click", "role": "button", "label": ""}],
        [{"kind": "click", "role": "button", "label": "Next", "extra": "no"}],
    ],
)
def test_allowed_controls_validation(controls):
    with pytest.raises(ValueError, match="allowed_controls"):
        auto.run_goal(Mock(), allowed_controls=controls)


@pytest.mark.parametrize("value", [True, 0, 121, 1.5])
def test_prediction_budget_validation(value):
    with pytest.raises(ValueError, match="max_predictions"):
        auto.run_goal(Mock(), max_predictions=value)


def test_stale_page_does_not_double_count_predictions():
    action = {"id": "wait", "kind": "wait", "role": "none", "label": "Wait"}
    page = {**PAGE, "actions": [action]}
    agent = Mock()
    agent.state = {"status": "ready", "page": page, "history": []}
    agent.browser.observe.return_value = page
    predictions = 0

    def command(name, *_args):
        nonlocal predictions
        if name == "predict":
            predictions += 1
            agent.state["decision"] = {"choice": "wait", "operation": "WAIT", "latency_ms": 0}
            if predictions == 1:
                raise auto.StalePage("changed")
        else:
            agent.state["history"].append({"kind": "wait", "page_changed": False})

    agent.command.side_effect = command
    result = auto.run_goal(agent, max_steps=1, max_predictions=2)
    assert result["status"] == "budget_exhausted"
    assert predictions == 2
    assert result["actions_executed"] == 1


def test_no_action_runs_after_prediction_budget_is_used():
    agent = Mock()
    agent.state = {"status": "ready", "page": PAGE.copy(), "history": []}
    agent.browser.observe.return_value = PAGE
    agent.command.side_effect = auto.StalePage("changed")

    result = auto.run_goal(agent, max_predictions=1)

    assert result["status"] == "budget_exhausted"
    agent.command.assert_called_once_with("predict")


@pytest.mark.parametrize(
    "page_changed, invalid, expected_acts",
    [(False, False, 1), (True, False, 2), (True, True, 1)],
)
def test_identical_no_effect_or_validation_action_is_not_replayed(page_changed, invalid, expected_acts):
    action = {"id": "next", "kind": "click", "role": "button", "label": "Next", "node": 7}
    invalid_field = {"id": "field", "kind": "fill", "role": "textbox", "label": "Name", "invalid": invalid}
    page = {**PAGE, "actions": [action, invalid_field]}
    agent = Mock()
    agent.state = {"status": "ready", "page": page, "history": []}
    agent.browser.observe.return_value = page
    acts = 0

    def command(name, *_args):
        nonlocal acts
        if name == "predict":
            agent.state["decision"] = {"choice": "next", "operation": "CLICK", "latency_ms": 0}
        else:
            acts += 1
            agent.state["history"].append({"kind": "click", "page_changed": page_changed})

    agent.command.side_effect = command
    result = auto.run_goal(
        agent,
        max_steps=2,
        allowed_controls=[{"kind": "click", "role": "button", "label": "Next"}],
    )
    assert acts == expected_acts
    assert result["status"] == ("needs_review" if expected_acts == 1 else "budget_exhausted")


def test_invalid_page_does_not_block_changed_fill_retry():
    action = {"id": "name", "kind": "fill", "role": "textbox", "label": "Name", "node": 7, "invalid": True}
    page = {**PAGE, "title": "Form", "text": "Name is required", "actions": [action]}
    agent = Mock()
    agent.pending_text = None
    agent.state = {"status": "ready", "page": page, "history": [], "goal": "Enter Pat", "text_calls": []}
    agent.browser.observe.return_value = page
    acts = 0

    def command(name, *_args):
        nonlocal acts
        if name == "predict":
            agent.state["decision"] = {"choice": "name", "operation": "TYPE_TEXT", "latency_ms": 0}
        else:
            acts += 1
            agent.state["history"].append({"kind": "fill", "page_changed": True})

    agent.command.side_effect = command
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(auto, "field_text", lambda _context: ("Pat", {"model": "fake", "latency_ms": 0}))
        result = auto.run_goal(
            agent,
            max_steps=2,
            allowed_controls=[{"kind": "fill", "role": "textbox", "label": "Name"}],
        )
    assert acts == 2
    assert result["status"] == "budget_exhausted"


def test_replay_guard_uses_previous_run_history():
    action = {"id": "next", "kind": "click", "role": "button", "label": "Next", "node": 7}
    page = {**PAGE, "actions": [action]}
    agent = Mock()
    agent.state = {
        "status": "needs_review",
        "page": page,
        "decision": None,
        "history": [{"kind": "click", "node": 7, "action": "Next", "page_changed": False}],
    }
    agent.browser.observe.return_value = page

    def command(name, *_args):
        assert name == "predict"
        agent.state["decision"] = {"choice": "next", "operation": "CLICK", "latency_ms": 0}

    agent.command.side_effect = command
    result = auto.run_goal(
        agent,
        allowed_controls=[{"kind": "click", "role": "button", "label": "Next"}],
    )
    assert result["status"] == "needs_review"
    agent.command.assert_called_once_with("predict")


@pytest.mark.parametrize("changed, expected_predictions", [(False, 1), (True, 2)])
def test_resume_reuses_pending_decision_only_for_same_fingerprint(changed, expected_predictions):
    action = {"id": "next", "kind": "click", "role": "button", "label": "Next", "node": 7}
    first_page = {**PAGE, "fingerprint": "first", "actions": [action]}
    refreshed = {**first_page, "fingerprint": "changed" if changed else "first"}
    agent = Mock()
    agent.state = {"status": "ready", "page": first_page, "history": []}
    agent.browser.observe.side_effect = [first_page, refreshed]
    predictions = 0

    def command(name, *_args):
        nonlocal predictions
        if name == "predict":
            predictions += 1
            agent.state["decision"] = {"choice": "next", "operation": "CLICK", "latency_ms": 0}
        else:
            agent.state["history"].append({"kind": "click", "page_changed": True})

    agent.command.side_effect = command
    paused = auto.run_goal(agent)
    assert paused["status"] == "needs_review"
    resumed = auto.run_goal(
        agent,
        max_steps=1,
        allowed_controls=[{"kind": "click", "role": "button", "label": "Next"}],
    )
    assert resumed["status"] == "budget_exhausted"
    assert predictions == expected_predictions
