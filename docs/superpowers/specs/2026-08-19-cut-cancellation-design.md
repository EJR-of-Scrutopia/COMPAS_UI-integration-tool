# Cut cancellation: superseded cuts stop, identical cuts join

Date: 2026-08-19. The queue item from Param's priority meeting, defined
nowhere in writing until now; this spec grounds it in the measured
diagnosis (the explorer's report, numbers restated below). Param is
away; the wave runs autonomously, his review deferred at his standing
instruction. Branch feature/cut-cancellation STACKED on
feature/rim-remainder (c24c3b1), a controller ruling recorded in the
ledger: this wave touches bundle.py, which activates the rim wave's
follow-up rider (a crossing-rule staleness stamp), and the stamp must
name the rule that will actually be live.

## The measured problem

A real cut costs 1.5 to 13.7 seconds (Armadillo 0.4 m: 1.5 s; 0.2 m:
13.7 s; Trial 2 0.3 m: 9.9 s), 77-90% of it in
pieces.segment_pieces's per-cell loop, super-linear as size shrinks.
The server (sync-def FastAPI handlers on the threadpool) has NO
cancellation, disconnect awareness, or in-flight dedup: two
simultaneous requests for the IDENTICAL cut both run the full
computation (measured: two 13.7 s cuts each take ~30 s under GIL
contention -- waste that actively slows the answer the user waits
for). The client already does two things right: the size/thickness
sliders commit on release with a 1500 ms settle (drag cannot pile up),
and a loadSequence token guarantees a stale response never overwrites
a fresher one. What is missing: the pattern/material selects fire one
FULL build per change event with no debounce, superseded fetches are
never aborted (only ignored on arrival), and the server computes every
abandoned build to completion.

## What ships (three pieces plus the rider)

### 1. Client: select debounce + fetch abort (static/studio.js)

- The pattern and material selects get a 300 ms debounce (a dedicated
  short timer, NOT scheduleReload's 1500 ms settle: a single deliberate
  pick must still feel immediate, only arrow-key cycling coalesces).
  The existing comment "The selects commit immediately; they share the
  token, not the timer" is updated to tell the new truth.
- loadStudy keeps one AbortController in state; firing a new load
  aborts the previous in-flight fetch (fetchJson gains an optional
  signal parameter). An AbortError is swallowed silently when the
  sequence token says the load was superseded (the existing token
  logic stays the authority for what owns the screen).

### 2. Server: single-flight joining (bundle.py)

An in-flight registry keyed by the cut key (export, pattern, size):
when a build for a key is already running, a second request for the
SAME key does not compute -- it waits on the first build's completion
event and shares its result (the /api/runs 409/attach-to-existing
pattern, applied at the _cut_for layer where the memo already lives,
guarded by the existing _cut_memo_lock). Joiners get the same
generation-counter protection the memo already has.

### 3. Server: cooperative supersession (bundle.py, app.py,
pieces.py, generators.py)

- A per-export interactive-request token: each bundle GET registers a
  monotonically increasing token for its export before building. An
  in-flight build is SUPERSEDED when a strictly newer token exists for
  the same export with a DIFFERENT cut key (an identical key joins
  instead, and never supersedes).
- pieces.segment_pieces gains an optional `checkpoint` parameter
  (callable, default None), invoked once per cell in the main loop;
  generators.generate gains the same, invoked once per course in the
  builder loop (thread it through bonded_courses/monolithic_bands or
  call it in generate's own orchestration -- implementer's choice,
  stated in the report). The modules stay pure: the callable itself
  raises; pieces/generators never import bundle or know about HTTP.
- bundle passes a closure that raises CutSuperseded (a new exception
  in bundle.py) when the registry says the build's token is
  superseded. The route catches CutSuperseded and returns HTTP 409
  with {"superseded": true} -- the client's sequence guard (or the
  abort) means nobody renders it; log one line server-side.
- ONLY interactive bundle GETs register tokens and receive
  checkpoints. The staging/runs path and any other _cut_for caller
  build WITHOUT a checkpoint and can never be cancelled by
  interactive supersession (a run's cut must complete even if the
  user flips patterns while it runs).
- A superseded build writes NOTHING: no memo store (the generation
  guard already skips it; the raise happens long before), no disk
  bundle (the single write sits at the end of build_bundle, after the
  point any checkpoint can raise -- the diagnosis verified both
  writers are single-shot-at-the-end).

### 4. The rider: the crossing-rule staleness stamp

domain.py gains `CROSSING_RULE = "first-exit-2026-08-19"` beside
radius_at (a comment: bump this identifier whenever radius_at's
geometric answer changes; it exists because REQUIRED_BUNDLE_KEYS is
presence-only and cannot see a pure geometry-rule change -- the
2026-08-19 rim wave's final review finding). bundle stamps it into
the tessellation summary as `crossing_rule` on every fresh build, and
REQUIRED_BUNDLE_KEYS gains "tessellation.crossing_rule", so every
bundle cached before this wave (cut under any earlier rule) fails the
freshness gate and rebuilds.

## Acceptance bars

- Single-flight: two threads requesting the identical cold cut ->
  segment_pieces runs ONCE (counted via monkeypatch), both callers get
  equal results.
- Supersession: a slow build (a small synthetic study is enough)
  superseded by a newer different-key request raises CutSuperseded
  out of the cut loop, the route answers 409, nothing is memoised or
  written to disk; the newer request completes normally.
- Checkpoint cadence: segment_pieces invokes the checkpoint at least
  once per cell (counting callable on a multi-cell fixture);
  generate at least once per course. With checkpoint=None both
  behave byte-identically to today (the Trial-2 pin and the whole
  suite are the proof).
- Isolation: a staging-path build completes even when interactive
  supersession fires for its export mid-build.
- The stamp: a fresh bundle carries tessellation.crossing_rule ==
  "first-exit-2026-08-19"; a cached document missing the key is
  rebuilt (same test shape as the boundary_loops staleness test).
- Client: the static pins (tests/studio/test_static.py's grep style)
  cover the select debounce constant, the AbortController presence,
  and the updated comment; no JS runtime tests exist in this repo and
  none are invented for this wave.
- Suite green throughout; the Armadillo acceptance unchanged.

## Out of scope

- Cancelling staging/FEA/CRA runs (the 409/attach dedup they already
  have stays as-is).
- Multi-tab arbitration: Bench Studio is a single-user local tool;
  with two tabs open, the newer tab's interactive request supersedes
  the older tab's in-flight different-key build for the same export.
  Accepted and disclosed here.
- Preemptive thread interruption, request timeouts, HTTP/2 push, or
  any framework-level disconnect detection (measured: unavailable to
  sync handlers; cooperative checkpoints are the whole mechanism).
- Progress reporting from inside a cut (a possible future use of the
  same checkpoint hook; not built now).

## Constraints

Pure stdlib in bench/studio; suite via the worktree venv from the
repo root; no em dashes (U+2014), ASCII "--" fine; no AI attribution;
commit per task with explicit paths (unrelated uncommitted demo
deletions in the tree); NEVER push. Branch feature/cut-cancellation
off feature/rim-remainder c24c3b1 (stacked; merges after or with it,
never before -- the stamp names the first-exit rule).
