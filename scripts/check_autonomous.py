"""Opt-in live integration: temporary local pages in Dia; uses paid model calls."""

import argparse
import json
import os
import subprocess
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from jev_ultrafast.browser import Browser

SEARCH = """<title>Jev search fixture</title>
<label>Destination<input id="city"></label>
<button onclick="document.getElementById('result').textContent='Results for '+document.getElementById('city').value">
Search</button><p id="result"></p>"""
REVIEW = """<title>Jev approval fixture</title><p>Draft is ready. Recipient: test fixture.</p>
<button onclick="document.title='SENT';window.sent=true">Send</button>"""
DRAFT = """<title>Jev draft fixture</title><p id="step">Draft step 1 of 2; fields complete.</p>
<button onclick="window.draftStage=(window.draftStage||1)+1;
document.getElementById('step').textContent=window.draftStage===2?
'Draft step 2 of 2; fields complete.':'Draft complete';
if(window.draftStage===3)this.remove()">Next</button>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(({"/review": REVIEW, "/draft": DRAFT}.get(self.path, SEARCH)).encode())

    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-models", action="store_true", required=True)
    parser.add_argument("--case", choices=["/", "/review", "/draft"], help="Run one fixture only")
    args = parser.parse_args()
    assert args.live_models
    os.environ["CDP_AGENT_ID"] = "jev-live-check-" + uuid.uuid4().hex
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cases = [
            ("/", "Search for London and stop when Results for London is visible.", "done",
             "document.getElementById('result').textContent", "Results for London"),
            ("/review", "Send the prepared draft using the Send button.", "needs_review",
             "Boolean(window.sent)", False),
            ("/draft", "Complete the draft steps and stop when Draft complete is visible.", "done",
             "document.getElementById('step').textContent", "Draft complete"),
        ]
        for route, goal, status, expression, expected in cases:
            if args.case and route != args.case:
                continue
            url = f"http://127.0.0.1:{server.server_port}{route}"
            result = subprocess.run(
                [sys.executable, "-m", "jev_ultrafast.tool", "--browser", "dia", "--url", url,
                 "--goal", goal, "--run", "--max-steps", "6", "--max-seconds", "60",
                 "--max-predictions", "6",
                 *(["--allow-control", json.dumps({"kind": "click", "role": "button", "label": "Next"})]
                   if route == "/draft" else [])],
                capture_output=True, text=True, timeout=90,
            )
            rows = [json.loads(line) for line in result.stdout.splitlines()]
            if not rows or "tab" not in rows[-1]:
                raise RuntimeError(f"Tool failed with exit {result.returncode}")
            final = rows[-1]
            observer = Browser(None, browser="dia", tab=final["tab"])
            try:
                assert final["status"] == status, final.get("reason", final["status"])
                assert observer.evaluate(expression) == expected
                if route == "/draft":
                    assert observer.evaluate("window.draftStage") == 3
                    assert final["actions_executed"] == 2
                print(json.dumps({"case": route, "status": status,
                                  "actions": final["actions_executed"], "wall_ms": final["wall_ms"],
                                  "events": [row for row in rows if "event" in row],
                                  "usage": final["usage"],
                                  "independent_verification": "passed"}), flush=True)
            finally:
                observer.owned = True  # Only this script's freshly-created fixture tab.
                observer.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
