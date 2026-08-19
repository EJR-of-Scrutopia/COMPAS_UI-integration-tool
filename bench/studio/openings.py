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

Stdlib only, like every cutting-engine module: test_studio_guard.py
forbids solver stacks (compas, numpy, shapely, ...) on this path.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import tessellation


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
