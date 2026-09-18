# Dia browser optimization — 2026-09-18

## Motivation

Multi-step browser automation benefits from fewer host handoffs, explicit control
scope, fresh target checks, bounded model requests, and early detection of stalled
or invalid page state. The changes below address these execution patterns.

## Changes

- Exact kind/role/label authorization allows bounded draft navigation in one loop; consequential controls and origin scope still pause.
- Resume an unchanged paused decision without repredicting; changed snapshots invalidate it.
- Bound predictions separately from actions and wall time, including detours.
- Stop repeated no-effect actions and repeated clicks while observed validation errors remain.
- Expose bounded nearby field context, accessible descriptions and invalid state. Nearby text is not presented as an authoritative input value. Ambiguous multi-input containers are excluded.
- Compact response default, verbose recovery option, aggregate Jev/text-model call/token/time reporting.
- Shared skill directs early diagnosis of environment blockers and focused Codex recovery instead of restarting the same failed goal.

## Verification

80 offline pytest checks, ruff, JavaScript syntax checks, wheel/source build passed.
22 real Dia guard checks passed without model calls, including custom-field context,
validation, stale targets, overlays and node replacement.

Opt-in paid runs on isolated local fixture tabs, independently checked via DOM:

| Fixture | Outcome | Loop time | Jev calls / input / output | Text helper |
| --- | --- | --- | --- | --- |
| Search London | Exact result rendered | 8,505 ms | 3 / 5,401 / 322 | 6,604 ms; 8,521 input, 15 output tokens |
| Send boundary | Paused, zero sends | 749 ms | 1 / 1,202 / 69 | none |
| Two draft steps | Both advances executed; completion state checked | 1,425 ms | 3 / 3,199 / 178 | none |

The first draft fixture version had a DOM-global naming collision; it was corrected
and rerun with an explicit stage-count assertion. Only the corrected result is listed.
All owned fixture tabs were closed. These are single samples on small fixtures, not
an end-to-end production benchmark or a guarantee of equivalent task performance.

## Cost interpretation and next bottleneck

The tool reports model usage rather than inferring account-specific dollar cost.
For text-heavy tasks, spawning a text helper per field was the largest measured
latency component in the search fixture above. Persistent or batched text generation
requires separate context-isolation and correctness evaluation.

Optimize time and spend per independently verified completion, counting failed runs,
recovery, host handoffs and repeated predictions. Do not judge speed by one model's
latency or accept DONE as sufficient evidence.
