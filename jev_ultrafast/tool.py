"""Bounded autonomous browser goals, with optional JSON-lines step/recovery control."""

import argparse
import json
import os
import sys

from .agent import Agent
from .autonomous import origin, run_goal
from .demo import load_environment
from .model import field_context, field_text


def _token_count(usage, *names):
    for name in names:
        value = usage.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return value
    return 0


def _usage_summary(state):
    decisions = state.get("decisions", [])
    text_calls = state.get("text_calls", [])

    def aggregate(calls, input_names, output_names):
        return {
            "calls": len(calls),
            "input_tokens": sum(_token_count(call.get("usage", {}), *input_names) for call in calls),
            "output_tokens": sum(_token_count(call.get("usage", {}), *output_names) for call in calls),
            "latency_ms": sum(call.get("latency_ms", 0) for call in calls),
        }

    return {
        "jev": aggregate(decisions, ("input_tokens",), ("output_tokens",)),
        "text_model": aggregate(
            text_calls,
            ("input_tokens", "prompt_tokens"),
            ("output_tokens", "completion_tokens"),
        ),
    }


def summary(agent, *, verbose=False):
    state = agent.snapshot()
    page = state["page"]
    decision = state["decision"]
    selected_action = None
    if decision:
        selected_action = next((action for action in page["actions"] if action["id"] == decision["choice"]), None)

    result = {
        "status": state["status"], "tab": agent.browser.target,
        "url": page["url"], "title": page["title"], "text": page["text"][:6000],
        "fingerprint": page["fingerprint"],
        "selected_action": selected_action,
        "decision": {k: decision.get(k) for k in ("choice", "operation", "confidence", "usage", "latency_ms")}
        if decision else None,
        "last_action": state["history"][-1] if state["history"] else None,
        "usage": _usage_summary(state),
        "elapsed_ms": state["elapsed_ms"],
        "outcome_verified": False,
    }
    if verbose:
        result.update(
            elements=state["elements"],
            actions=page["actions"],
            decision={k: v for k, v in decision.items() if k not in {"request", "raw_answers"}}
            if decision else None,
        )
    return result


def handle(agent, request, on_event=None):
    command = request.get("command")
    verbose = request.get("verbose") is True
    if command == "observe":
        agent.state["decision"] = None
        agent.state["page"] = agent.browser.observe(screenshot=False)
    elif command == "predict":
        agent.command("predict")
    elif command == "text":
        state = agent.state
        decision = state["decision"]
        if not decision or decision["operation"] != "TYPE_TEXT":
            raise ValueError("Predict a TYPE_TEXT action before requesting text")
        action = next(a for a in state["page"]["actions"] if a["id"] == decision["choice"])
        context = field_context(state["goal"], action, state["page"], state["history"])
        text, metadata = field_text(context)
        agent.pending_text = (context, text, metadata)
        state["text_calls"].append({**metadata, "field": action["label"], "value": text})
        return {"text": text, "field": action["label"], "metadata": metadata}
    elif command == "act":
        agent.command("act", {"fingerprint": request.get("fingerprint")})
    elif command == "run":
        try:
            result = run_goal(
                agent, max_steps=request.get("max_steps", 12), max_seconds=request.get("max_seconds", 120),
                allowed_origins=[origin(url) for url in request["allowed_origins"]]
                if request.get("allowed_origins") else None,
                allowed_controls=request.get("allowed_controls"),
                max_predictions=request.get("max_predictions"),
                on_event=on_event,
            )
        except Exception as error:
            agent.state["status"] = "error"
            result = {"status": "error", "error": str(error), "inspect_before_retry": True}
        return {**summary(agent, verbose=verbose), **result}
    else:
        raise ValueError("Use run, observe, predict, text, act or close")
    return summary(agent, verbose=verbose)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    browser = parser.add_mutually_exclusive_group(required=True)
    browser.add_argument("--browser", help="Explicit chrome-cdp browser name, e.g. dia")
    browser.add_argument("--port", type=int, help="Explicit local or SSH-forwarded CDP port")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Open a new owned background tab")
    source.add_argument("--tab", help="Attach to an existing tab; preserve its URL and leave it open on exit")
    parser.add_argument("--goal", required=True)
    parser.add_argument("--keep-open", action="store_true", help="Retain an owned tab when the tool exits")
    parser.add_argument("--run", action="store_true", help="Execute a bounded browse/search goal and return JSON")
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--max-seconds", type=float, default=120)
    parser.add_argument("--max-predictions", type=int, help="Limit Jev predictions, including detours")
    parser.add_argument("--allow-control", action="append", type=json.loads,
                        help='Authorized exact control JSON: {"kind":"click","role":"button","label":"Next"}')
    parser.add_argument("--allow-origin", action="append", help="Authorized HTTP(S) origin; repeat for several")
    parser.add_argument("--verbose", action="store_true", help="Include full element, action and decision details")
    args = parser.parse_args()
    load_environment()
    os.environ.setdefault("TEXT_MODEL_PROVIDER", "codex")
    try:
        with Agent(args.url, args.goal, browser=args.browser, port=args.port, tab=args.tab,
                   keep_open=args.keep_open or args.run) as agent:
            def emit(event):
                print(json.dumps(event), flush=True)
            if args.run:
                result = handle(agent, {"command": "run", "max_steps": args.max_steps,
                                       "max_seconds": args.max_seconds, "allowed_origins": args.allow_origin,
                                       "allowed_controls": args.allow_control, "max_predictions": args.max_predictions,
                                       "verbose": args.verbose}, emit)
                emit(result)
                return 0 if result["status"] == "done" else 2
            print(json.dumps(summary(agent, verbose=args.verbose)), flush=True)
            for line in sys.stdin:
                try:
                    request = json.loads(line)
                    if not isinstance(request, dict):
                        raise ValueError("Expected a JSON object")
                    if request.get("command") == "close":
                        break
                    request.setdefault("verbose", args.verbose)
                    print(json.dumps(handle(agent, request, emit)), flush=True)
                except Exception as error:
                    print(json.dumps({"error": str(error), "inspect_before_retry": True}), flush=True)
    except Exception as error:
        print(json.dumps({"error": str(error)}), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
