# Multi-loop Generated Cutting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surfaces with one star-shaped outer rim and any number of interior openings cut natively in Bench Studio: courses flow around the openings, pieces trim onto the true opening boundaries.

**Architecture:** A new stdlib-only module `bench/studio/openings.py` (multi-loop boundary extraction + classification, and a plan-space polygon-difference clipper) applied as a post-pass over generated cells. The polar domain machinery is untouched on the zero-openings path (byte-identical output). Downstream of the cell list nothing changes: welding, segment_pieces, binding, staging and the client are already loop-agnostic.

**Tech Stack:** Python stdlib only in bench/studio (test_studio_guard forbids numpy/shapely/solver stacks), pytest via the worktree venv, FastAPI app untouched except the tessellation summary.

**Spec:** docs/superpowers/specs/2026-08-19-multiloop-cutting-design.md (binding; read it first, every algorithm detail and refusal message lives there)

## Global Constraints

- Repo: "C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-UI-integration-tool", branch feature/multiloop-cutting. Paths contain spaces: always quote.
- Suite: `"C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-Workflow-bench\.venv\Scripts\python.exe" -m pytest tests/studio -q` from the repo root. Green before every commit; check the tail line itself, never trust a piped exit code.
- bench/studio modules: pure stdlib. tests/studio/test_studio_guard.py must stay green.
- The zero-openings path is byte-identical: test_generators.py's committed Trial-2 fixture pin must pass UNCHANGED. If it fails, the change is wrong, not the pin.
- No em dashes (U+2014) anywhere -- ASCII "--" fine. Check every touched file with a python byte scan (grep -P is locale-broken on this machine). No AI attribution or Co-Authored-By, ever.
- Commit per task with EXPLICIT file paths only: the working tree carries unrelated uncommitted demo-file deletions (bench/demo, bench/studies) that must never enter a commit. NEVER push.
- Refusal messages are copied verbatim from the spec. Refusals raised under bundle.build_tessellation_for's generated branch become CutRefused/uncut_reason automatically; do not wrap anything yourself.
- Edit-tool caution: when replacing a block, re-read the surrounding lines and make sure old_string does not swallow an adjacent line you mean to keep.

---

### Task 1: openings.py -- loop extraction and classification

**Files:**
- Create: `bench/studio/openings.py`
- Test: `tests/studio/test_openings.py`

**Interfaces:**
- Produces: `extract_loops(faces: Sequence[Sequence[int]]) -> List[List[int]]` -- every closed boundary loop as an ordered vertex ring; each loop starts at its own minimum vertex id and walks toward its smaller-id neighbour first (deterministic); loops sorted by minimum vertex id. Raises ValueError with domain.boundary_ring's exact no-boundary and branch-vertex messages (copy the format strings verbatim from bench/studio/domain.py:76 and :84-87).
- Produces: `classify(loops: List[List[int]], vertices) -> Tuple[List[int], List[List[int]]]` -- (outer_ring, hole_rings), holes in extract_loops order. The three named refusals from the spec section "Loop extraction and classification", messages verbatim.
- Consumes: `tessellation.point_in_ring`, `tessellation.on_segment`, and the proper-crossing test (read tessellation.py:148-218 and :611-620 first; import from tessellation, do not duplicate).

- [ ] **Step 1: failing tests.** In `tests/studio/test_openings.py` build a local `grid(side, drop=())` helper copied in miniature from tests/studio/test_domain.py:27-60 (N x N unit quads at z=0, faces droppable by (row, col)). Tests:
  - `test_a_single_loop_mesh_yields_one_loop`: grid(3) -> extract_loops returns 1 loop, same vertex set as domain.boundary_ring(faces).
  - `test_an_interior_hole_yields_two_loops`: grid(5, drop=((2, 2),)) -> 2 loops; the 4-vertex interior loop is second (higher min vertex id ordering asserted explicitly).
  - `test_two_holes_yield_three_loops_deterministically`: grid(7, drop=((2, 2), (4, 4))) -> 3 loops, order stable across two calls.
  - `test_branch_vertex_still_refuses_verbatim`: two quads sharing only one vertex -> the exact "rim branches here" message.
  - `test_classify_picks_the_containing_loop`: grid(5, drop=((2, 2),)) -> outer is the 16-vertex rim, one 4-vertex hole.
  - `test_classify_refuses_when_no_loop_contains_the_others`: two disjoint quads (faces [[0,1,2,3],[4,5,6,7]] with two separated unit squares) -> "no single loop contains the others" message pinned.
  - `test_classify_refuses_a_self_crossing_opening`: hand-built loops/vertices where the hole ring's plan projection is a bowtie -> "crosses itself in plan" message pinned.
- [ ] **Step 2: run, confirm every test fails on ImportError/AttributeError.**
- [ ] **Step 3: implement `extract_loops` and `classify` to green.** Module docstring states purpose and the stdlib-only rule like domain.py:18-19 does.
- [ ] **Step 4: full suite green** (`-q`, read the tail line).
- [ ] **Step 5: commit** `feat(openings): every boundary loop extracted and classified, refusals named` with explicit paths (`bench/studio/openings.py`, `tests/studio/test_openings.py`).

### Task 2: openings.py -- the plan-space polygon difference

**Files:**
- Modify: `bench/studio/openings.py`
- Test: `tests/studio/test_openings.py` (extend)

**Interfaces:**
- Produces: `clip_cells(cells: List[Dict], hole_loops: List[List[List[float]]], target_size: float) -> Tuple[List[Dict], Dict]`. Cells are raw generator cells `{"key", "course", "outline", "holes"}`; hole_loops are plan polygons. Returns the surviving cell list and the report dict `{"openings": int, "cells_in_openings": int, "cells_clipped": [keys], "opening_slivers": [keys], "opening_clip_failures": [keys]}`.
- Algorithm: the spec's "Cell clipping" section is the binding description -- edge splitting at proper intersections, MIDPOINT classification of sub-edges (on-boundary midpoint = degenerate = drop the cell, named), ring stitching within 1e-9 m, containment sort (inner kept rings become component holes), area-descending key suffixes ("c3p12", "c3p12b", ...), 0.5%-of-unclipped-area sliver rule, sequential application of validated-disjoint holes, bbox pre-test.
- Consumes: Task 1's module scaffolding; tessellation.point_in_ring / on_segment; shoelace area computed locally (three lines, no import needed).

- [ ] **Step 1: failing tests, pure geometry** (no mesh, subject cell key "c0p0", course 0, target_size 1.0 unless said):
  - `test_no_overlap_leaves_the_cell_untouched`: square (0,0)-(4,4), hole square (10,10)-(12,12) -> identical cell object content, empty report lists.
  - `test_a_bite_trims_onto_the_hole_boundary`: square (0,0)-(4,4), hole square (3,1)-(5,3) -> one cell, its outline contains the hole's true corner points (3,1) and (3,3), area == 16 - 2 within 1e-9, key unchanged, "c0p0" in cells_clipped.
  - `test_a_crossing_hole_splits_into_two_components`: square (0,0)-(4,4), hole rectangle (-1,1.5)-(5,2.5) -> two cells keyed "c0p0" (area 6, the larger is equal here so assert the deterministic tie: area-descending then the stitcher's ring order) and "c0p0b", both course 0.
  - `test_a_swallowed_hole_becomes_an_interior_ring`: square (0,0)-(4,4), hole square (1,1)-(3,3) -> one cell, outline unchanged, holes == [the hole ring], area check via shoelace outline minus hole == 12.
  - `test_a_cell_inside_the_hole_is_dropped`: square (1,1)-(2,2), hole square (0,0)-(4,4) -> zero cells, cells_in_openings == 1.
  - `test_a_sliver_component_is_dropped_and_named`: square (0,0)-(4,4), hole rectangle (-1,-1)-(3.999,5) -> the surviving right-edge strip has area 0.004*4 = 0.016 < 0.5% of 16 (0.08) -> zero cells, "c0p0" in opening_slivers.
  - `test_a_collinear_tangency_is_dropped_and_named`: square (0,0)-(4,4), hole square (4,1)-(6,3) sharing the x=4 edge run -> "c0p0" in opening_clip_failures, zero crash.
  - `test_two_holes_apply_sequentially`: square (0,0)-(8,4), holes (1,1)-(3,3) swallowed and (7,-1)-(9,5) biting the right edge -> one cell with one interior ring and a trimmed right edge; both effects present.
- [ ] **Step 2: run, confirm failures.**
- [ ] **Step 3: implement the difference to green.** Keep the walk in small named helpers (`_split_edges`, `_classify_subedges`, `_stitch_rings`, `_assign_holes`) so each is testable; any degeneracy raises a private `_DegenerateClip(Exception)` caught once in clip_cells to drop-and-name.
- [ ] **Step 4: full suite green.**
- [ ] **Step 5: commit** `feat(openings): plan-space polygon difference, cells trim onto opening boundaries`.

### Task 3: plan_domain holes + generate clip pass, end to end on a holed dome

**Files:**
- Modify: `bench/studio/domain.py` (plan_domain only; boundary_ring untouched)
- Modify: `bench/studio/generators.py` (generate only)
- Test: `tests/studio/test_domain.py`, `tests/studio/test_generators.py` (extend)

**Interfaces:**
- plan_domain return dict gains `"holes": [{"ring": [vertex ids], "loop": [[x, y], ...]}, ...]`, [] for single-loop meshes; every existing key exactly as today. New axis-in-opening refusal AFTER classification, message verbatim from the spec ("the plan's axis falls inside an opening..."). plan_domain routes through openings.extract_loops + openings.classify; the outer ring feeds the existing axis/thetas/winding/wobble code untouched.
- generate: holes present + pattern "monolithic-bands" -> ValueError with the spec's verbatim sprayed-bands message; holes present + jointed pattern -> `raw, opening_report = openings.clip_cells(raw, [h["loop"] for h in domain["holes"]], size)` between the builder call and build_tessellation, then every opening_report key attached to the returned tess the way backward_turn is at generators.py:463-464.

- [ ] **Step 1: failing tests.**
  - test_domain.py: `test_a_single_loop_plan_gains_an_empty_holes_key` (grid(3): holes == [] and axis/loop/ring/thetas/star_shaped values equal the current output captured inline); `test_an_interior_hole_is_classified_not_refused` (grid(5, drop=((2, 2),)): plan_domain succeeds, one hole with 4 ids and 4 plan points, star_shaped True); `test_the_axis_inside_an_opening_refuses_verbatim` (build a mesh whose dropped faces surround the centroid: grid(5, drop=((2, 2),)) has axis near the centre -- shift the hole instead: construct grid(5) and drop (2,2) then verify axis location; if the axis lands inside, use this mesh for the refusal test and grid(7, drop=((2, 2),)) with an off-centre hole for the happy path; measure in the test, do not guess).
  - test_generators.py: `test_bonded_courses_flow_around_an_opening` on a holed paraboloid: 9x9 grid, z = 2 - (x-4.5)^2/20 - (y-4.5)^2/20 seen through the existing fixture idiom, faces (2,2),(2,3),(3,2),(3,3) dropped (off-centre 2x2 hole; assert in-test that the axis is NOT inside it): generate("bonded-courses", plan, 1.0) succeeds; some cell keys carry clip suffixes or cells_clipped is non-empty; no cell's outline point lies strictly inside the hole polygon (point_in_ring check over every outline point, strict); report keys present on tess. `test_monolithic_bands_refuse_openings_verbatim` on the same fixture. `test_the_trial_2_pin_is_untouched`: just run the existing pinned test unmodified -- named here so the implementer runs and quotes it in the report.
- [ ] **Step 2: run, confirm failures.**
- [ ] **Step 3: implement to green.** plan_domain's docstring gains two sentences on holes; generate's clip pass mirrors the backward_turn ride-along comment style.
- [ ] **Step 4: full suite green, Trial-2 pin quoted in the report.**
- [ ] **Step 5: commit** `feat(domain): openings classified into the plan domain, courses clip around them`.

### Task 4: lift projection onto every loop + the openings summary block

**Files:**
- Modify: `bench/studio/cutting.py` (Surface boundary attachment + lift projection)
- Modify: `bench/studio/bundle.py` (build_tessellation_for attachment site :265-271, tessellation_summary)
- Test: `tests/studio/test_cutting.py`, `tests/studio/test_bundle.py`, `tests/studio/test_app.py` (extend)

**Interfaces:**
- cutting.Surface: the boundary attachment accepts multiple closed polylines (the existing single-polyline path is the one-element case; read cutting.py:354-444 first and extend the existing attribute/mechanism rather than adding a parallel one). Lift's off-mesh projection picks the nearest point across ALL attached polylines.
- bundle.build_tessellation_for: attach every loop -- outer and openings -- from openings.extract_loops over the analysis faces, inside the same try/except ValueError guard as today (a branch-vertex mesh still just skips attachment).
- bundle.tessellation_summary: when the tess carries them, pass through `openings, cells_in_openings, cells_clipped, opening_slivers, opening_clip_failures` exactly like backward_turn_degrees/backward_steps today (bundle.py:400-427).

- [ ] **Step 1: failing tests.**
  - test_cutting.py: `test_an_off_mesh_point_projects_onto_the_nearest_opening_rim`: a Surface with two attached square polylines, a probe point just outside the inner one -> lift projects onto the inner polyline, not the outer (assert by distance).
  - test_app.py: `test_a_holed_contract_cuts_natively_with_pieces`: a contract built from the Task 3 holed paraboloid (follow bay_contract's construction at test_app.py:62-101): POST/GET the bundle -> 200, uncut_reason is None/absent, pieces non-empty, tessellation summary carries "openings" == 1.
  - test_bundle.py: `test_the_openings_block_rides_the_summary`: build_bundle on the holed fixture -> the five keys present; on a no-openings fixture -> absent (same presence rule as the existing optional keys).
- [ ] **Step 2: run, confirm failures.**
- [ ] **Step 3: implement to green.**
- [ ] **Step 4: full suite green.**
- [ ] **Step 5: commit** `feat(bundle): multi-loop lift projection and the openings summary`.

### Task 5: acceptance on the real Armadillo, docs, ledger numbers

**Files:**
- Test: `tests/studio/test_acceptance_armadillo.py` (new)
- Modify: `docs/` architecture/README notes only if a cutting-engine overview exists that lists the single-loop rule (search for "star" under docs/ and bench/studio module docstrings; update domain.py's module docstring lines 1-20, which still state the single-loop precondition as absolute -- reword to name openings support and the remaining outer-loop star rule).

- [ ] **Step 1: the acceptance test.** Skip-guarded exactly like the TRIAL_2 pattern (pytest.skip when the file is absent): load "bench/demo/upload from grasshopper/Aramdillo style-compas.json", drive derive_contract + the real cut path (build_bundle or the app test client, whichever the TRIAL_2 acceptance uses -- follow it): assert 200/no-CutRefused, pieces non-empty, openings == 3, opening_clip_failures small and disclosed (assert the list is a list; record its length). Print/record piece count and the report numbers.
- [ ] **Step 2: run it against the real file (it is on disk right now); paste the measured numbers into the report and the ledger.**
- [ ] **Step 3: docs.** domain.py docstring reword; any docs/ mention of the single-loop refusal updated to name the openings machinery.
- [ ] **Step 4: em-dash byte scan over every file touched this wave; full suite green.**
- [ ] **Step 5: commit** `feat(acceptance): the Armadillo cuts natively -- openings respected, numbers recorded`.

## Final verification (controller)

Full suite green on the branch; Trial-2 pin untouched; the Armadillo acceptance numbers in the ledger; final whole-branch review on the most capable model; ONE fix wave; merge decision is Param's (he is away -- leave the branch reviewed and ready, merge only on his word).
