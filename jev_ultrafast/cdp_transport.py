"""Jev protocol adapter over the shared chrome-cdp Python client."""

import importlib.util
import os
from pathlib import Path


def _client_type():
    root = Path(os.environ.get("CHROME_CDP_SKILL", Path.home() / ".agents/skills/chrome-cdp"))
    spec = importlib.util.spec_from_file_location("chrome_cdp_client", root / "python/chrome_cdp/__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ChromeCDP


class ChromeCDP:
    def __init__(self, browser=None, *, port=None):
        self.client = _client_type()(browser=browser, port=port, env={"CDP_AGENT_LABEL": "Jev / Codex"})

    def __call__(self, method, session_id=None, **params):
        if method == "Target.createTarget":
            return {"targetId": self.client.new_tab(params["url"])}
        if method == "Jev.resolveTab":
            return {"targetId": self.client.attach(params["tab"])}
        if method == "Target.attachToTarget":
            return {"sessionId": self.client.attach(params["targetId"])}
        if method == "Target.closeTarget":
            return self.client.close_tab(params["targetId"])
        if method == "Jev.release":
            return self.client.release(params["targetId"])
        return self.client.send(session_id, method, **params)

    def close(self):
        self.client.close()
