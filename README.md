<img src="docs/banner.svg" alt="Jev Ultrafast · Browser Use × TypeSafe" width="100%" />

# Jev Ultrafast ⚡

**A browser agent with a dynamic, indexed action space.**

Give it one goal. [TypeSafe's Jev](https://docs.typesafe.ai/introduction) picks an operation and an element. A small LLM writes text only when the operation is `TYPE_TEXT`.

**Zürich → London on Google Flights in 7.1 seconds.** One natural-language goal, actual text generation, and loading waits included.

<a href="docs/demo.mp4"><img src="docs/demo.gif" alt="A real Google Flights search at 1× speed, with generated city names and dynamic operation/target decisions" width="100%" /></a>

[Watch the MP4](docs/demo.mp4) · [Measurements](docs/performance.md) · [Read the loop](jev_ultrafast/agent.py)

## The action space

Every observation produces a new element table:

```text
[1] button    Change ticket type · Round trip
[2] combobox  Where from?        · San Francisco
[3] combobox  Where to?          · empty
[4] textbox   Departure          · empty
...
```

The operations are `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`, `DONE`, and `BLOCKED`. Only supported operations and targets are offered.

```text
                      one TypeSafe request
                     ┌───────────────────────────┐
page → element table → operation                 │
                     │ click_target              │
                     │ type_text_target          │
                     │ select_target, if present │
                     └─────────────┬─────────────┘
                         use the matching target
                                   │
                    CLICK [7] ─────┤──→ browser
                TYPE_TEXT [3] ─────┘
                          ↓
                   small LLM → text → browser
```

Target questions are speculative. If the operation is `CLICK`, only `click_target` can execute. Two decisions, **one network round trip**. Each target head contains only compatible elements. Native dropdown choices carry an observed element/option index.

There are no site-specific action scripts or prepared field strings in the policy. The Flights example supplies a goal and independently verifies the outcome. The screenshot renderer adds labels afterward; it does not drive the browser.

## Try it

```bash
git clone https://github.com/browser-use/jev-ultrafast.git
cd jev-ultrafast
uv sync
cp .env.example .env
# Add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY.
uv run jev
```

Open **http://127.0.0.1:8766** and click **Start demo → Run automatically**. The inspector shows numbered elements, operation probabilities, target probabilities, and executed actions. **Choose next** pauses before execution.

Chrome connects through [Browser Harness](https://github.com/browser-use/browser-harness), installed by `uv sync`. Run `uv run browser-harness --doctor` if it needs connecting. Allow remote debugging in Chrome when prompted.

`TEXT_MODEL_API_KEY` is an OpenRouter key in the example configuration. The current demo uses `inception/mercury-2.5` with reasoning disabled. Gemini, GLM, and DeepSeek can also use the OpenAI-compatible text helper; configure the appropriate model, endpoint, and reasoning setting.

## Use the library

```python
from jev_ultrafast import Agent

with Agent(
    "https://www.google.com/travel/flights?hl=en",
    "Find one-way flights from Zurich to London on September 20, 2026, "
    "for one adult in economy. Stop when matching flight options are visible.",
) as agent:
    for state in agent.run():
        print(state["elapsed_ms"], state["status"])
```

Run with `uv run --env-file .env python your_script.py`. The same policy can run a different task:

```bash
uv run --env-file .env python examples/run.py \
  --url https://en.wikipedia.org/wiki/Main_Page \
  --goal 'Find and open the Wikipedia article about Gödel’s incompleteness theorems.'
```

`uv run --env-file .env python examples/flights.py --keep-open` performs the flight search, checks the actual route/date/results, and saves its trace. It does not select or book a flight.

## Why it moves

- **One request per decision cycle.** Operation and target heads share the same observed state.
- **No screenshots in the default agent loop.** Jev consumes structured state. The inspector opts into screenshots; the video uses a separate continuous screencast.
- **One browser call per snapshot.** Read visible controls, their names, values, and text atomically. Keep references to the actual DOM nodes.
- **Validate the selected target.** Clicks check the document, form values, target, and nearby context. Animation alone does not force another prediction. Resolve current geometry and reject covered controls before input.
- **Wait for useful state.** After typing into a combobox, wait for visible suggestions, capped at 200 ms. Other interactions get at most two animation frames or 50 ms. These reads happen after execution is logged.
- **Keep hidden tabs rendering.** Focus emulation prevents background animation throttling without switching Chrome's visible tab.
- **Send visible text.** Offscreen article bodies and footers do not fill the model context.
- **Reuse an interrupted text request.** A generated value survives a stale-page retry only if the entire text-helper input is unchanged.

Every executed target is resolved from an observed node. The executor rechecks page freshness and click occlusion. Model output never becomes selectors, coordinates, shell commands, or executable JavaScript. Text-helper output must parse as a small JSON object before typing.

## Small enough to read

| File | Job |
| --- | --- |
| [agent.py](jev_ultrafast/agent.py) | The complete loop and text-helper handoff |
| [snapshot.js](jev_ultrafast/snapshot.js) | Atomic DOM snapshot, indexed controls, freshness guards |
| [browser.py](jev_ultrafast/browser.py) | Browser connection, current geometry, execution |
| [model.py](jev_ultrafast/model.py) | Dynamic operation/target heads and text generation |
| [questions.py](jev_ultrafast/questions.py) | Model instructions |
| [demo.py](jev_ultrafast/demo.py) | Local inspector |

## Evidence and limits

The current video is a **7,073 ms** Google Flights run. Timing starts after initial page observation and includes model calls, generated text, browser work, stale decisions, and loading waits. A fresh independent check verifies the one-way setting, Zürich, London, September 20, 2026, and visible flight options. The video plays at 1×, with no opening hold and a 0.5-second final hold.

In six alternating runs with identical models and settings, both versions passed **3/3**. Median task time went from **9.450 s → 7.092 s**, a **25% reduction**; median browser protocol calls went from **1,092 → 101**. This is three repeats of one task on one browser profile, not a general reliability benchmark.

The same policy opened the requested Wikipedia article in **2.798 s** and passed a local hotel search/filter task in **1.896 s**. Runs, failures, source hashes, and measurement boundaries are in [performance.md](docs/performance.md).

A `DONE` choice still requires independent outcome verification. The DOM reader handles common HTML and ARIA controls, not the full accessible-name specification. Shadow roots, frames, canvas, uploads, pop-up tabs, nested scrolling, and arbitrary keyboard widgets remain outside this MVP. Owned tabs share the existing Chrome profile.

## Development

```bash
uv run ruff check .
uv run pytest
node --check jev_ultrafast/static/app.js
node --check jev_ultrafast/snapshot.js
uv build
```

Tests are offline. `uv run python scripts/check_guards.py` checks real controls in a local browser without model calls. Live examples and recording scripts make paid API calls. `scripts/record_flights.py <new-folder>` captures original browser timestamps; `scripts/render_demo.py <recording-folder>` renders that verified run at 1× and crops out the Google account strip. Credentials and raw traces stay ignored.

---

[Browser Use](https://github.com/browser-use/browser-use) · [Browser Harness](https://github.com/browser-use/browser-harness) · [TypeSafe speculative fan-out](https://docs.typesafe.ai/patterns/fan-out)

## Codex + Dia (local integration)

Codex hands Jev a complete, bounded natural-language goal. Jev chooses each
operation and observed target using the goal, current page and recent actions.
Codex supplies field text only for TYPE_TEXT. The caller independently verifies
the result and handles recovery or required user approvals. Browser Harness is
model-agnostic; Jev is TypeSafe's model. This integration uses the canonical
chrome-cdp layer rather than a competing Browser Harness connection.

```bash
uv run jev-tool --browser dia --url https://en.wikipedia.org/wiki/Main_Page \
  --goal 'Find the article about Ada Lovelace and open it.' \
  --run --max-steps 12 --max-seconds 120
```

`--run` emits JSON progress and a final JSON observation, then exits. Exit 0 means
Jev said DONE, not independently verified success. Exit 2 means paused, blocked,
budget exhausted or an in-run error; exit 1 means setup failed. Newly created tabs
remain open after `--run` so Codex can verify them; the caller should close its
owned tabs when finished. Existing tabs (`--tab TAB_ID` instead of `--url`) are
never navigated or closed during setup/exit. No inspector UI is needed.

Autonomous mode currently applies a conservative **browse/search policy**:
search-like fields, search buttons, options, supported filters and same-origin
links can run. Consequential labels (Send, Pay, Confirm, Delete, etc.), unknown
controls and out-of-scope navigation pause with `needs_review`. This policy is a
heuristic boundary, not proof of a site's behavior or a substitute for user
approval. Delegate only authorized browse/search tasks; use step mode for other
workflows. Do not treat an arbitrary broad goal as permission to send, buy or delete.
The current origin is allowed by default; add `--allow-origin https://example.org`
for explicitly authorized additional destinations. No site-specific action plans
or prewritten field values are supplied to Jev.

Actions, prediction attempts and elapsed time are bounded. Time is checked between
observations/model calls and before input; an in-flight request can exceed the time
budget, but no subsequent action executes after that check. Browser mutations are
never replayed after errors. Stale observations trigger a fresh decision, preserving
already-logged actions. `outcome_verified:false` remains explicit even on DONE.

For interactive recovery, omit `--run`. The process emits an initial observation
and accepts newline-delimited JSON on stdin:

- `{"command":"run","max_steps":12,"max_seconds":120}` executes the goal autonomously.
- `{"command":"observe"}` refreshes the page and discards the pending decision.
- `{"command":"predict"}` asks TypeSafe for one next action without executing it.
- `{"command":"text"}` previews and caches Codex text for a pending TYPE_TEXT.
- `{"command":"act","fingerprint":"FROM_LAST_OBSERVATION"}` executes that decision once.
- `{"command":"close"}` exits; EOF also exits. Owned tabs close unless `--keep-open`.

After a pause, Codex inspects the pending action, obtains any required user approval,
then uses step mode or a fresh bounded goal as appropriate. The tool itself does not
collect interpersonal final-send approval. It must be obtained by the caller.

### Connection and text providers

The programmatic client lives in `chrome-cdp/python/chrome_cdp`. It holds one Node
sidecar for the whole Python session and uses the same per-browser daemon, tab
claims and diagnostics as the existing CLI/MCP. It does not launch a subprocess for
each action or observation. Set `CHROME_CDP_SKILL` only if the skill is not at
`~/.agents/skills/chrome-cdp`. Node and that skill must be installed; Dia must have
remote debugging enabled. `cdp doctor --browser dia` is read-only diagnostics.

An explicit `--port N` can replace `--browser dia`, including an already established
SSH-forwarded CDP port. No remote resources or paid cloud browsers are provisioned.
Direct hosted ws/wss URLs and provider-specific authentication remain deferred.

`jev-tool` defaults to `TEXT_MODEL_PROVIDER=codex` and uses the existing CLI login
and account usage limits. `TYPESAFE_API_KEY` is still required for predictions;
`TEXT_MODEL_API_KEY` is unnecessary with Codex. Set `CODEX_TEXT_MODEL` optionally.
Observations go to TypeSafe when predicting; field context goes to Codex for text.
Codex runs ephemerally with browser, shell, apps and other action tools disabled.

Jev retains its own indexed snapshot and freshness checks instead of converting
nodes into chrome-cdp snapshot refs. Its original limitations (shadow DOM, frames,
uploads, pop-up tabs, nested scrolling) still apply; use ordinary chrome-cdp for
those workflows. Advisory claims prevent accidental competing writers, not hostile
processes. Do not control a tab simultaneously through two clients.

### Local validation

`uv run pytest` is offline. `uv run python scripts/check_autonomous.py --live-models`
explicitly opts into model calls against temporary local forms in Dia. It checks
full-goal search completion and a pre-Send pause, independently reads final DOM
state and closes its own fixture tabs. One measured full-goal run completed in
9.3 seconds, of which 7.3 seconds was Codex text generation. This is a local fixture
measurement, not a general browser reliability or performance benchmark.

### Faster supervised draft workflows

The CLI now returns compact summaries with the selected control and aggregate
`usage.jev` / `usage.text_model` (calls, input/output tokens, model latency).
Use `--verbose` or JSON `"verbose": true` for the complete action table and probabilities.
These metrics cover recorded successful responses, not provider billing or unknown retry usage.

For an already-authorized draft workflow, permit exact observed controls once:

```sh
uv run jev-tool --browser dia --tab TAB_ID --goal 'Complete the authorized draft; stop before publication' \
  --run --max-steps 8 --max-predictions 10 --max-seconds 60 \
  --allow-control '{"kind":"click","role":"button","label":"Next"}'
```

This extends permission scope without prescribing a click sequence. Consequential
labels and origin checks still take precedence. Other unknown controls still pause.
In a persistent session, resume with `allowed_controls` and `max_predictions` on
`command: run`; an unchanged paused decision is reused without another Jev request.
Validation/no-progress repeats return for diagnosis before another identical action.
The prediction cap counts logical predictions; provider retries can add HTTP requests.

See [the observed bottlenecks and verification](docs/dia-optimization-20260918.md).
