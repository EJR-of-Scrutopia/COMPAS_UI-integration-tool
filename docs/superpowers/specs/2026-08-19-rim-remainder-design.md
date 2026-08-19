# The rim remainder: radius_at's crossing rule becomes the first exit

Date: 2026-08-19. Param chose this wave from the queue ("move onto
next task" after the multi-loop merge); he is away and the wave runs
autonomously, his review deferred at his own standing instruction.
Every decision below is grounded in the measured design probe at
.superpowers/sdd/2026-08-19-rim-remainder-probe/report.md (git-ignored;
the binding numbers are restated here so this spec stands alone).

## The defect, correctly diagnosed at last

domain.radius_at picks the OUTERMOST ray-segment crossing. The
2026-08-18 rim-spikes diagnosis named the consequence (mechanism A:
4 of Trial 2's 240 rim vertices resolve to the wrong rim point,
producing the visible spike wedges welded into real cuts) but its
mechanism story was wrong, and this wave's probe re-measured it:

- The worst mispositioning is 980.4 mm (vertices 184/220), not the
  505.7 mm the diagnosis reported (that figure was a vertex-to-vertex
  distance, not the error).
- The offending segment is nearly PERPENDICULAR to the ray (72.6-72.8
  degrees), not nearly radial; every "filter near-radial segments"
  fix is a measured no-op at every threshold.
- The real mechanism: Trial 2's tolerated rim wobble makes the rim
  genuinely MULTI-VALUED over a 0.2337 degree window (a small lobe,
  triangle 181-182-183, mirrored). Inside that window the plan's
  interior along a ray is two disjoint intervals; the outermost rule
  returns a point on the far side of a gap the ray has already left
  the plan through. Every symptom (wrong-vertex substitution, the
  1.23 m rim cliff, the folded cells, containment violations at
  f = 0.999) follows from that choice.

## The rule that ships

R6, the FIRST EXIT: count crossings with a half-open side convention,
group crossings coincident within 1e-12 m, and return the smallest
radius whose group has ODD parity -- the radius at which the ray
first genuinely leaves the plan. On any star-shaped plan and any
corner graze this returns exactly what the outermost rule returned
(a graze is an even group and never flips parity -- the current
docstring's fear, handled by construction rather than by "outermost").
Where the rim is multi-valued it returns the near branch. No tuned
thresholds beyond the existing 1e-15 parallel guard and the 1e-12 m
grouping (measured five orders of magnitude clear of both graze gaps
< 1e-13 and genuine gaps > 0.27 m).

The implementation is BINDING as probed (bench/studio/domain.py,
replacing radius_at's body; docstring rewritten to the first-exit
story):

```python
def radius_at(domain: Dict, theta: float) -> float:
    ax, ay = domain["axis"]
    dx, dy = math.cos(theta), math.sin(theta)
    loop = domain["loop"]
    n = len(loop)
    hits = []
    for i in range(n):
        p = loop[i]
        q = loop[(i + 1) % n]
        sp = dx * (p[1] - ay) - dy * (p[0] - ax)
        sq = dx * (q[1] - ay) - dy * (q[0] - ax)
        if (sp > 0.0) == (sq > 0.0):
            continue
        ex, ey = q[0] - p[0], q[1] - p[1]
        denominator = dx * ey - dy * ex
        if abs(denominator) < 1e-15:
            continue
        px, py = p[0] - ax, p[1] - ay
        along_ray = (px * ey - py * ex) / denominator
        if along_ray >= 0.0:
            hits.append(along_ray)
    if not hits:
        raise ValueError(
            "no rim crossing at theta {:.6f}; the axis is outside the "
            "plan".format(theta))
    hits.sort()
    i = 0
    while i < len(hits):
        j = i
        while j + 1 < len(hits) and hits[j + 1] - hits[i] <= 1e-12:
            j += 1
        if (j - i + 1) % 2 == 1:
            return hits[i]
        i = j + 1
    return hits[-1]
```

(The refusal message is unchanged, verbatim. The half-open side test
replaces the along_edge tolerance test entirely.)

Why not the runner-up (innermost): indistinguishable on every cut
metric, but its apparent vertex-truth win comes from returning
TANGENCIES -- on a rim with an inward needle it would collapse the
domain radius to the needle tip. First-exit is immune by construction.

CONTROLLER RULING, recorded for the reviewers: on a multi-valued rim,
per-vertex radius truth is NOT the objective (returning each wobble
vertex's own radius would emit course-0 outlines out of walked order,
i.e. self-crossing cells). The objectives are containment, continuity,
fold count, and the cut metrics below. The nominal vertex-truth
regression at vertices 182/222 (980.4 -> 1186.6 mm max) is accepted
on that ground.

## Measured acceptance bars (Trial 2 unless stated)

- Containment at f = 0.999: zero points outside the true loop, both
  on a 72000-sample sweep AND on 2000 targeted samples inside each
  backward-wobble window (the coarse sweep alone straddles the notch
  and proves nothing).
- TRIAL_2_FOLDS and TRIAL_2_SLIVERS: both become EMPTY, and the
  existing 55-size sweep test keeps proving it (folds 6 -> 0,
  slivers 2 -> 0 across both generators).
- Longest course-0 RIM edge at 0.4 m: <= 1.0 m (measured 0.945; was
  1.225 -- the false cliff across the notch mouth replaced by the
  notch's real step; it cannot reach the 0.412 m median and honesty
  forbids pretending otherwise).
- Real-path pieces at 0.4 m: 1140 of 1140 cells drawn (was 1138;
  c1p47/c1p87 rescued); degenerate_dropped empty at every swept size.
- projected_max_m at 0.9 m: ~0.008679 (was 0.046405; the test_pieces
  pin moves to the new measured value, same approx tolerance).
- Armadillo (multi-loop control): every number of
  test_acceptance_armadillo.py unchanged -- 840 pieces, 14 courses,
  openings 3, clip failures 0, slivers ["c9p9"], coverage_holes
  empty; welded coordinates move at most ~4e-14 m.
- The committed Trial-2 fixture is REGENERATED (532 points, same 237
  cells / 7 courses; only c0p22/c0p40 change geometrically, all cell
  entries renumber). PREREQUISITE: tests/studio/make_fixtures.py
  still reads the retired export path "bench/demo/upload from
  grasshopper/Trial 2-contract.json"; repoint it to
  "bench/retired-2026-08-18/" FIRST and prove the harness by
  regenerating BEFORE the rule change -- the output must be
  byte-identical to the committed fixture.

## Everything else that moves (binding checklist)

- test_pieces.py::test_an_untriangulatable_cell_is_dropped_not_crashed
  loses its real fixture (nothing on Trial 2 is untriangulatable any
  more, at any size): KEEP the test, feed it a hand-built synthetic
  untriangulatable cell so the drop-not-crash contract stays pinned.
- domain.py WOBBLE_TOLERANCE comment: the "what a tolerated wobble
  still costs" paragraph re-measured (0 folded cells at 0 sizes) and
  rewritten with the first-exit rule named.
- Stale prose naming the outermost rule: cutting.py ~:397,
  pieces.py ~:228, test_cutting.py ~:152 docstring.
- docs/BENCH.md: the K3 overshoot figures (46.4/40.2 mm -> 8.7/6.8),
  the folded-cells table (empties), the mechanism-A paragraph
  (505.7 -> the corrected story and 980.4 mm figure).
- docs/specs/2026-08-17-cutting-truth-design.md and the 2026-08-18
  rim-spikes diagnosis both declared this rule out of scope /
  unchangeable: APPEND a dated correction note to each (house
  convention: append, never rewrite history) pointing at this spec.
- A NEW pin test: on the committed Trial-2 domain, dense targeted
  sampling inside both wobble windows at f = 0.999 stays inside the
  loop (the containment bar made permanent).

## What this wave does NOT do

- The notch lobe itself (2 x 0.023 m2, 0.023% of the plan) is
  legitimately outside the star-shaped kernel the polar domain can
  reach; the cut stops 1-2 cm short of the mesh edge over 0.23
  degrees of rim, twice, with zero coverage_holes/orphans (binding
  still claims every face). A dedicated rim-remainder piece for such
  lobes is now WELL-DEFINED (bounded between two single-valued
  curves) and deferred as its own future item.
- Cut cancellation: the next queue item, untouched here.
- No behaviour change on star-shaped plans beyond last-ulp float
  drift (measured <= 1.2e-14 m on saddle/Armadillo samples); no test
  asserts exact float equality against stored points except the
  regenerated fixture itself.

## Constraints

Pure stdlib in bench/studio; suite via the worktree venv from the
repo root; no em dashes (U+2014), ASCII "--" fine; no AI attribution;
commit per task with explicit paths (the tree carries unrelated
uncommitted demo deletions); NEVER push. Branch feature/rim-remainder
off main 5b15307.
