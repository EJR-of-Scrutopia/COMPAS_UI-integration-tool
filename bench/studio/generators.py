"""The patterns the studio can draw for itself.

These are a preview kit, not the design. The real cutting patterns come
from Grasshopper, where the control and the design intent belong; these
exist so that materiality, engineering, rendering and animation are all
working before those arrive. That is why the interface matters more than
the two patterns behind it, and why an imported tessellation is a
generator like any other (see tessellation.read_tessellation).

Bonded courses apply an alternating half pitch offset to shift every other
course, which avoids systematic alignment of head joints. However, this
does not prevent all alignments: where adjacent courses' piece counts share
factors, individual joints can line up. On a disc radius 5 at target size
1.0, courses have 28, 22, 16, 9 and 3 pieces respectively, and a head
joint falls at 90 degrees in courses 0, 1 and 2 alike. A sizing rule that
guarantees no alignment is not a wave 6a question.

Stdlib only: the bundle path imports this.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

import cutting
import domain as domain_module
import openings
import refusals
import tessellation

TWO_PI = 2.0 * math.pi

# Patterns named in the spec that this wave does not build. The UI lists
# them and says which wave they arrive in, rather than quietly drawing
# courses under a Guastavino label.
PLANNED = {
    "guastavino-herringbone": "wave 6b",
    "hexagonal-panels": "wave 6b",
    "diagrid": "wave 6b",
    "spiral-courses": "wave 6b",
    "armadillo-dual": "wave 6c -- author with the Armadillo Dual component "
    "in Grasshopper and import the sidecar",
}

# Every material's default, overridable from the UI. Tile and stone point
# at bonded courses because their intended patterns are not built yet, and
# the pattern control says so.
DEFAULT_PATTERN = {
    "concrete": "bonded-courses",
    "concrete-c50": "bonded-courses",
    "concrete-sprayed": "monolithic-bands",
    "timber": "bonded-courses",
    "brick": "bonded-courses",
    "tile": "bonded-courses",
    "stone": "bonded-courses",
}

MATERIAL_NOTES = {
    "tile": "Guastavino herringbone arrives in wave 6b; tile is drawn in "
            "bonded courses until then.",
    "stone": "The Armadillo force aligned tessellation arrives in wave 6c; "
             "stone is drawn in bonded courses until then.",
}

ANGLE_SAMPLES = 720


def _mean_radius(domain: Dict) -> float:
    total = 0.0
    for i in range(ANGLE_SAMPLES):
        total += domain_module.radius_at(domain, TWO_PI * i / ANGLE_SAMPLES)
    return total / ANGLE_SAMPLES


def _course_count(domain: Dict, size: float) -> int:
    return max(1, int(math.floor(_mean_radius(domain) / size + 0.5)))


def _inside_span(angles, start: float, end: float) -> List[float]:
    """Every candidate angle, resolved to whichever branch lands strictly
    inside (start, end) and deduplicated, sorted by the value actually
    used rather than the angle it came from.

    Tried at theta, theta plus a turn and theta minus a turn, because a
    span can sit anywhere on the real line while an angle is reported in
    minus pi to pi and a course's head joints run from an offset up past
    2 pi. Sorting the surviving values, not the source angles, is what
    lets a span crossing either seam (2 pi on the head joint pass, pi on
    the rim pass) come out in sequence: some of its points are reached
    through the wrapped branch and some directly, so ordering by theta
    would emit them out of order and the outline would cross itself.
    """

    return sorted({
        turn
        for theta in angles
        for turn in (theta, theta + TWO_PI, theta - TWO_PI)
        if start + 1e-12 < turn < end - 1e-12
    })


def _point_line_distance(p, a, b) -> float:
    """Perpendicular distance from p to the infinite line through a, b;
    falls back to point-to-point distance if a and b coincide."""

    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length < 1e-12:
        return math.hypot(p[0] - ax, p[1] - ay)
    return abs(dx * (p[1] - ay) - dy * (p[0] - ax)) / length


def _douglas_peucker_indices(anchor_a, points, anchor_b, tolerance: float) -> List[int]:
    """Indices into points that survive simplifying anchor_a..points..
    anchor_b against tolerance: the classic recursive rule -- keep the
    point farthest from the current chord if it is over tolerance away,
    then recurse on both halves; keep nothing between two points that are
    already within tolerance of the chord joining them."""

    n = len(points)
    if n == 0:
        return []
    keep = [False] * n

    def recurse(lo: int, hi: int, a, b) -> None:
        if lo >= hi:
            return
        farthest_i, farthest_d = lo, -1.0
        for i in range(lo, hi):
            d = _point_line_distance(points[i], a, b)
            if d > farthest_d:
                farthest_i, farthest_d = i, d
        if farthest_d <= tolerance:
            return
        keep[farthest_i] = True
        recurse(lo, farthest_i, a, points[farthest_i])
        recurse(farthest_i + 1, hi, points[farthest_i], b)

    recurse(0, n, anchor_a, anchor_b)
    return [i for i in range(n) if keep[i]]


def _simplify_boundary_run(
    domain: Dict, f: float, start: float, end: float, turns: List[float], tolerance: float
) -> List[float]:
    """Douglas-Peucker over one cell's own rim-following outline stretch.

    K3 (cutting truth, 2026-08-17): course 0's outline used to insert
    every one of the real rim's own boundary vertices between a cell's two
    head joints (240 on the real Trial 2 export, one drawn piece boundary
    point per mesh boundary vertex, the one-piece-per-boundary-vertex
    fragmentation named in the cutting truth spec). The anchors here are
    the arc's own start and end points, already exactly on the rim
    (plan_point at f = 1.0), so simplifying the points between them
    against a straight chord simplifies exactly this one cell's own
    boundary-following stretch, never reaching past its own two head
    joints into a neighbour's -- two adjacent course-0 cells therefore
    still meet at the same welded point they always did, only the run
    between meets thins out.
    """

    anchor_a = domain_module.plan_point(domain, f, start)
    anchor_b = domain_module.plan_point(domain, f, end)
    points = [domain_module.plan_point(domain, f, turn) for turn in turns]
    keep = _douglas_peucker_indices(anchor_a, points, anchor_b, tolerance)
    return [turns[i] for i in keep]


def _arc(
    domain: Dict, f: float, start: float, end: float, extra_angles=None,
    boundary_tolerance: float = cutting.CHORD_TARGET,
) -> List[List[float]]:
    """Outline points from start to end at radius f, ends included.

    At the rim the arc follows the mesh's own boundary corners, so the
    silhouette is the real silhouette. Inside, a course boundary is a
    straight chord between its two ends, which is what a cut bed joint
    actually is, and what keeps a piece a clean four sided shape.

    extra_angles: optional list of angles to include if they fall strictly
    inside the span -- always kept verbatim, never simplified: these are
    deliberate cut joints (a neighbouring course's own head joint angles,
    threaded through so two courses' shared boundary stays one set of
    points on both sides), not boundary vertices, so there is nothing
    about them a chord tolerance should be allowed to drop.

    boundary_tolerance: K3 (cutting truth, 2026-08-17). At the rim
    (f >= 1), the mesh's own boundary corners strictly inside this span
    are simplified against this chord tolerance before insertion (see
    _simplify_boundary_run) -- reusing cutting.CHORD_TARGET, the cut's own
    existing precision budget for how far a cap may depart from the true
    surface, rather than inventing a new number for how far this outline
    may depart from the true rim.
    """

    plain_inside = _inside_span(extra_angles, start, end) if extra_angles else []

    boundary_inside: List[float] = []
    if f >= 1.0 - 1e-12:
        boundary_inside = _inside_span(domain_module.boundary_angles(domain), start, end)
        if boundary_inside:
            boundary_inside = _simplify_boundary_run(
                domain, f, start, end, boundary_inside, boundary_tolerance)

    inside = sorted(set(plain_inside) | set(boundary_inside))
    return (
        [domain_module.plan_point(domain, f, start)]
        + [domain_module.plan_point(domain, f, turn) for turn in inside]
        + [domain_module.plan_point(domain, f, end)]
    )


def _arc_length_samples(domain: Dict, f: float) -> Tuple[List[float], List[float]]:
    """Theta and cumulative plan arc length at radius f, sampled at
    ANGLE_SAMPLES steps around one full turn and closed (thetas[-1] is
    exactly TWO_PI, cumulative[-1] is the course's own circumference at
    this radius). Kept as a running total alongside its own theta samples,
    rather than the plain summed distance a circumference figure alone
    would be, so the running total can be inverted back to an angle.
    """

    thetas = [TWO_PI * i / ANGLE_SAMPLES for i in range(ANGLE_SAMPLES + 1)]
    points = [domain_module.plan_point(domain, f, t) for t in thetas]
    cumulative = [0.0]
    for i in range(1, len(points)):
        cumulative.append(cumulative[-1] + math.hypot(
            points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1]))
    return thetas, cumulative


def _theta_at_length(thetas: List[float], cumulative: List[float], s: float) -> float:
    """The theta whose cumulative plan arc length, measured from theta =
    0 around _arc_length_samples's own polyline, is s; s wraps into
    [0, total). Linear interpolation within the bracketing sample pair,
    which is exact wherever the true boundary is straight there and a
    close approximation everywhere else at ANGLE_SAMPLES resolution (0.5
    degree steps) -- more than fine enough for placing a masonry head
    joint.
    """

    total = cumulative[-1]
    # Cheap cleanup (review, 2026-08-18): a genuinely zero-length course
    # (mid radius zero all the way round) would otherwise divide by zero
    # at "s % total" below. _uniform_arc_divisions already guards its own
    # near-zero case the same way (length <= 1e-9 -> 1 piece); this guard
    # keeps that same threshold's promise here, at the one call site that
    # actually performs a division by it.
    if total <= 1e-9:
        return thetas[0]
    s = s % total
    lo, hi = 0, len(cumulative) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if cumulative[mid] <= s:
            lo = mid
        else:
            hi = mid
    span = cumulative[hi] - cumulative[lo]
    fraction = (s - cumulative[lo]) / span if span > 1e-15 else 0.0
    return thetas[lo] + fraction * (thetas[hi] - thetas[lo])


def _uniform_arc_divisions(length: float, target: float) -> int:
    """How many equal length pieces to cut a course's own full-loop arc
    into, near target size (2026-08-18, row-uniform courses fix).

    ceil(length / target): every piece comes out at or under target,
    never over -- "slightly under target", the fix contract's own words,
    not an accident of rounding. max(1, ...) is also, for what this
    generator actually ever calls this with, the whole of the fix
    contract's "an arc shorter than half the target merges into its
    neighbour's division" rule: bonded_courses only ever hands this
    function a course's own full 2*pi loop (measured directly: no
    opening/interruption mechanism exists anywhere in domain.py,
    generators.py or tessellation.py, see
    .superpowers/sdd/2026-08-18-rim-spikes/diagnosis.md), so there is
    never a second, neighbouring arc within the same course to merge a
    short one into. A course shorter than half the target simply becomes
    the one piece it already would under max(1, ...), rather than being
    forced into a multi-way split with no piece anywhere near the size
    actually asked for -- the one-arc special case of the general rule,
    named here rather than left implicit.
    """

    if length <= 1e-9:
        return 1
    return max(1, math.ceil(length / target - 1e-9))


def _divisions(
    domain: Dict, size: float, courses: int, course: int
) -> Tuple[int, float, List[float]]:
    """One course's piece count and its own head joint angles, spaced at
    UNIFORM ARC LENGTH (2026-08-18, row-uniform courses fix) rather than
    uniform angle.

    Equal angular steps only give equal PLAN length on a true circle: a
    real vault plan is not one, and dividing it into equal angles instead
    of equal lengths is exactly what let pieces within one course come out
    anywhere from far short of the target to several times over it.
    Measured on the real Trial 2 export at 0.4 m under the OLD angle-
    uniform rule: course 0 alone ran 0.163 m to 2.239 m within a single
    course, a 13.8x max/min ratio (full table:
    .superpowers/sdd/2026-08-18-rim-spikes/diagnosis.md). Sampling arc
    length at this course's own mid radius (the same reference radius the
    piece COUNT was already computed from, below) and placing head joints
    at equal steps of that length, then converting each step back to its
    own angle, fixes it: every piece in the course comes out the same
    length at the sampled radius, by construction.

    The returned "offset" is now angles[0] itself (the first head joint's
    own angle) rather than a separately meaningful half-angle stagger:
    callers that used to reconstruct a piece's own start/end from
    `offset + TWO_PI * k / count` must instead read angles[k] and
    angles[k + 1] directly, since the steps are no longer uniform in
    angle. The stagger itself is now a genuine half-PIECE-LENGTH offset on
    alternating courses (length_offset below) -- an actual half-brick
    stagger, the physical point of running bond, in place of the old
    half-angle one.
    """

    mid_f = 1.0 - (course + 0.5) / courses
    thetas, cumulative = _arc_length_samples(domain, mid_f)
    total = cumulative[-1]
    count = _uniform_arc_divisions(total, size)
    piece_length = total / count
    length_offset = (course % 2) * (piece_length / 2.0)
    angles = [
        _theta_at_length(thetas, cumulative, length_offset + k * piece_length)
        for k in range(count)
    ]
    return count, angles[0], angles


def _ring(domain: Dict, f: float) -> List[List[float]]:
    """A full turn at radius f, counter clockwise, closed by the caller.

    Both bands sharing this circle call it with the same f and get the
    identical point list, so welding joins them into one boundary rather
    than two circles a float apart.
    """

    steps = max(48, int(math.ceil(ANGLE_SAMPLES / 8)))
    out: List[List[float]] = []
    for i in range(steps):
        out.extend(_arc(domain, f, TWO_PI * i / steps, TWO_PI * (i + 1) / steps)[:-1])
    return out


def bonded_courses(
    domain: Dict, size: float, checkpoint: Optional[Callable[[], None]] = None
) -> List[Dict]:
    """Staggered courses, rim to crown, at the target piece size.

    checkpoint (cut cancellation, 2026-08-19): an optional zero-argument
    callable, invoked once per course at the top of the loop below that
    actually builds each course's own pieces -- not the divisions pass
    just above it, which only samples ANGLE_SAMPLES points per course
    regardless of how many pieces that course holds. The build loop is
    where the real, piece-count-scaling cost sits (one _arc call, with its
    own boundary simplification, per piece), the same order of magnitude
    as pieces.segment_pieces's own per-cell loop, so this is where a
    single per-course checkpoint honestly covers the course's expensive
    work. None (the default) means this behaves exactly as before this
    parameter existed.
    """

    courses = _course_count(domain, size)

    # Calculate divisions for each course
    all_divisions = []
    for course in range(courses):
        count, offset, angles = _divisions(domain, size, courses, course)
        all_divisions.append((count, offset, angles))

    # Build shared angles for each boundary level (union of adjacent courses)
    shared = {}
    for k in range(courses + 1):
        angles_set = set()
        if k >= 1:
            # Inner boundary of course k-1
            angles_set.update(all_divisions[k-1][2])
        if k < courses:
            # Outer boundary of course k
            angles_set.update(all_divisions[k][2])
        shared[k] = sorted(list(angles_set))

    cells: List[Dict] = []
    for course in range(courses):
        if checkpoint is not None:
            checkpoint()
        outer_f = 1.0 - course / courses
        inner_f = 1.0 - (course + 1) / courses
        count, _offset, angles = all_divisions[course]

        for k in range(count):
            # Row-uniform courses fix (2026-08-18): angles[k]..angles[k+1]
            # is this piece's own span, at UNIFORM ARC LENGTH rather than
            # uniform angle -- see _divisions. The last piece wraps back to
            # angles[0] plus one full turn, the same convention the old
            # offset + TWO_PI * (k + 1) / count expression used at k = count - 1.
            start = angles[k]
            end = angles[k + 1] if k + 1 < count else angles[0] + TWO_PI

            outline = _arc(domain, outer_f, start, end, shared[course])
            if inner_f > 1e-12:
                outline += list(reversed(_arc(domain, inner_f, start, end, shared[course + 1])))
            else:
                outline.append([domain["axis"][0], domain["axis"][1]])

            cells.append({
                "key": "c{}p{}".format(course, k),
                "course": course,
                "outline": outline,
                "holes": [],
            })
    return cells


def monolithic_bands(
    domain: Dict, size: float, checkpoint: Optional[Callable[[], None]] = None
) -> List[Dict]:
    """One continuous cell per course. Sprayed concrete has no castings.

    checkpoint: see bonded_courses's own docstring -- the same optional
    zero-argument callable, invoked once per course at the top of this
    loop, the only one this builder has, where each course's own ring (or
    pair of rings, for a course with a hole) is actually built.
    """

    courses = _course_count(domain, size)
    cells: List[Dict] = []
    for course in range(courses):
        if checkpoint is not None:
            checkpoint()
        outer_f = 1.0 - course / courses
        inner_f = 1.0 - (course + 1) / courses
        cell = {
            "key": "band{}".format(course),
            "course": course,
            "outline": _ring(domain, outer_f),
            "holes": [],
        }
        if inner_f > 1e-12:
            cell["holes"] = [list(reversed(_ring(domain, inner_f)))]
        cells.append(cell)
    return cells


GENERATORS = {
    "bonded-courses": bonded_courses,
    "monolithic-bands": monolithic_bands,
}


def _separate_opening_regions(report: Dict, hole_loops: List, points: List) -> None:
    """Split report["coverage_holes"] into real gaps and opening regions.

    Fix round 1 (review finding 3, task-3-review.md): tessellation's own
    coverage-hole finder (tessellation._find_coverage_holes) reports every
    enclosed region no cell covers, and cannot tell an opening apart from
    a genuine gap -- both are, structurally, a loop of single-owner
    facets. An opening IS such a loop by construction (clip_cells trims
    every bordering cell onto the opening's true boundary, so the missing
    material's edge sits exactly there), so on a holed cut every opening
    ships as a false positive in coverage_holes unless something here
    tells them apart.

    The representative point for a coverage_holes entry is its own loop's
    centroid (the mean of its own boundary points, `entry["points"]`
    indexing into `points`): for an opening this lands deep inside that
    opening's own polygon, because the loop bounding it is that polygon's
    boundary. tessellation.point_in_ring treats "on the boundary" as
    inside, matching plan_domain's own axis-in-opening rule. This is a
    representative-point test, not a full polygon-containment proof: a
    pathologically non-convex coverage-hole loop could in principle have
    its own vertex-average centroid fall outside its own boundary, the
    same class of approximation WOBBLE_TOLERANCE and the clip's own
    sliver threshold already accept elsewhere in this engine, and not one
    any real cut in this repo (paraboloid or Armadillo) has produced.

    Mutates report in place: entries whose centroid falls inside any
    opening move from "coverage_holes" into a new "opening_regions" list,
    same entry shape, so nothing is silently dropped -- only reclassified.
    A genuine gap's own loop bounds real, uncut material, nowhere near an
    opening's polygon, so it is untouched by this pass and still names
    itself in coverage_holes exactly as before.
    """

    coverage_holes = []
    opening_regions = []
    for entry in report["coverage_holes"]:
        loop = entry["points"]
        centroid = [
            sum(points[i][0] for i in loop) / len(loop),
            sum(points[i][1] for i in loop) / len(loop),
        ]
        in_opening = any(
            tessellation.point_in_ring(centroid, list(range(len(hole_loop))), hole_loop)
            for hole_loop in hole_loops
        )
        (opening_regions if in_opening else coverage_holes).append(entry)
    report["coverage_holes"] = coverage_holes
    report["opening_regions"] = opening_regions


def generate(
    pattern: str,
    domain: Dict,
    size: float,
    checkpoint: Optional[Callable[[], None]] = None,
) -> Dict:
    """Build a cut of the named pattern over domain, at the target size.

    checkpoint (cut cancellation, 2026-08-19): an optional zero-argument
    callable threaded straight through to whichever builder GENERATORS
    dispatches to (bonded_courses or monolithic_bands), which invokes it
    once per course -- see either builder's own docstring for exactly
    where and why. generate() never calls it directly itself: this
    function's own work outside the builder call (openings.clip_cells,
    tessellation.build_tessellation) is not per-course, and doesn't
    reliably run at all (clip_cells only when the domain has holes), so
    there is no honest per-course point to add a second call here. None
    (the default) means generate() and both builders behave exactly as
    they did before this parameter existed: never called. Raising out of
    checkpoint propagates unmodified; generate() never mutates domain, so
    an aborted call leaves the caller's own domain dict untouched.
    """

    builder = GENERATORS.get(pattern)
    if builder is None:
        # NOT retyped to refusals.PlanRefused (fix batch, bundle honesty,
        # 2026-08-19; classification decision, task-2-report.md): these
        # two messages are about the ARGUMENT, not the geometry -- there
        # is no domain, no plan, nothing "this geometry cannot be cut
        # politely" about a caller naming a pattern that does not exist
        # (a typo) or exists only on the roadmap (PLANNED). app._validate
        # already rejects both with its own 400 before build_bundle is
        # ever reached over the real API (bench/studio/app.py:108-113),
        # so a plain ValueError reaching here at all means a DIRECT
        # caller (bundle.py, staging.py, a test) misused the function
        # signature -- API misuse, not a refusal on valid geometry, and
        # it must keep propagating as the bug it is rather than being
        # caught by bundle.build_tessellation_for's PlanRefused-only
        # catch and reported as an honest uncut bundle.
        planned = PLANNED.get(pattern)
        if planned is not None:
            raise ValueError(
                "the {} pattern arrives in {}. Available now: {}".format(
                    pattern, planned, ", ".join(sorted(GENERATORS))
                )
            )
        raise ValueError(
            "unknown pattern {!r}: use one of {}".format(
                pattern, ", ".join(sorted(GENERATORS))
            )
        )
    if not domain["star_shaped"]:
        failure = domain["failure"]
        # Curated refusal (fix batch, bundle honesty, 2026-08-19): see
        # refusals.PlanRefused's own docstring. Message unchanged.
        raise refusals.PlanRefused(
            "this plan is not star shaped about its axis (the rim turns back "
            "on itself at vertex {}, {} times, {:.2f} degrees of backward "
            "turn total), so no polar pattern can cover it. Author the "
            "tessellation in Grasshopper and import it instead.".format(
                failure["vertex"], failure["backward_steps"],
                math.degrees(domain["backward_turn"]),
            )
        )
    # domain.get rather than domain["holes"]: a domain dict built by hand
    # (a fixture, or the pinned Trial-2 tessellation's own committed
    # domain, both predating this wave) never carries the key, and no
    # openings is exactly the behaviour those callers already pin.
    holes = domain.get("holes", [])
    if holes and pattern == "monolithic-bands":
        # Curated refusal (fix batch, bundle honesty, 2026-08-19): see
        # refusals.PlanRefused's own docstring. Message unchanged.
        raise refusals.PlanRefused(
            "sprayed bands cannot yet cross openings; cut a jointed "
            "pattern or author the tessellation in Grasshopper."
        )

    raw = builder(domain, size, checkpoint=checkpoint)
    opening_report = None
    if holes:
        raw, opening_report = openings.clip_cells(
            raw, [h["loop"] for h in holes], size
        )
    tess = tessellation.build_tessellation(
        raw, pattern, "generated", size, _course_count(domain, size)
    )
    # The wobble is a measured property of the plan, not of the pattern
    # drawn on it, so it rides along on every generated cut for whoever
    # reports it downstream (see bundle.py's tessellation summary).
    tess["backward_turn"] = domain["backward_turn"]
    tess["backward_steps"] = domain["backward_steps"]
    # Same ride-along, only when openings were actually clipped: the
    # report is a property of the plan against this cut, not of the
    # pattern beyond having crossed it.
    if opening_report is not None:
        tess["openings"] = opening_report["openings"]
        tess["cells_in_openings"] = opening_report["cells_in_openings"]
        tess["cells_clipped"] = opening_report["cells_clipped"]
        tess["opening_slivers"] = opening_report["opening_slivers"]
        tess["opening_clip_failures"] = opening_report["opening_clip_failures"]
        # An opening is not a coverage hole (review finding 3): it is a
        # loop of single-owner facets exactly like a real gap is, so
        # tessellation's own coverage-hole finder cannot tell them apart
        # on its own -- separate them here, where the opening polygons
        # are known.
        _separate_opening_regions(
            tess["report"], [h["loop"] for h in holes], tess["points"]
        )
    return tess
