"""Bounded goal execution with a conservative browse/search action boundary."""

import re
import time
from urllib.parse import urlsplit

from .browser import StalePage
from .model import field_context, field_text

CONSEQUENTIAL = re.compile(
    r"\b(send|submit|post|publish|pay|purchase|buy|book|reserve|delete|remove|unsubscribe|"
    r"save|confirm|approve|accept|agree|sign|login|log in|logout|log out|password|"
    r"message|comment|reply|upload|download|transfer|checkout|place order|cancel|reset)\b", re.I
)
SEARCH_FIELD = re.compile(
    r"\b(search|query|destination|origin|where from|where to|departure|return date|"
    r"check.in|check.out|city|location|filter|sort|adults?|children|guests?|passengers?|"
    r"economy|nonstop|price|category)\b", re.I
)
SEARCH_BUTTON = re.compile(r"^(search(?: .*)?|find(?: .*)?|go|show results|apply filters|"
                           r"next page|previous page|load more)$", re.I)


def origin(url):
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        return None
    port = parts.port or (443 if parts.scheme == "https" else 80)
    return f"{parts.scheme}://{parts.hostname}:{port}"


def approval_reason(action, page, allowed_origins, allowed_controls=()):
    """A conservative automation boundary, not proof that a website has no side effects."""
    if origin(page["url"]) not in allowed_origins:
        return "Page left the authorized origin scope"
    label = action.get("label", "")
    if CONSEQUENTIAL.search(label):
        return "Potentially consequential control; Codex must review scope and obtain required user approval"
    kind, role = action["kind"], action.get("role")
    if kind == "click" and role == "link":
        if not action.get("href"):
            return "Link target is unavailable; origin scope cannot be verified"
        if origin(action["href"]) not in allowed_origins:
            return "Link leaves the authorized origin scope"
    if any(all(action.get(key) == control[key] for key in ("kind", "role", "label")) for control in allowed_controls):
        return None
    if kind in {"wait", "scroll"}:
        return None
    if kind == "fill" and (role == "searchbox" or SEARCH_FIELD.search(label)):
        return None
    if kind == "select" and SEARCH_FIELD.search(label):
        return None
    if kind == "click":
        if role == "link" and action.get("href"):
            return None
        if role in {"textbox", "searchbox", "combobox", "spinbutton"} and SEARCH_FIELD.search(label):
            return None
        if role in {"option", "gridcell", "tab"}:
            return None
        if SEARCH_BUTTON.fullmatch(label.strip()):
            return None
        if role in {"checkbox", "radio"} and SEARCH_FIELD.search(label):
            return None
    return "Control is outside the automatic browse/search policy; return to Codex for review"


def run_goal(
    agent,
    *,
    max_steps=12,
    max_seconds=120,
    max_predictions=None,
    allowed_origins=None,
    allowed_controls=None,
    on_event=None,
):
    """Let Jev select all steps. Codex only supplies TYPE_TEXT; stop at unclear actions."""
    if type(max_steps) is not int or not 1 <= max_steps <= 60:
        raise ValueError("max_steps must be an integer between 1 and 60")
    if type(max_seconds) not in {int, float} or not 1 <= max_seconds <= 600:
        raise ValueError("max_seconds must be between 1 and 600")
    if max_predictions is None:
        max_predictions = max_steps * 2
    if type(max_predictions) is not int or not 1 <= max_predictions <= 120:
        raise ValueError("max_predictions must be an integer between 1 and 120")
    if allowed_controls is None:
        allowed_controls = []
    if not isinstance(allowed_controls, list) or any(
        not isinstance(control, dict)
        or set(control) != {"kind", "role", "label"}
        or any(not isinstance(control[key], str) or not control[key] for key in ("kind", "role", "label"))
        for control in allowed_controls
    ):
        raise ValueError("allowed_controls must be a list of exact non-empty kind, role and label strings")
    scope = {origin(agent.state["page"]["url"]), *(allowed_origins or [])}
    if None in scope:
        raise ValueError("Autonomous browsing requires an explicit HTTP(S) origin")
    started = time.monotonic()
    executed = 0
    initial_history = len(agent.state["history"])
    predictions = 0
    previous = agent.state["history"][-1] if agent.state["history"] else None
    last_executed_action = (
        (previous.get("kind"), previous.get("node"), previous.get("action"))
        if previous and previous.get("kind") not in {"wait", "scroll"} and previous.get("action")
        else None
    )
    emit = on_event or (lambda event: None)

    def stop(status, reason):
        agent.state["status"] = status
        return {"status": status, "reason": reason, "actions_executed": executed,
                "wall_ms": round((time.monotonic() - started) * 1000), "outcome_verified": False}

    def expired():
        return time.monotonic() - started >= max_seconds

    while agent.state["status"] not in {"done", "blocked"}:
        if expired() or executed >= max_steps or predictions >= max_predictions:
            return stop("budget_exhausted", "Action, prediction or wall-time budget reached")
        if origin(agent.state["page"]["url"]) not in scope:
            return stop("needs_review", "Page left the authorized origin scope")
        action = None
        history_before_iteration = len(agent.state["history"])
        try:
            # Refresh first so an external navigation is checked before page content is sent to a model.
            pending_decision = agent.state.get("decision")
            pending_fingerprint = agent.state["page"].get("fingerprint") if pending_decision else None
            agent.state["page"] = agent.browser.observe(screenshot=False)
            if origin(agent.state["page"]["url"]) not in scope:
                return stop("needs_review", "Page left the authorized origin scope")
            if not pending_decision or agent.state["page"].get("fingerprint") != pending_fingerprint:
                agent.state["decision"] = None
                predictions += 1
                agent.command("predict")
            state = agent.state
            decision, page = state["decision"], state["page"]
            if expired():
                return stop("budget_exhausted", "Time budget reached after prediction; no action executed")
            if decision["choice"] not in {"DONE", "BLOCKED"}:
                action = next(a for a in page["actions"] if a["id"] == decision["choice"])
                reason = approval_reason(action, page, scope, allowed_controls)
                if reason:
                    return stop("needs_review", reason)
                signature = tuple(action.get(key) for key in ("kind", "node", "label"))
                if (
                    last_executed_action == signature
                    and action["kind"] not in {"wait", "scroll"}
                    and state["history"]
                    and (
                        state["history"][-1].get("page_changed") is False
                        or (action["kind"] == "click" and any(item.get("invalid") is True for item in page["actions"]))
                    )
                ):
                    return stop("needs_review", "The same control had no visible effect; it was not replayed")
                if action["kind"] == "fill":
                    context = field_context(state["goal"], action, page, state["history"])
                    if not agent.pending_text or agent.pending_text[0] != context:
                        text, metadata = field_text(context)
                        agent.pending_text = (context, text, metadata)
                        state["text_calls"].append({**metadata, "field": action["label"], "value": text})
                        emit({"event": "text_generated", "latency_ms": metadata["latency_ms"],
                              "model": metadata["model"]})
                    if expired():
                        return stop("budget_exhausted", "Time budget reached after text generation; nothing typed")
            before = len(state["history"])
            agent.command("act", {"fingerprint": page["fingerprint"]})
            state["decision"] = None
            executed += len(state["history"]) - before
            if len(state["history"]) > before and decision["choice"] not in {"DONE", "BLOCKED"}:
                last_executed_action = tuple(action.get(key) for key in ("kind", "node", "label"))
            emit({"event": "step", "operation": decision["operation"], "status": state["status"],
                  "actions_executed": executed, "prediction_ms": decision["latency_ms"]})
        except StalePage:
            # Only pre-input stale checks are retriable. Agent logs post-input actions before observation.
            # Count from history so a stale post-action observation cannot escape the budget.
            executed = len(agent.state["history"]) - initial_history
            if len(agent.state["history"]) > history_before_iteration and action is not None:
                last_executed_action = tuple(action.get(key) for key in ("kind", "node", "label"))
            agent.state["decision"] = None
            agent.state["status"] = "ready"
            emit({"event": "stale_page", "action_replayed": False})
    return stop(agent.state["status"], "Jev stopped; independent verification is still required")
