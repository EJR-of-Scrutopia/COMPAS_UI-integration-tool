# Cut Cancellation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Superseded interactive cuts stop mid-loop instead of burning 1.5-13.7 s to a result nobody reads; identical concurrent cuts join one computation; the client aborts what it abandons; cached bundles learn to see crossing-rule changes.

**Architecture:** Optional checkpoint callables threaded into the two cut loops (pieces per-cell, generators per-course; modules stay pure, the callable raises); a bundle-layer in-flight registry giving single-flight joining per cut key and per-export supersession tokens for interactive GETs only; a 300 ms select debounce plus AbortController client-side; the CROSSING_RULE staleness stamp riding along.

**Tech Stack:** Python stdlib (threading.Event/Lock alongside the existing _cut_memo_lock), FastAPI sync handlers unchanged in shape, vanilla JS in studio.js.

**Spec:** docs/superpowers/specs/2026-08-19-cut-cancellation-design.md (binding: the supersession semantics, isolation rule, stamp value, and every acceptance bar)

## Global Constraints

- Repo: "C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-UI-integration-tool", branch feature/cut-cancellation (STACKED on feature/rim-remainder c24c3b1; never merges before it). Paths contain spaces: always quote.
- Suite: `"C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-Workflow-bench\.venv\Scripts\python.exe" -m pytest tests/studio -q` from the repo root; green before every commit; read the tail line itself.
- Pure stdlib in bench/studio (test_studio_guard). checkpoint=None must be byte-identical to today: the Trial-2 pin is the proof. No em dashes (U+2014) -- python byte-scan touched files. No AI attribution. Explicit-path git add only. NEVER push.
- Concurrency tests must be deterministic: gate thread interleavings on threading.Event handshakes (a fake-slow segment_pieces that signals "started" and waits for "release"), never on sleeps.

---

### Task 1: The checkpoint hook in the cut loops

**Files:**
- Modify: `bench/studio/pieces.py` (segment_pieces signature + per-cell invocation), `bench/studio/generators.py` (generate + builders, per-course invocation)
- Test: `tests/studio/test_pieces.py`, `tests/studio/test_generators.py` (extend)

**Interfaces:**
- Produces: `segment_pieces(tess, surface, support_points, checkpoint=None)` -- checkpoint invoked once per cell at the TOP of the main per-cell loop (before the cell's expensive work); `generate(pattern, domain, size, checkpoint=None)` -- invoked once per course inside the builder loops (state in the report where exactly, and why there). The callable takes no arguments and returns nothing; raising is the caller's business; pieces/generators import nothing new.

- [ ] Failing tests: a counting callable on a multi-cell fixture asserts calls >= cell count (pieces) and >= course count (generators); a raising callable aborts the loop with the raised exception propagating and NO partial mutation of shared state (assert the tess/report objects handed in are not half-written); checkpoint=None leaves the existing pinned outputs byte-identical (run the Trial-2 pin and quote it).
- [ ] Implement; full suite green; commit `feat(cut): a cooperative checkpoint in the cut loops`.

### Task 2: Single-flight joining and supersession in bundle/app

**Files:**
- Modify: `bench/studio/bundle.py` (in-flight registry, CutSuperseded, checkpoint closure, the CROSSING_RULE stamp + REQUIRED_BUNDLE_KEYS entry), `bench/studio/domain.py` (the CROSSING_RULE constant + comment), `bench/studio/app.py` (get_bundle registers the interactive token, catches CutSuperseded -> 409 {"superseded": true}, one log line)
- Test: `tests/studio/test_bundle.py`, `tests/studio/test_app.py` (extend)

**Interfaces:**
- Consumes: Task 1's checkpoint parameters.
- Produces: in bundle.py -- `CutSuperseded(Exception)`; an in-flight map keyed by the cut key (export, pattern, size) guarded by _cut_memo_lock (holder: threading.Event + result slot + error slot); a per-export token registry with `register_interactive(export) -> token` and `superseded(export, token, key) -> bool` (true iff a strictly newer token for the export carries a DIFFERENT key); `_cut_for(..., interactive_token=None)` builds the checkpoint closure only when a token is given. `domain.CROSSING_RULE = "first-exit-2026-08-19"` stamped as `crossing_rule` in tessellation_summary on every fresh build; `"tessellation.crossing_rule"` appended to REQUIRED_BUNDLE_KEYS with a self-describing comment.

- [ ] Failing tests, deterministic via Event handshakes: (a) single-flight -- two threads, identical cold key, monkeypatched segment_pieces counts ONE invocation, both threads receive equal results; (b) supersession -- thread A starts a slow build (fake segment_pieces blocks on an Event after signalling started), a newer interactive request registers a different key for the same export, A's checkpoint raises CutSuperseded when released, the route answers 409 {"superseded": true}, nothing memoised, no bundle file written (assert on a scratch STUDIES_DIR); the newer request completes; (c) isolation -- a build WITHOUT an interactive token (the staging path's shape) completes untouched while supersession fires for its export; (d) identical-key newer request JOINS and does not supersede; (e) the stamp -- fresh bundle carries crossing_rule == "first-exit-2026-08-19"; a cached document with the key deleted is rebuilt (mirror the boundary_loops staleness test).
- [ ] Implement; full suite green; commit `feat(bundle): superseded cuts stop, identical cuts join, the crossing rule stamps the cache`.

### Task 3: Client debounce + abort, static pins, acceptance

**Files:**
- Modify: `bench/studio/static/studio.js` (select debounce 300 ms via a dedicated timer + constant; one AbortController in state, fetchJson gains an optional signal, loadStudy aborts the predecessor, AbortError swallowed when superseded; the "share the token, not the timer" comment updated)
- Test: `tests/studio/test_static.py` (extend, house grep style)

- [ ] Failing static pins: the debounce constant name + 300 value; "AbortController" present in loadStudy's region; the updated comment text; fetchJson's signal parameter.
- [ ] Implement; manual-check note for Param recorded in the report (flip patterns rapidly in the browser: one cut, no console errors); full suite green.
- [ ] Em-dash byte scan over every file this wave touched; run the Armadillo acceptance and quote it; commit `feat(studio): the client aborts what it abandons`.

## Final verification (controller)

Full suite green; the deterministic concurrency tests stable across 3 consecutive runs (no flake); Armadillo acceptance unchanged; final whole-branch review (most capable model) covering the stacked-branch relationship; ONE fix wave; the branch waits with feature/rim-remainder for Param's word.
