"""Every closed boundary loop of a mesh, extracted and classified.

domain.boundary_ring walks one boundary loop and refuses outright if a
second one closes: a surface with an opening has no single rim. This
module lifts that limit for generated cutting. extract_loops walks every
connected boundary component instead of just one, so a vault with an
oculus or a touchdown ring describes its whole boundary rather than
refusing at the first ring. classify then picks the outer rim out of
those loops -- the one loop whose plan polygon contains every other
loop's vertices -- and validates the rest as interior openings: no loop
may overlap another, and no opening's own boundary may cross itself in
plan.

clip_cells then does the actual trimming: a plan-space polygon difference
between each raw generator cell and each opening, in the tradition of
tessellation's own edge-splitting and welding. A cell an opening bites
into is trimmed onto the opening's true boundary; a cell an opening
swallows whole is dropped and counted; a cell that swallows an opening
whole gains it as an interior "holes" ring, same field the authored path
and cutting.bridge_holes already read.

Stdlib only, like every cutting-engine module: test_studio_guard.py
forbids solver stacks (compas, numpy, shapely, ...) on this path.
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence, Tuple

import tessellation

TOL = tessellation.TOL


def extract_loops(faces: Sequence[Sequence[int]]) -> List[List[int]]:
    """Every closed boundary loop of the mesh, as an ordered vertex ring.

    Same edge-use counting as domain.boundary_ring, and the same degree-2
    branch refusal, but instead of walking a single ring and refusing
    when more than one loop closes, every connected boundary component is
    walked and returned. Deterministic order: each loop starts at its own
    minimum vertex id and steps toward its smaller-id neighbour first;
    loops are sorted by minimum vertex id.
    """

    users: Dict[tuple, int] = {}
    for face in faces:
        count = len(face)
        for i in range(count):
            a, b = face[i], face[(i + 1) % count]
            key = (a, b) if a < b else (b, a)
            users[key] = users.get(key, 0) + 1
    edges = [key for key, used in users.items() if used == 1]
    if not edges:
        raise ValueError("this mesh has no boundary, so it has no rim to fit")

    neighbours: Dict[int, List[int]] = {}
    for a, b in edges:
        neighbours.setdefault(a, []).append(b)
        neighbours.setdefault(b, []).append(a)
    for vertex, found in neighbours.items():
        if len(found) != 2:
            raise ValueError(
                "boundary vertex {} has {} boundary neighbours, not 2; the "
                "rim branches here".format(vertex, len(found))
            )

    visited = set()
    loops: List[List[int]] = []
    for start in sorted(neighbours):
        if start in visited:
            continue
        ring = [start]
        visited.add(start)
        previous = start
        current = min(neighbours[start])
        while current != start:
            ring.append(current)
            visited.add(current)
            options = [v for v in neighbours[current] if v != previous]
            previous, current = current, options[0]
        loops.append(ring)

    loops.sort(key=lambda ring: ring[0])
    return loops


def _proper_crossing_point(loop_a, loop_b, vertices):
    """The start point of the first properly crossing edge pair, or None."""

    count_a, count_b = len(loop_a), len(loop_b)
    for i in range(count_a):
        a1 = vertices[loop_a[i]]
        a2 = vertices[loop_a[(i + 1) % count_a]]
        for j in range(count_b):
            b1 = vertices[loop_b[j]]
            b2 = vertices[loop_b[(j + 1) % count_b]]
            if tessellation._segments_cross(a1, a2, b1, b2):
                return a1[0], a1[1]
    return None


def _partial_containment_point(loop_a, loop_b, vertices):
    """A vertex of loop_b inside loop_a, if loop_a holds some but not all."""

    inside = [
        v for v in loop_b
        if tessellation.point_in_ring(vertices[v], loop_a, vertices)
    ]
    if 0 < len(inside) < len(loop_b):
        vertex = inside[0]
        return vertices[vertex][0], vertices[vertex][1]
    return None


def _overlap_point(loop_a, loop_b, vertices):
    """Where loop_a and loop_b's plan polygons overlap, or None.

    Overlap is a proper edge crossing between the two loops, or either
    loop containing some but not all of the other's vertices (full
    containment is the ordinary outer/hole relationship, not overlap).
    """

    point = _proper_crossing_point(loop_a, loop_b, vertices)
    if point is not None:
        return point
    point = _partial_containment_point(loop_a, loop_b, vertices)
    if point is not None:
        return point
    return _partial_containment_point(loop_b, loop_a, vertices)


def _self_crossing_point(loop, vertices):
    """The start point of the first pair of non-adjacent edges that cross."""

    count = len(loop)
    for i in range(count):
        a1 = vertices[loop[i]]
        a2 = vertices[loop[(i + 1) % count]]
        for j in range(i + 2, count):
            if (j + 1) % count == i:
                continue
            b1 = vertices[loop[j]]
            b2 = vertices[loop[(j + 1) % count]]
            if tessellation._segments_cross(a1, a2, b1, b2):
                return a1[0], a1[1]
    return None


def classify(
    loops: List[List[int]], vertices: Sequence[Sequence[float]]
) -> Tuple[List[int], List[List[int]]]:
    """Split loops into the outer rim and its interior openings.

    The outer loop is the one whose plan polygon contains every other
    loop's vertices (tessellation.point_in_ring). Every pair of loops,
    outer included, is then checked for overlap (a proper edge crossing,
    or one loop containing some but not all of another's vertices).
    Finally every hole loop's own plan polygon must be simple, not
    self-crossing -- the outer loop's shape rules are plan_domain's
    concern, not this function's.
    """

    if len(loops) == 1:
        return loops[0], []

    outer_index = None
    for i, candidate in enumerate(loops):
        contains_all_others = all(
            j == i
            or all(
                tessellation.point_in_ring(vertices[v], candidate, vertices)
                for v in loops[j]
            )
            for j in range(len(loops))
        )
        if contains_all_others:
            outer_index = i
            break
    if outer_index is None:
        raise ValueError(
            "the plan has {} boundary loops but no single loop contains "
            "the others; this surface has no outer rim to course "
            "from.".format(len(loops))
        )

    for i in range(len(loops)):
        for j in range(i + 1, len(loops)):
            point = _overlap_point(loops[i], loops[j], vertices)
            if point is not None:
                raise ValueError(
                    "boundary loops overlap in plan near ({:.2f}, {:.2f}); "
                    "an overhanging surface has no single-height plan to "
                    "cut.".format(point[0], point[1])
                )

    outer_ring = loops[outer_index]
    hole_rings = [loop for i, loop in enumerate(loops) if i != outer_index]

    for hole in hole_rings:
        point = _self_crossing_point(hole, vertices)
        if point is not None:
            raise ValueError(
                "an opening's boundary crosses itself in plan near "
                "({:.2f}, {:.2f}); this opening cannot be trimmed "
                "to.".format(point[0], point[1])
            )

    return outer_ring, hole_rings


# --- Cell clipping: the plan-space polygon difference -----------------
#
# Stitched-ring endpoints from the SAME crossing land within machine
# precision of one another (the intersection point is computed once and
# shared by both polygons' split lists), so ring stitching uses a much
# tighter tolerance than the general TOL used for containment queries.
STITCH_TOL = 1e-9

# A component below this fraction of the unclipped cell's area is a
# sliver: dropped, its key named in the report rather than shipped.
SLIVER_FRACTION = 0.005


class _DegenerateClip(Exception):
    """A clip walk hit a configuration this algorithm cannot resolve.

    Caught exactly once, in clip_cells: the cell that triggered it is
    dropped whole and its key recorded in opening_clip_failures. The cut
    never crashes on a clip; on real geometry (holes validated disjoint
    by classify, cells simple by construction) these configurations are
    measure zero, so honesty beats heroics on the adversarial remainder.
    """


def _shoelace_area(ring: Sequence[Sequence[float]]) -> float:
    """Plan area of a closed polygon given as a list of [x, y] points."""

    total = 0.0
    count = len(ring)
    for i in range(count):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % count][0], ring[(i + 1) % count][1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _bbox(ring: Sequence[Sequence[float]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_overlap(a, b) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _in_ring(point, ring: Sequence[Sequence[float]]) -> bool:
    """tessellation.point_in_ring adapted to a raw coordinate ring.

    point_in_ring wants a ring of indices into a shared points table;
    plan polygons here are plain [x, y] lists, so the ring is its own
    identity index and its own points table.
    """

    return tessellation.point_in_ring(point, list(range(len(ring))), ring)


def _point_ring_relation(point, ring: Sequence[Sequence[float]]) -> str:
    """"in", "on" or "out" -- point_in_ring collapses "on" into "in", and
    the clip walk needs the distinction: a midpoint ON the other
    polygon's boundary is exactly the tangency this algorithm refuses to
    walk through blind (see _classify_subedges).
    """

    count = len(ring)
    for i in range(count):
        a = ring[i]
        b = ring[(i + 1) % count]
        if abs(a[0] - point[0]) <= TOL and abs(a[1] - point[1]) <= TOL:
            return "on"
        if tessellation.on_segment(point, a, b) is not None:
            return "on"
    return "in" if _in_ring(point, ring) else "out"


def _rings_cross(ring_a, ring_b) -> bool:
    count_a, count_b = len(ring_a), len(ring_b)
    for i in range(count_a):
        a1, a2 = ring_a[i], ring_a[(i + 1) % count_a]
        for j in range(count_b):
            b1, b2 = ring_b[j], ring_b[(j + 1) % count_b]
            if tessellation._segments_cross(a1, a2, b1, b2):
                return True
    return False


def _intersection(a, b, c, d):
    """Where infinite lines ab and cd meet, plus each line's parameter.

    Only ever called on a pair the caller already knows crosses properly
    (tessellation._segments_cross), so the lines are never parallel here.
    """

    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    denom = rx * sy - ry * sx
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / denom
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / denom
    point = (a[0] + t * rx, a[1] + t * ry)
    return point, t, u


def _apply_cuts(ring, cuts: List[List[Tuple[float, Tuple[float, float]]]]):
    """Split ring into sub-edges at the given per-edge (t, point) cuts."""

    count = len(ring)
    subedges = []
    for i in range(count):
        a, b = ring[i], ring[(i + 1) % count]
        ordered = [point for _, point in sorted(cuts[i], key=lambda item: item[0])]
        chain = [a] + ordered + [b]
        for k in range(len(chain) - 1):
            subedges.append((chain[k], chain[k + 1]))
    return subedges


def _split_edges(subject, clip):
    """Split subject and clip at every proper mutual intersection.

    Every crossing's point is computed exactly once (the standard
    plan-space parametric solve) and pushed into both rings' cut lists,
    so a subject sub-edge and a clip sub-edge that meet at the same
    crossing carry bit-identical coordinates there -- the ring stitch
    later relies on that. Returns (subject_subedges, clip_subedges,
    crossed), crossed being whether any proper intersection existed at
    all (the no-crossing outcomes -- untouched, swallowed, cell-inside
    -hole -- are told apart by the caller from that flag).
    """

    subject_cuts: List[List[Tuple[float, Tuple[float, float]]]] = [
        [] for _ in subject
    ]
    clip_cuts: List[List[Tuple[float, Tuple[float, float]]]] = [[] for _ in clip]
    crossed = False
    for i in range(len(subject)):
        a1, a2 = subject[i], subject[(i + 1) % len(subject)]
        for j in range(len(clip)):
            b1, b2 = clip[j], clip[(j + 1) % len(clip)]
            if tessellation._segments_cross(a1, a2, b1, b2):
                crossed = True
                point, t, u = _intersection(a1, a2, b1, b2)
                subject_cuts[i].append((t, point))
                clip_cuts[j].append((u, point))
    subject_subedges = _apply_cuts(subject, subject_cuts)
    clip_subedges = _apply_cuts(clip, clip_cuts)
    return subject_subedges, clip_subedges, crossed


def _classify_subedges(subject_subedges, clip_subedges, subject, clip):
    """Keep sub-edges by their midpoint, oriented for the difference.

    A subject sub-edge outside the hole survives as-is; a clip sub-edge
    inside the subject survives reversed, so the difference's boundary
    runs consistently. A midpoint sitting ON the other polygon (a
    tangency) is the degenerate case: raise rather than guess a side.
    """

    kept = []
    for a, b in subject_subedges:
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        relation = _point_ring_relation(mid, clip)
        if relation == "on":
            raise _DegenerateClip(
                "a cell edge runs tangent to an opening boundary"
            )
        if relation == "out":
            kept.append((a, b))
    for a, b in clip_subedges:
        mid = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        relation = _point_ring_relation(mid, subject)
        if relation == "on":
            raise _DegenerateClip(
                "an opening boundary runs tangent to a cell edge"
            )
        if relation == "in":
            kept.append((b, a))
    return kept


def _distance(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _stitch_rings(edges):
    """Chain kept directed edges into closed rings by endpoint identity.

    Matches within STITCH_TOL (1e-9 m): the edges reaching here were
    split at coordinates computed once and shared between both polygons,
    so a genuine match lands at or near machine precision. An edge whose
    end never finds its way back to a ring start is a degenerate walk:
    raise, the caller drops the whole cell.
    """

    remaining = list(edges)
    rings = []
    while remaining:
        start_edge = remaining.pop(0)
        ring = [start_edge[0], start_edge[1]]
        current_end = start_edge[1]
        while _distance(current_end, ring[0]) > STITCH_TOL:
            match_index = None
            for idx, (a, _b) in enumerate(remaining):
                if _distance(a, current_end) <= STITCH_TOL:
                    match_index = idx
                    break
            if match_index is None:
                raise _DegenerateClip(
                    "a clipped edge does not close back into a ring"
                )
            _a, b = remaining.pop(match_index)
            ring.append(b)
            current_end = b
        ring.pop()
        rings.append(ring)
    return rings


def _assign_holes(rings):
    """Sort stitched rings by containment into {"outline", "holes"} parts.

    A ring not contained by any other kept ring is a component outline; a
    ring contained by an outer ring becomes that component's hole. A
    single hole's difference against a single (simple) cell never nests
    more than one level deep, so first-containing-outer is unambiguous.
    """

    indexed = list(enumerate(rings))
    outers = []
    inners = []
    for i, ring in indexed:
        point = ring[0]
        contained = any(
            j != i and _in_ring(point, other) for j, other in indexed
        )
        if contained:
            inners.append(ring)
        else:
            outers.append(ring)
    components = []
    for outline in outers:
        holes = [ring for ring in inners if _in_ring(ring[0], outline)]
        components.append({"outline": outline, "holes": holes})
    return components


def _clip_cell_against_hole(subject, hole):
    """The core difference: subject ring minus hole ring.

    Returns ("cell_in_hole", None) when the cell is wholly consumed,
    ("unchanged", None) when the hole has no effect, or ("trimmed",
    components) with components a list of {"outline", "holes"} dicts
    (one for a bite, several for a split, one carrying a new hole ring
    when the opening was swallowed whole).
    """

    subject_subedges, clip_subedges, crossed = _split_edges(subject, hole)
    kept = _classify_subedges(subject_subedges, clip_subedges, subject, hole)
    if not kept:
        return "cell_in_hole", None
    if not crossed and len(kept) == len(subject):
        return "unchanged", None
    rings = _stitch_rings(kept)
    components = _assign_holes(rings)
    return "trimmed", components


def _attach_existing_holes(cell, components, hole):
    """Carry a cell's pre-existing "holes" rings onto the new components.

    These rings came from an earlier opening in the sequential
    application; the current difference only ever touched the outline.
    Each ring lands, unchanged, on whichever surviving component
    contains it (tested by its first vertex). Openings are validated
    disjoint by classify, so on real geometry an existing ring can never
    cross or fall inside the new hole; if one does, that is exactly the
    kind of adversarial configuration this module drops and names rather
    than mishandles.
    """

    for old_hole in cell.get("holes", []):
        vertex = old_hole[0]
        if _point_ring_relation(vertex, hole) in ("in", "on"):
            raise _DegenerateClip(
                "an existing interior ring falls inside the new opening"
            )
        if _rings_cross(old_hole, hole):
            raise _DegenerateClip(
                "an existing interior ring crosses the new opening boundary"
            )
        target = None
        for component in components:
            if _in_ring(vertex, component["outline"]):
                target = component
                break
        if target is None:
            raise _DegenerateClip(
                "an existing interior ring is not contained by any "
                "surviving component"
            )
        target["holes"].append(old_hole)


def _suffixed_key(base: str, index: int) -> str:
    """The base key at index 0, "b", "c", ... for the rest -- area-descending."""

    if index == 0:
        return base
    return base + chr(ord("a") + index)


def clip_cells(
    cells: List[Dict], hole_loops: List[List[List[float]]], target_size: float
) -> Tuple[List[Dict], Dict]:
    """Trim every cell against every opening: a plan-space polygon difference.

    Openings are validated disjoint by classify, so they apply to the
    cell list sequentially -- each hole clips every component the holes
    before it produced. For each (cell, hole) pair, a plan bounding-box
    miss skips that hole for that cell entirely (cheap pre-test); a hit
    runs the four-step difference (_split_edges, _classify_subedges,
    _stitch_rings, _assign_holes). A cell wholly inside a hole is dropped
    and counted; a component under 0.5% of the unclipped cell's area is
    a sliver, dropped and named; a degenerate walk drops and names the
    whole cell rather than crashing the cut.

    target_size is accepted for interface symmetry with the rest of the
    generator pipeline (courses, sizes); the difference itself has no
    target-size-scaled behaviour to tune.
    """

    del target_size

    report = {
        "openings": len(hole_loops),
        "cells_in_openings": 0,
        "cells_clipped": [],
        "opening_slivers": [],
        "opening_clip_failures": [],
    }
    clipped_seen = set()

    current = list(cells)
    for hole in hole_loops:
        hole_box = _bbox(hole)
        next_cells = []
        for cell in current:
            outline = cell["outline"]
            if not _bbox_overlap(_bbox(outline), hole_box):
                next_cells.append(cell)
                continue

            try:
                outcome, components = _clip_cell_against_hole(outline, hole)
            except _DegenerateClip:
                report["opening_clip_failures"].append(cell["key"])
                continue

            if outcome == "cell_in_hole":
                report["cells_in_openings"] += 1
                continue
            if outcome == "unchanged":
                next_cells.append(cell)
                continue

            try:
                _attach_existing_holes(cell, components, hole)
            except _DegenerateClip:
                report["opening_clip_failures"].append(cell["key"])
                continue

            unclipped_area = _shoelace_area(outline)
            threshold = SLIVER_FRACTION * unclipped_area
            components.sort(key=lambda c: _shoelace_area(c["outline"]), reverse=True)

            survivors = []
            for index, component in enumerate(components):
                key = _suffixed_key(cell["key"], index)
                if _shoelace_area(component["outline"]) < threshold:
                    report["opening_slivers"].append(key)
                    continue
                survivors.append(
                    {
                        "key": key,
                        "course": cell["course"],
                        "outline": component["outline"],
                        "holes": component["holes"],
                    }
                )

            if survivors and cell["key"] not in clipped_seen:
                report["cells_clipped"].append(cell["key"])
                clipped_seen.add(cell["key"])

            next_cells.extend(survivors)
        current = next_cells

    return current, report

    return outer_ring, hole_rings
