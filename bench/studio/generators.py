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
from typing import Dict, List, Tuple

import cutting
import domain as domain_module
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
    "armadillo-dual": "wave 6c",
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


def _circumference(domain: Dict, f: float) -> float:
    """Plan length once around at normalised radius f."""

    total = 0.0
    previous = domain_module.plan_point(domain, f, 0.0)
    for i in range(1, ANGLE_SAMPLES + 1):
        point = domain_module.plan_point(domain, f, TWO_PI * i / ANGLE_SAMPLES)
        total += math.hypot(point[0] - previous[0], point[1] - previous[1])
        previous = point
    return total


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


def _divisions(
    domain: Dict, size: float, courses: int, course: int
) -> Tuple[int, float, List[float]]:
    """One course's piece count, its stagger offset, and its head joint angles."""
    mid_f = 1.0 - (course + 0.5) / courses
    count = max(1, int(math.floor(_circumference(domain, mid_f) / size + 0.5)))
    offset = (course % 2) * math.pi / count
    angles = [offset + TWO_PI * k / count for k in range(count)]
    return count, offset, angles


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


def bonded_courses(domain: Dict, size: float) -> List[Dict]:
    """Staggered courses, rim to crown, at the target piece size."""

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
        outer_f = 1.0 - course / courses
        inner_f = 1.0 - (course + 1) / courses
        count, offset, _ = all_divisions[course]

        for k in range(count):
            start = offset + TWO_PI * k / count
            end = offset + TWO_PI * (k + 1) / count

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


def monolithic_bands(domain: Dict, size: float) -> List[Dict]:
    """One continuous cell per course. Sprayed concrete has no castings."""

    courses = _course_count(domain, size)
    cells: List[Dict] = []
    for course in range(courses):
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


def generate(pattern: str, domain: Dict, size: float) -> Dict:
    builder = GENERATORS.get(pattern)
    if builder is None:
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
        raise ValueError(
            "this plan is not star shaped about its axis (the rim turns back "
            "on itself at vertex {}, {} times, {:.2f} degrees of backward "
            "turn total), so no polar pattern can cover it. Author the "
            "tessellation in Grasshopper and import it instead.".format(
                failure["vertex"], failure["backward_steps"],
                math.degrees(domain["backward_turn"]),
            )
        )
    raw = builder(domain, size)
    tess = tessellation.build_tessellation(
        raw, pattern, "generated", size, _course_count(domain, size)
    )
    # The wobble is a measured property of the plan, not of the pattern
    # drawn on it, so it rides along on every generated cut for whoever
    # reports it downstream (see bundle.py's tessellation summary).
    tess["backward_turn"] = domain["backward_turn"]
    tess["backward_steps"] = domain["backward_steps"]
    return tess
