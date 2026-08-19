# Rim Remainder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace domain.radius_at's outermost-crossing rule with the measured first-exit (parity) rule, eliminating the rim spike wedges, every folded/sliver cell on real geometry, and 81% of the K3 boundary overshoot.

**Architecture:** One function body changes (radius_at); everything else is repinning what that function's old defect had pinned: the Trial-2 fixture regenerates, fold/sliver pin dicts empty, one test gets a synthetic fixture, stale prose is corrected, and a new containment pin makes the fix permanent.

**Tech Stack:** Python stdlib only in bench/studio; pytest via the worktree venv.

**Spec:** docs/superpowers/specs/2026-08-19-rim-remainder-design.md (binding: the R6 code, every acceptance bar, and the checklist of moved pins live there)

## Global Constraints

- Repo: "C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-UI-integration-tool", branch feature/rim-remainder. Paths contain spaces: always quote.
- Suite: `"C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-Workflow-bench\.venv\Scripts\python.exe" -m pytest tests/studio -q` from the repo root; green before every commit; read the tail line itself.
- Pure stdlib in bench/studio (test_studio_guard stays green). No em dashes (U+2014) -- python byte-scan every touched file. No AI attribution. Explicit-path git add only (unrelated uncommitted demo deletions in the tree). NEVER push.
- The probe report .superpowers/sdd/2026-08-19-rim-remainder-probe/report.md is the measurement authority; quote its numbers rather than re-deriving where a bar needs a value.

---

### Task 1: Repoint make_fixtures and prove the harness (CONTROLLER-DIRECT candidate)

**Files:**
- Modify: `tests/studio/make_fixtures.py` (the Trial 2 export path)

**Interfaces:**
- Produces: a regeneration harness that reads "bench/retired-2026-08-18/Trial 2-contract.json" (the demo exports were retired there on 2026-08-18) and, run on the UNCHANGED rule, emits a fixture byte-identical to the committed tests/studio/fixtures/trial-2-tessellation.json.

- [ ] Repoint the path; run the regeneration; diff against the committed fixture: MUST be byte-identical (this proves the harness before the rule changes anything).
- [ ] Commit `test(fixtures): make_fixtures reads the retired Trial 2 export` (the script change only; the fixture itself is unchanged).

### Task 2: The first-exit rule and everything it repins

**Files:**
- Modify: `bench/studio/domain.py` (radius_at body + docstring; the WOBBLE_TOLERANCE "what a wobble still costs" paragraph)
- Modify: `tests/studio/test_domain.py` (new unit tests), `tests/studio/test_generators.py` (TRIAL_2_FOLDS/TRIAL_2_SLIVERS -> {}), `tests/studio/test_pieces.py` (projected_max pin -> 0.008679; the untriangulatable-cell test gets a synthetic hand-built untriangulatable cell), `tests/studio/fixtures/trial-2-tessellation.json` (regenerated)
- Modify (prose only): `bench/studio/cutting.py` ~:397, `bench/studio/pieces.py` ~:228, `tests/studio/test_cutting.py` ~:152 docstring

**Interfaces:**
- Consumes: Task 1's working regeneration harness.
- Produces: radius_at exactly as the spec's binding code block; same signature, same refusal message; all callers untouched.

- [ ] Failing unit tests first (test_domain.py): (a) corner graze on the unit square returns the rim (parity: even group skipped) -- assert equality with the pre-change value computed inline; (b) a hand-built notched polygon (miniature of Trial 2's lobe: a small triangle doubling back over a ~0.5 degree window) returns the NEAR branch inside the window, not the far lobe -- assert the exact expected radius; (c) on the square and a regular polygon, first-exit equals outermost at 720 sampled thetas within 1e-12 (star-shape identity); (d) f=0.999 dense containment inside the hand-built notch window: zero points outside (point-in-polygon).
- [ ] Implement the spec's radius_at verbatim; run the unit tests green.
- [ ] Repin: TRIAL_2_FOLDS = {}, TRIAL_2_SLIVERS = {}; test_pieces projected_max pin -> approx(0.008679, abs=1e-4) (verify the measured value on this machine first and use what YOU measure, quoting it); rebuild the untriangulatable-cell test around a synthetic degenerate cell (e.g. an outline collapsing to a line after welding) so drop-not-crash stays pinned; regenerate the Trial-2 fixture with Task 1's harness (expect 532 points, 237 cells, 7 courses -- quote the diff summary in your report).
- [ ] Prose corrections (domain WOBBLE_TOLERANCE paragraph re-measured and rewritten; the three stale outermost mentions).
- [ ] Full suite green; commit `feat(domain): radius_at returns the first exit -- the rim spike dies` with every touched path listed explicitly.

### Task 3: The permanent containment pin, docs, acceptance

**Files:**
- Test: `tests/studio/test_domain.py` (the committed-fixture containment pin)
- Modify: `docs/BENCH.md`; append dated correction notes to `docs/specs/2026-08-17-cutting-truth-design.md` and `.superpowers/sdd/2026-08-18-rim-spikes/diagnosis.md` (append-only, house convention; the diagnosis note lists its three measured factual errors and points at the new spec)

- [ ] New pin test: load the COMMITTED regenerated trial-2 fixture's domain, locate its backward-wobble windows from the walked thetas, sample densely (>= 500 per window) at f = 0.999, assert zero points outside the loop. This is the acceptance bar made permanent against future rule regressions.
- [ ] docs/BENCH.md: K3 figures, folded-cells table, mechanism-A paragraph -- updated to the probe's corrected numbers (980.4 mm story).
- [ ] The two append-only correction notes.
- [ ] Run the Armadillo acceptance test and quote every number (must be unchanged: 840/14/3/0); full suite green; em-dash byte scan over every file the wave touched.
- [ ] Commit `docs(rim): the first-exit rule recorded, the diagnosis corrected`.

## Final verification (controller)

Full suite green; the fixture regeneration provenance clean (Task 1 identity proof + Task 2 regen); Armadillo unchanged; final whole-branch review (most capable model); ONE fix wave; branch left merged-or-ready per Param's standing word ("merge to local" was given for the PREVIOUS wave only -- the merge decision for THIS wave is his unless he already spoke by then).
