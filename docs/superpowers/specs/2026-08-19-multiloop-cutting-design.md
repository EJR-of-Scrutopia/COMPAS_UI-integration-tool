# Multi-loop generated cutting: openings in the plan domain

Date: 2026-08-19. Param chose this wave from the queue and asked for it to
be carried autonomously; his review of this spec is DEFERRED at his own
instruction ("keep working and i will look later"). Decisions below are
controller rulings, each recorded with its reasoning; the SDD ledger
carries the same list.

## What it is

Today the generated cutting engine refuses any thrust surface whose
boundary is more than one loop: `domain.boundary_ring` walks a single
ring and raises "the rim is more than one loop: {} boundary edges close
a ring of {} vertices." Param's Armadillo-style export is exactly that
surface: one outer rim of 93 vertices (measured star-shaped about its
centroid, 0 backward steps) plus three interior openings -- two elevated
oculi (z 1.8-2.6 m and 2.8-3.4 m, roughly 5 m2 each in plan) and one
ground-level touchdown ring (10 vertices at z = 0, 2.4 m2). It can only
stand in the studio today as an uncut shell or through an authored
tessellation sidecar.

This wave lifts the single-loop constraint for GENERATED cutting: a
surface with one star-shaped outer rim and any number of interior
openings cuts natively. Courses flow around the openings; pieces
adjacent to an opening are trimmed onto its true boundary, the same way
course 0 already follows the outer rim.

## The design in one paragraph

The polar domain machinery stays exactly as it is, built on the OUTER
loop alone -- axis, radius_at, courses, row-uniform arc-length division,
all byte-identical when there are no openings. Openings are handled as a
post-pass: each generated cell (a simple polygon in plan) is clipped by
each opening's plan polygon with a plan-space polygon difference. Cells
fully inside an opening are dropped and counted; cells the opening bites
into keep their trimmed remainder, whose new edge runs along the true
opening boundary; a cell that swallows an opening whole gains it as an
interior hole ring (the raw-cell "holes" field, already supported
downstream -- the authored path and cutting.bridge_holes prove it).
Everything downstream of the cell list (welding, T-junctions,
segment_pieces, binding, staging, the client) is already loop-topology
agnostic and does not change.

Why this shape and not a new parameterisation: distance-field or
mesh-graph coursing would rewrite the row-uniform machinery shipped and
pinned on 2026-08-18 and would change the output of every existing
single-loop cut (the Trial-2 fixture is pinned byte-for-byte). The
clipping post-pass leaves the zero-openings path UNTOUCHED -- same code,
same bytes -- and adds behaviour only where openings exist.

## New module: bench/studio/openings.py

Stdlib only, like every cutting-engine module (test_studio_guard
enforces it; shapely and numpy are forbidden). Two responsibilities:

### 1. Loop extraction and classification

- `extract_loops(faces) -> List[List[int]]`: every closed boundary loop
  of the mesh, each an ordered vertex ring. Same edge-use counting as
  `domain.boundary_ring`; the degree-2 check and its "rim branches
  here" refusal stay (verbatim message); instead of walking one loop
  and refusing on the count mismatch, walk every connected component.
  Deterministic order: each loop starts at its own minimum vertex id,
  loops sorted by minimum vertex id.
- `classify(loops, vertices) -> (outer_ring, hole_rings)`: the outer
  loop is the one whose plan polygon contains every other loop's
  vertices (point_in_ring). Validation, each failure a ValueError so it
  becomes CutRefused upstream:
  - No loop contains all others: "the plan has {n} boundary loops but
    no single loop contains the others; this surface has no outer rim
    to course from."
  - Two loops' plan polygons overlap (any proper edge crossing, or
    either containing a vertex of the other without full containment):
    "boundary loops overlap in plan near ({x:.2f}, {y:.2f}); an
    overhanging surface has no single-height plan to cut."
  - A hole loop's plan polygon is not simple (self-crossing when
    projected): "an opening's boundary crosses itself in plan near
    ({x:.2f}, {y:.2f}); this opening cannot be trimmed to."
  Containment/crossing tests reuse tessellation.point_in_ring,
  tessellation.on_segment and the segment-crossing primitive; import
  direction openings -> tessellation is acyclic (tessellation.py never
  imports domain or openings).

### 2. Cell clipping (plan-space polygon difference)

`clip_cells(cells, hole_loops, target_size) -> (cells, report)` where
cells are raw generator cells ({"key", "course", "outline", "holes"})
and hole_loops are plan polygons ([[x, y], ...]). For each cell, for
each hole whose plan bounding box overlaps the cell's (cheap pre-test):
difference the cell's outline by the hole polygon.

The difference algorithm (subject = cell outline, clip = hole):

1. Split every subject edge at every proper intersection with a clip
   edge, and vice versa (the same proper-crossing mathematics as
   tessellation._segments_cross, solved for the intersection point).
2. Classify every subject sub-edge by its MIDPOINT: outside the hole,
   keep; inside, discard. Classify every clip sub-edge by its midpoint:
   inside the subject, keep reversed; outside, discard. A midpoint that
   lies ON the other polygon's boundary (on_segment) is a degenerate
   configuration: abandon the walk and drop the whole cell into the
   named failure count (below). Midpoint classification is chosen over
   entry/exit flags precisely because tangencies then fail loudly
   instead of walking wrong.
3. Stitch kept sub-edges into closed rings by endpoint identity within
   1e-9 m. Any leftover unstitched edge: degenerate, drop the cell,
   named.
4. Sort rings by containment: an outermost ring is a component outline;
   a ring inside a kept outline becomes that component's hole (this is
   how a fully-swallowed opening becomes a "holes" ring on the cell).
   Orientation is normalised downstream by build_tessellation.

Outcomes per cell:
- No bbox overlap or no intersection and cell outside hole: unchanged.
- Cell entirely inside the hole (no intersections, any outline vertex
  in the hole): dropped, counted in `cells_in_openings` (count only).
- Bite: one component, key kept.
- Split into several components: components ordered by area descending;
  the largest keeps the base key, the rest get letter suffixes ("c3p12"
  -> "c3p12b", "c3p12c", deterministic). All inherit the course value.
- A component with plan area below 0.5% of the unclipped cell's area is
  dropped and its key counted in `opening_slivers` (list of keys).
- Degenerate walk (step 2/3 failures): the whole cell is dropped and
  its key recorded in `opening_clip_failures` (list of keys). The cut
  NEVER crashes on a clip; it drops and names. On real geometry these
  configurations are measure-zero; on adversarial geometry honesty
  beats heroics.

Multiple holes: validated disjoint by classify, so they are applied
sequentially; each hole clips every component produced so far.

The report dict returned: {"openings": n_holes, "cells_in_openings":
int, "cells_clipped": [keys], "opening_slivers": [keys],
"opening_clip_failures": [keys]}.

## domain.py changes

`plan_domain` calls `openings.extract_loops` + `openings.classify`
instead of `boundary_ring`, builds the polar domain from the OUTER ring
with the existing axis / thetas / winding / wobble machinery completely
unchanged, and returns one NEW key: `"holes": [ {"ring": [vertex ids],
"loop": [[x, y], ...]} ... ]` (empty list for a single-loop mesh; every
existing key keeps its exact meaning, so every existing caller and pin
survives). The star-shape rule applies to the outer loop exactly as
today. `boundary_ring` itself is UNCHANGED (its single-loop refusal
message and its tests stay; bundle.py's surface-boundary attachment
stops depending on its single-loop limitation, below).

One new refusal in plan_domain, after classification: if the axis (mean
face centroid) falls inside any hole's plan polygon
(tessellation.point_in_ring, boundary counts as inside), raise: "the
plan's axis falls inside an opening, so the polar pattern has no crown
to close on. Author the tessellation in Grasshopper and import it
instead." This is a NAMED WAVE-1 LIMIT (a true crown oculus needs the
innermost course's inner edge to follow the opening instead of closing
on the axis point; the clip machinery could carry it but the
full-circle unwrap risk is not worth this wave). Recorded as a deferral.

## generators.py changes

In `generate`, after `raw = builder(domain, size)`:

- If `domain["holes"]` is non-empty and the pattern is
  "monolithic-bands": raise ValueError "sprayed bands cannot yet cross
  openings; cut a jointed pattern or author the tessellation in
  Grasshopper." (Band ring cells span the full turn; clipping them
  needs a seam split that would touch the no-openings path. Named
  wave-1 limit, recorded as a deferral.)
- Otherwise if holes exist: `raw, opening_report =
  openings.clip_cells(raw, [h["loop"] for h in domain["holes"]],
  size)`, then build_tessellation as today, then attach every
  opening_report key onto the returned tess exactly the way
  backward_turn/backward_steps ride along today.

Zero-openings behaviour: `domain["holes"]` is empty, no clip call, the
emitted tessellation is byte-identical to today's. This is a hard
acceptance bar (the pinned Trial-2 fixture must not change by one
byte).

## bundle.py and cutting.py changes

`build_tessellation_for` currently attaches `surface.boundary` from
`domain.boundary_ring` inside try/except-pass, so a multi-loop mesh
silently gets NO boundary polyline and Surface.lift falls back to the
nearest-face clamp for off-mesh points. Upgrade: attach EVERY loop
(outer and openings) so that a drawn point pushed just off the mesh
near an opening's rim projects onto THAT opening's boundary polyline.
Concretely: cutting.Surface grows a multi-polyline attachment (list of
closed polylines; the existing single-polyline behaviour is the
one-element case -- keep the existing attribute name and semantics
working, extend rather than break, and follow cutting.py's existing
lift/projection code style). The lift projection picks the nearest
point across all attached polylines.

`tessellation_summary` (bundle.py) gains the openings block when
present on the tess: `openings, cells_in_openings, cells_clipped,
opening_slivers, opening_clip_failures` -- same mechanism as
backward_turn today. No client change: pieces render as pieces; the
uncut banner simply stops appearing for these files because they now
cut.

## What still refuses, verbatim

- Non-manifold rim (branch vertex): unchanged message.
- No boundary at all: unchanged message.
- Outer loop not star-shaped / not winding once: unchanged message
  (the star rule still binds the OUTER loop).
- No loop contains the others; loops overlap in plan; an opening
  self-crosses in plan; axis inside an opening; monolithic-bands with
  openings: the five new messages above.
- boundary_ring's own "more than one loop" message survives in
  boundary_ring for any remaining single-loop caller, but plan_domain
  no longer routes through it, so multi-loop surfaces reach the new
  machinery instead of that refusal.

## Testing

Suite: `"C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos
Studio\VS code\COMPAS-Workflow-bench\.venv\Scripts\python.exe" -m
pytest tests/studio -q` from the UI repo root. All existing tests stay
green UNTOUCHED except where a test pins the exact multi-loop refusal
path through plan_domain (none known; boundary_ring's own pins
survive because boundary_ring is unchanged).

New coverage:
- openings unit tests: extract_loops on a grid fixture with dropped
  interior faces (one hole, two holes), determinism of loop order;
  classify happy path and every named refusal, messages pinned.
- Difference unit tests, pure geometry: bite, split-into-two,
  hole-swallowed (component gains a holes ring), cell-inside-hole
  dropped, sliver component dropped and named, degenerate tangency
  dropped and named, multi-hole sequential application.
- plan_domain: single-loop mesh returns holes == [] and every other
  key byte-identical to the pre-wave output; holed mesh returns the
  classified holes; axis-in-opening refusal pinned.
- generate end-to-end on a synthetic holed dome fixture (grid or dome
  with an interior ring of faces removed): bonded-courses cuts, the
  welded tessellation has no coverage holes attributable to the clip
  (an opening is not a coverage hole: assert the report separates
  them), courses stagger, staging builds, segment_pieces draws every
  kept cell; monolithic-bands on the same fixture refuses with the
  pinned message.
- App-level: a holed contract returns 200 WITH pieces (no
  uncut_reason); the openings block appears in the tessellation
  summary.
- The pinned Trial-2 fixture test passes unchanged (byte-for-byte).
- Acceptance, skip-guarded like the TRIAL_2 pattern: if "bench/demo/
  upload from grasshopper/Aramdillo style-compas.json" is on disk,
  drive the real derive-contract + cut path: expect a native cut with
  pieces, openings == 3, zero crash; record the piece count and the
  three per-opening clip counts in the test's assertion message or the
  ledger.

## Out of scope, recorded as deferrals

- Crown oculus (axis inside an opening): refused, named above.
- monolithic-bands across openings: refused, named above.
- Non-star outer rims: unchanged refusal; lifting star-shapedness is a
  different wave (it is the rim remainder / radius_at crossing-rule
  question, queue item, untouched here).
- The radius_at wrong-crossing defect (mechanism A, 4 rim vertices on
  Trial 2): unchanged by this wave; openings never enter radius_at
  (only the outer loop does), so the defect is neither fixed nor
  worsened. Still the next queue item.
- Client-side surfacing of the openings block beyond the generic data
  panel: YAGNI until Param asks.

## Constraints

- Pure stdlib in bench/studio (test_studio_guard); no shapely, no
  numpy.
- No em dashes (U+2014) anywhere; ASCII "--" fine. No AI attribution
  or Co-Authored-By, ever. Commit per task with explicit paths (the
  working tree carries unrelated uncommitted demo-file deletions that
  must NOT be committed). NEVER push.
- Branch: feature/multiloop-cutting off UI main c4282e6.
- The zero-openings path must be byte-identical: the Trial-2 pin is
  the proof.
