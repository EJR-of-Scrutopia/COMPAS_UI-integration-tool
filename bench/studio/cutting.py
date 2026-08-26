"""One cell outline becomes one cap that follows the thrust surface.

Three moves. Holes are bridged into a single ring so an ordinary ear clip
can triangulate it. The ear clip runs on the coarse outline, so the
triangles start well shaped rather than as a fan of slivers. Then uniform
one to four subdivision refines every triangle at once.

Uniform subdivision, and not the longest edge bisection the spec sketched,
because it is conformal with no bookkeeping: every edge splits at its
midpoint, both triangles sharing an edge see the same midpoint, and so do
both PIECES sharing a boundary edge, since a midpoint is the plain average
of its two ends and IEEE 754 addition is commutative. Two neighbours
therefore land on bit identical boundary points without comparing notes.

Stdlib only: the bundle path imports this.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import spatial

CAP_EDGE_TARGET = 0.30    # metres: the edge length subdivision aims at
CHORD_TARGET = 0.005      # metres: how far a cap may cut inside the surface
MAX_ROUNDS = 3            # 4 ** 3 triangles per ear clipped triangle


def _area2(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _inside_triangle(p, a, b, c, inclusive: bool = False) -> bool:
    total = _area2(a, b, c)
    if abs(total) < 1e-18:
        return False
    u = _area2(p, b, c) / total
    v = _area2(a, p, c) / total
    w = _area2(a, b, p) / total
    limit = -1e-12 if inclusive else 1e-12
    return u > limit and v > limit and w > limit


_COLLINEAR_TOL = 1e-6   # metres: matches tessellation.TOL, the weld tolerance
                        # a T junction point was itself resolved to


def ear_clip(ring: Sequence[int], points) -> List[Tuple[int, int, int]]:
    """Triangulate a simple ring, largest ear first.

    A T junction leaves a straight 180 degree vertex in the outline, whose
    ear has exactly zero area under any ordering. Plain ear clipping can
    therefore never remove it as a tip: the area <= 0.0 skip excludes it
    from the loop, but the loop still has to end somewhere, and the final
    triangle it appends is not checked, so a ring that reduces to exactly
    that vertex and its two collinear neighbours ships a triangle with no
    area at all. That vertex's later subdivision points then sit outside
    the welded count, so the corner ownership pass skips them and a
    neighbour on the other side of that joint can end up storing a
    different normal for a point this piece also claims to own, which is
    the one thing this module exists to prevent.

    So every straight vertex is set aside first, the remaining ring is ear
    clipped as usual (it now has no zero area ears to trip over), and each
    set aside vertex is spliced back in by splitting the one triangle whose
    boundary edge it lies on. That keeps every ring vertex a real corner of
    at least one triangle with area, with no degenerate triangle produced.

    Largest ear first matters for triangle quality otherwise: taking the
    biggest available ear avoids carving off slivers. Since these caps are
    subdivided and then lifted onto a surface, sliver triangles would
    produce noisy surface normals on the drawn casting.
    """

    indices = list(ring)
    if sum(
        points[indices[i]][0] * points[indices[(i + 1) % len(indices)]][1]
        - points[indices[(i + 1) % len(indices)]][0] * points[indices[i]][1]
        for i in range(len(indices))
    ) < 0:
        indices.reverse()

    n = len(indices)
    collinear = [False] * n
    for i in range(n):
        a, b, c = indices[i - 1], indices[i], indices[(i + 1) % n]
        base = math.hypot(points[c][0] - points[a][0], points[c][1] - points[a][1])
        if base > 1e-12:
            height = abs(_area2(points[a], points[b], points[c])) / base
            collinear[i] = height < _COLLINEAR_TOL

    simplified = [indices[i] for i in range(n) if not collinear[i]]
    if len(simplified) < 3:
        raise ValueError(
            "a ring with only {} non collinear point(s) cannot be "
            "triangulated".format(len(simplified))
        )

    triangles = _ear_clip_simplified(simplified, points)

    # Splice the straight vertices back in, in ring order starting from a
    # survivor, so a run of several on one edge lands in order along it:
    # the first split creates the very edge the next one needs, rather
    # than the original, now gone, edge between the two far corners.
    start = next(i for i in range(n) if not collinear[i])
    for step in range(n):
        i = (start + step) % n
        if not collinear[i]:
            continue
        left = indices[(i - 1) % n]
        j = (i + 1) % n
        while collinear[j]:
            j = (j + 1) % n
        right = indices[j]
        triangles = _split_edge(triangles, left, right, indices[i])

    return triangles


def _ear_clip_simplified(indices: List[int], points) -> List[Tuple[int, int, int]]:
    """The classic ear clip loop, on a ring already wound and free of any
    straight vertex, so every ear it considers has real area."""

    indices = list(indices)
    triangles: List[Tuple[int, int, int]] = []
    # Guard against infinite loops if the loop body changes: each iteration
    # either raises or removes exactly one index, so the loop terminates.
    guard = len(indices) * len(indices) + 16
    while len(indices) > 3:
        guard -= 1
        if guard < 0:
            raise ValueError("ear clipping did not terminate: the ring is not simple")
        best = None
        for i in range(len(indices)):
            a = indices[i - 1]
            b = indices[i]
            c = indices[(i + 1) % len(indices)]
            area = _area2(points[a], points[b], points[c])
            if area <= 0.0:
                continue
            blocked = False
            for other in indices:
                if other in (a, b, c):
                    continue
                if _inside_triangle(points[other], points[a], points[b], points[c]):
                    blocked = True
                    break
            if blocked:
                continue
            if best is None or area > best[0]:
                best = (area, i, (a, b, c))
        if best is None:
            raise ValueError("no ear found: the ring crosses itself")
        triangles.append(best[2])
        indices.pop(best[1])
    triangles.append((indices[0], indices[1], indices[2]))
    return triangles


def _split_edge(triangles, a, b, t):
    """Split the one triangle whose boundary edge runs from a to b.

    A ring's own boundary edge, unlike an internal ear-clip diagonal,
    belongs to exactly one triangle, in exactly this direction, so the
    first match is the only one: it is found regardless of which of the
    triangle's three cyclic positions the edge sits at, and the split
    always keeps the same winding as the triangle it replaces.
    """

    for index, (p, q, r) in enumerate(triangles):
        if (p, q) == (a, b):
            apex = r
        elif (q, r) == (a, b):
            apex = p
        elif (r, p) == (a, b):
            apex = q
        else:
            continue
        return triangles[:index] + [(a, t, apex), (t, b, apex)] + triangles[index + 1:]
    raise ValueError(
        "no triangle carries the boundary edge {} to {} to receive point {}".format(
            a, b, t
        )
    )


def bridge_holes(outline: Sequence[int], holes, points) -> List[int]:
    """Splice each hole into the outline, so one ear clip covers both.

    The standard bridge: from the hole's rightmost point, cast a ray to
    the right, take the outline edge it first meets, and join to whichever
    of that edge's ends is visible. The reflex refinement matters for
    spiky imported outlines; the concentric bands this studio generates
    are answered by the first candidate every time.

    Holes are taken rightmost first, and each is spliced into the ring the
    previous ones were already bridged into, so a later hole casts against
    a ring that includes those bridges. Two holes tied at the same maximum
    x, or a third hole behind two bridges, can leave the ray with no edge
    to take. _splice raises in that case rather than returning a corrupt
    ring, and it is told how many bridges the ring already carries so its
    message can say whose defect it is: with no bridges in the ring the
    hole really is outside its outline, and with bridges in it the
    bridging is as likely to be the limit as the outline is. The import
    contract documents multi-hole cells, so this is reachable.
    """

    ring = list(outline)
    ordered = sorted(holes, key=lambda h: -max(points[i][0] for i in h))
    for bridged, hole in enumerate(ordered):
        ring = _splice(ring, list(hole), points, bridged)
    return ring


def _splice(ring: List[int], hole: List[int], points, bridged: int = 0) -> List[int]:
    start = max(range(len(hole)), key=lambda i: points[hole[i]][0])
    m = hole[start]
    mx, my = points[m]

    best_at = None
    best_x = None
    for i in range(len(ring)):
        a = points[ring[i]]
        b = points[ring[(i + 1) % len(ring)]]
        if (a[1] > my) == (b[1] > my):
            continue
        crossing = a[0] + (my - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
        if crossing < mx:
            continue
        if best_x is None or crossing < best_x:
            best_x = crossing
            best_at = i if a[0] > b[0] else (i + 1) % len(ring)
    if best_at is None:
        if bridged:
            raise ValueError(
                "a hole could not be bridged into an outline that already "
                "carries {} bridge(s): the ray right from the hole's "
                "rightmost point met no edge of that ring to join to. Two "
                "holes reaching the same maximum x, or a third hole behind "
                "two bridges, can leave no candidate edge. That is a limit "
                "of this bridging, not necessarily a fault in the "
                "outline".format(bridged)
            )
        raise ValueError("a hole is not inside its outline")

    partner = points[ring[best_at]]
    corner = (best_x, my)
    best_tangent = None
    for i, index in enumerate(ring):
        if i == best_at:
            continue
        q = points[index]
        if not _inside_triangle(q, (mx, my), corner, partner, inclusive=True):
            continue
        previous = points[ring[i - 1]]
        following = points[ring[(i + 1) % len(ring)]]
        if _area2(previous, q, following) > 0:
            continue                       # convex, so it cannot block the bridge
        tangent = abs(q[1] - my) / (q[0] - mx) if q[0] != mx else float("inf")
        if best_tangent is None or tangent < best_tangent:
            best_tangent = tangent
            best_at = i
    rotated = hole[start:] + hole[:start]
    return ring[: best_at + 1] + rotated + [m] + ring[best_at:]


def subdivide(points, triangles, chains, rounds: int):
    """N rounds of one to four splitting, chains kept in step.

    chains are the boundary rings, in order. They are split with the same
    cached midpoints the triangles use, so the ring stays exactly the
    triangulation's boundary and the wall built on it stays watertight.
    """

    for _ in range(max(0, int(rounds))):
        cache: Dict[Tuple[int, int], int] = {}

        def midpoint(u: int, v: int) -> int:
            key = (u, v) if u < v else (v, u)
            found = cache.get(key)
            if found is not None:
                return found
            a, b = points[key[0]], points[key[1]]
            points.append([(a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0])
            cache[key] = len(points) - 1
            return cache[key]

        split: List[Tuple[int, int, int]] = []
        for a, b, c in triangles:
            ab, bc, ca = midpoint(a, b), midpoint(b, c), midpoint(c, a)
            split.extend([(a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca)])
        triangles = split

        grown = []
        for chain in chains:
            out = []
            for i in range(len(chain)):
                out.append(chain[i])
                out.append(midpoint(chain[i], chain[(i + 1) % len(chain)]))
            grown.append(out)
        chains = grown
    return points, triangles, chains


def _as_boundary_loops(boundary) -> List[Sequence[Sequence[float]]]:
    """self.boundary, normalized to a list of one or more closed polylines.

    self.boundary keeps its original single-loop shape untouched: a flat
    list of [x, y] points (every caller before this task, and every test
    in this file and test_pieces.py, sets it that way). Multi-loop
    (2026-08-19): a caller attaching more than one rim (bundle.py's outer
    rim plus every opening's own rim) sets a LIST of such polylines
    instead. The two shapes are told apart by their first element: a
    coordinate (a plain number) means a single flat polyline, the
    one-element case; a nested sequence means a list of polylines already.
    """

    if not boundary:
        return []
    if isinstance(boundary[0][0], (int, float)):
        return [boundary]
    return list(boundary)


class Surface:
    """The render mesh as a height field with barycentric field weights.

    A cut piece does not sit on mesh vertices, so every cap point asks the
    surface where it is: its height, its normal, and the weights that let
    a solved per vertex field be read at a point that is not a vertex.
    """

    def __init__(self, vertices: Sequence[Sequence[float]], faces: Sequence[Sequence[int]]):
        self.vertices = vertices
        self.faces = faces
        self.normals = _vertex_normals(vertices, faces)
        # K3 (cutting truth, 2026-08-17): the analysis mesh's own boundary
        # ring, projected to plan and ordered, so a cap point that lands
        # off this mesh can be projected to the nearest point of the real
        # rim (lift, below) instead of clamped into whichever face happens
        # to be nearest by centroid. None until a caller attaches one
        # (bundle.build_tessellation_for does, for every real cut); a
        # Surface built directly, the way this module's own tests and
        # pieces.py's fixtures do, keeps the old nearest-face clamp as its
        # only fallback, unchanged.
        #
        # Multi-loop (2026-08-19): a single-loop surface still attaches one
        # flat polyline here, a plain list of [x, y] points, exactly as
        # before -- every existing caller and test keeps setting it that
        # way. A surface with openings attaches a LIST of such polylines
        # instead (the outer rim plus every opening's own rim), so an
        # off-mesh probe near an opening projects onto that opening's true
        # boundary rather than the outer one. _as_boundary_loops (below)
        # tells the two shapes apart wherever self.boundary is read, so the
        # single-polyline form is simply the one-element case of the
        # multi-loop one; the attribute's name and its single-loop
        # semantics are unchanged.
        self.boundary: Optional[Sequence[Sequence[float]]] = None
        spread = max(
            max(v[0] for v in vertices) - min(v[0] for v in vertices),
            max(v[1] for v in vertices) - min(v[1] for v in vertices),
            1e-6,
        )
        self.grid = spatial.Grid(max(spread / 64.0, 1e-6))
        self.boxes: List[Tuple[float, float, float, float]] = []
        for index, face in enumerate(faces):
            xs = [vertices[i][0] for i in face]
            ys = [vertices[i][1] for i in face]
            box = (min(xs), min(ys), max(xs), max(ys))
            self.boxes.append(box)
            self.grid.insert(index, *box)

    def _triangles(self, face):
        for i in range(1, len(face) - 1):
            yield (face[0], face[i], face[i + 1])

    def _on_mesh(self, x: float, y: float) -> Optional[Dict]:
        """A sample if (x, y) lands inside some face's triangle, else None."""

        for index in self.grid.query(x, y, x, y):
            bx0, by0, bx1, by1 = self.boxes[index]
            # A grid candidate only shares a bucket with this point. Pad
            # the face's own box by the weld tolerance, because the
            # barycentric test below deliberately accepts a point that is
            # fractionally outside an edge rather than opening a seam.
            if not (
                bx0 - 1e-6 <= x <= bx1 + 1e-6
                and by0 - 1e-6 <= y <= by1 + 1e-6
            ):
                continue
            for a, b, c in self._triangles(self.faces[index]):
                weights = self._barycentric(x, y, a, b, c)
                if weights is not None and min(w for _, w in weights) >= -1e-9:
                    return self._sample(weights, False, 0.0, x, y)
        return None

    def lift(self, x: float, y: float) -> Dict:
        found = self._on_mesh(x, y)
        if found is not None:
            return found
        # Off the mesh. This is not a float's rounding: measured on the real
        # Trial 2 export at the default 0.9 m before this fix, 137 cap
        # points landed here, all of them genuinely outside the render
        # mesh, at 6e-14 m at the closest, 0.0246 m at the median and
        # 0.0523 m at the worst, and all but one of them inside the two
        # clusters at plus and minus 125.4 degrees where the rim notch is.
        #
        # The cause was upstream and deliberate. domain.radius_at used to
        # take the OUTERMOST ray crossing, so wherever the tolerated rim
        # wobble made the plan boundary multi-valued along a ray, an f = 1
        # outline point could be placed on the far crossing, past the near
        # one, and therefore past the real surface. That choice is what
        # stopped a ray grazing a corner from falling back inside the rim,
        # and it was not changed here (K3, 2026-08-17).
        #
        # Rim remainder (2026-08-19): radius_at now returns the first exit
        # instead (docs/superpowers/specs/2026-08-19-rim-remainder-design.
        # md), the near branch rather than a branch on the far side of a
        # gap the ray has already left the plan through, so most of what
        # used to need this projection at all no longer does -- measured on
        # the real Trial 2 export at 0.9 m, the worst overshoot this
        # fallback still reaches for fell from 46.4 mm to 8.7 mm.
        #
        # K3 (cutting truth, 2026-08-17): the point is projected to the
        # NEAREST point of the real rim (self.boundary, the analysis mesh's
        # own boundary polyline in plan, cached by whoever built this
        # surface) rather than clamped into whichever render face happens
        # to be nearest by centroid. The projected point sits on the true
        # silhouette, so it is looked up again with the same on-mesh
        # containment test that a well behaved point uses, not blended by
        # face-relative barycentric weights the way the old clamp was: that
        # blending is exactly what pulled a rim point up to 52 mm inward,
        # since "nearest face by centroid" is a poor proxy for "nearest
        # point of the boundary" wherever the render mesh's faces are not
        # small relative to the notch that put the point off the mesh in
        # the first place.
        #
        # Rim-rectangular fix (2026-08-18): before this fix, only the
        # SAMPLE (z, normal, weights) moved to (px, py); the caller kept
        # asking for the ORIGINAL (x, y) as the point's own drawn plan
        # position (see pieces._lift), so a cap point genuinely off the
        # render mesh still shipped at its own unprojected position. That
        # is the gap the cutting truth wave's own retrospective correction
        # named (docs/specs/2026-08-17-cutting-truth-design.md): "it is the
        # sample that moves to the rim, not the point itself". _on_mesh's
        # own _sample call below now carries (px, py) through as the
        # returned dict's own "x"/"y", so a caller that wants the point ON
        # the rim, not merely sampled there, can have it. Measured on the
        # real Trial 2 export: this population (417-658 points depending on
        # size, all in course 0) is the one this fix moves; it is not the
        # same defect as a wrongly chosen ray crossing landing exactly on
        # some OTHER real part of the true rim (a rarer, more severe, and
        # separately diagnosed case -- see
        # .superpowers/sdd/2026-08-18-rim-spikes/diagnosis.md -- which is
        # invisible to this containment test and is not fixed here).
        if self.boundary:
            px, py = self._nearest_boundary_point(x, y)
            found = self._on_mesh(px, py)
            if found is not None:
                found["projected"] = True
                found["projected_m"] = math.hypot(px - x, py - y)
                return found
            # The projected point itself did not land inside any triangle:
            # floating point at a seam, or a boundary polyline that does
            # not actually trace this surface's own mesh boundary. Fall
            # through to the old nearest-face clamp below rather than
            # raising or silently returning an unlifted point.

        # Clamp to the nearest face and measure it, rather than dropping
        # the point. This is the last resort now, reached only when no
        # boundary polyline was attached at all, or the projection above
        # still failed to land on the mesh.
        best = None
        best_distance = None
        for index, face in enumerate(self.faces):
            cx = sum(self.vertices[i][0] for i in face) / len(face)
            cy = sum(self.vertices[i][1] for i in face) / len(face)
            distance = (cx - x) ** 2 + (cy - y) ** 2
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best = face
        a, b, c = next(iter(self._triangles(best)))
        weights = self._barycentric(x, y, a, b, c) or [(a, 1.0)]
        clamped = [(index, min(1.0, max(0.0, weight))) for index, weight in weights]
        total = sum(weight for _, weight in clamped) or 1.0
        # The last resort keeps the OLD convention: the point's own plan
        # position is not moved, only its sample is blended from the
        # nearest face. Rim-rectangular fix (2026-08-18) only extends the
        # boundary-polyline projection above to move (x, y); this fallback
        # is reached rarely (no boundary attached, or the projection above
        # still missed the mesh) and its own reach is already disclosed via
        # clamp_m, so it is left as it was.
        return self._sample(
            [(i, w / total) for i, w in clamped], True, self._reach(x, y, best), x, y
        )

    def _nearest_boundary_point(self, x: float, y: float) -> Tuple[float, float]:
        """The point of self.boundary nearest (x, y), in plan.

        Each polyline self.boundary carries (see _as_boundary_loops) is a
        closed polygon (no point repeated at the end), so the segment from
        its last point back to its first is included by wrapping the
        index, the same convention domain.py's loop uses.

        Multi-loop (2026-08-19): with more than one polyline attached (an
        outer rim plus every opening's own rim), the nearest point is
        measured against every one of them and the global nearest wins, so
        a probe pushed off the mesh near an opening projects onto THAT
        opening's own boundary instead of the outer rim, which is exactly
        what made the old single-polyline projection wrong here (see
        test_an_off_mesh_point_projects_onto_the_nearest_opening_rim).
        """

        best_distance = None
        best_point = None
        for boundary in _as_boundary_loops(self.boundary):
            n = len(boundary)
            for i in range(n):
                a = boundary[i]
                b = boundary[(i + 1) % n]
                ex, ey = b[0] - a[0], b[1] - a[1]
                length2 = ex * ex + ey * ey
                if length2 < 1e-24:
                    near = (a[0], a[1])
                else:
                    along = min(1.0, max(0.0, ((x - a[0]) * ex + (y - a[1]) * ey) / length2))
                    near = (a[0] + along * ex, a[1] + along * ey)
                distance = (x - near[0]) ** 2 + (y - near[1]) ** 2
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_point = near
        return best_point

    def _reach(self, x: float, y: float, face) -> float:
        """How far, in plan and in metres, the clamp moved this point.

        The plan distance from the point to the outline of the face it was
        clamped onto. The fallback is only reached when no face's own
        triangles hold the point, so this is a distance outward: it is the
        size of the disagreement between where the cut asked for a point
        and where the surface actually ends.
        """

        ring = [self.vertices[i] for i in face]
        best = None
        for i in range(len(ring)):
            a, b = ring[i], ring[(i + 1) % len(ring)]
            ex, ey = b[0] - a[0], b[1] - a[1]
            length2 = ex * ex + ey * ey
            if length2 < 1e-24:
                near = a
            else:
                along = min(1.0, max(0.0, ((x - a[0]) * ex + (y - a[1]) * ey) / length2))
                near = (a[0] + along * ex, a[1] + along * ey)
            distance = math.hypot(x - near[0], y - near[1])
            if best is None or distance < best:
                best = distance
        return best if best is not None else 0.0

    def height(self, x: float, y: float) -> Optional[float]:
        # Optional is the callback contract for Task 7's tessellation reader,
        # not a claim that this implementation can return None.
        return self.lift(x, y)["z"]

    def _barycentric(self, x, y, a, b, c):
        pa, pb, pc = self.vertices[a], self.vertices[b], self.vertices[c]
        total = _area2(pa, pb, pc)
        if abs(total) < 1e-18:
            return None
        p = (x, y)
        return [
            (a, _area2(p, pb, pc) / total),
            (b, _area2(pa, p, pc) / total),
            (c, _area2(pa, pb, p) / total),
        ]

    def _sample(self, weights, clamped: bool, clamp_m: float, x: float, y: float) -> Dict:
        z = sum(self.vertices[i][2] * w for i, w in weights)
        normal = [
            sum(self.normals[i][axis] * w for i, w in weights) for axis in range(3)
        ]
        length = math.sqrt(sum(v * v for v in normal)) or 1.0
        return {
            "z": z,
            "normal": [v / length for v in normal],
            "weights": weights,
            "clamped": clamped,
            # Zero when the point was on the mesh, so a caller can sum or
            # sort these without asking about clamped first.
            "clamp_m": clamp_m,
            # K3 (cutting truth, 2026-08-17): set True/nonzero by lift's
            # boundary-projection branch after this dict is built, for the
            # same reason clamp_m defaults to zero here rather than being
            # left absent -- a caller should never have to ask "is this key
            # even present" before reading it.
            "projected": False,
            "projected_m": 0.0,
            # Rim-rectangular fix (2026-08-18): the plan position this
            # sample was actually taken at -- the ORIGINAL (x, y) lift() was
            # asked about when it landed on the mesh unaided or was clamped
            # by the last-resort face clamp, or the PROJECTED (x, y) when
            # the boundary-polyline projection is what found this sample.
            # Always present (the same "no absent keys" rule clamp_m and
            # projected_m already follow), so a caller can always ship this
            # point's actual plan position rather than assuming its own
            # unprojected request was correct.
            "x": x,
            "y": y,
        }


def _vertex_normals(vertices, faces):
    """Area weighted vertex normals, the same rule blocks.py uses."""

    out = [[0.0, 0.0, 0.0] for _ in vertices]
    for face in faces:
        for i in range(1, len(face) - 1):
            a, b, c = vertices[face[0]], vertices[face[i]], vertices[face[i + 1]]
            u = [b[axis] - a[axis] for axis in range(3)]
            v = [c[axis] - a[axis] for axis in range(3)]
            cross = [
                u[1] * v[2] - u[2] * v[1],
                u[2] * v[0] - u[0] * v[2],
                u[0] * v[1] - u[1] * v[0],
            ]
            for index in (face[0], face[i], face[i + 1]):
                for axis in range(3):
                    out[index][axis] += cross[axis]
    for normal in out:
        length = math.sqrt(sum(v * v for v in normal))
        if length > 1e-12:
            for axis in range(3):
                normal[axis] /= length
        else:
            normal[2] = 1.0
    return out
