"""The piece the viewer draws: a cap cut to its outline, on flat joints.

A drawn piece is built from its own cell, not from whatever mesh faces
happened to fall inside it. Its cap is a triangulation of the outline
lifted onto the thrust surface, so the vault keeps its curvature and the
heatmaps keep their resolution, and its boundary is the outline exactly.
Neighbours share boundary points because both took them from the same
welded cut, so their joints coincide rather than nearly coincide.

Thickness is not applied here. Each vertex ships as a surface point --
under K1 (cutting truth, 2026-08-17) the surface the formwork touches,
the intrados, recorded as provenance["surface"] == "intrados" -- plus a
unit normal, and the viewer extrudes upward by the full thickness, which
keeps thickness, taper and the joint gap client side.

K2 (cutting truth, 2026-08-17): a jointed piece (any cut whose pattern is
not monolithic-bands, i.e. one with real per-piece joints -- today only
bonded-courses) also ships a seat_plane: the least-squares plane through
its own lifted outline points, oriented outward. The viewer builds a true
prismatic block from this, belly and top both flat and parallel, rather
than K1's curved-surface offset. A flat cut on a curved form always
leaves a gap between the seat plane and the true surface -- the packing
or mortar bed the flat cut implies -- so seat_gap discloses the worst
distance from any of the piece's own cap points to its seat plane, and
seat_gap_stats in the report carries the distribution the same way
clamped_* does for the outline clamp. Sprayed concrete (monolithic-bands)
ships no seat_plane at all: it is moulded on the formwork, genuinely
curved, and has no flat seat to gap against.

A corner sits where two facets meet, and a single stored normal can only
lie in one of their two planes at once. So exactly one of a corner's
facets owns its normal, chosen by a rule both neighbours compute
identically, and the other facet is very slightly non planar at that one
point. The residual is measured and reported rather than assumed: it is
the sine of the angle between the stored normal and the non-owning
facet's plane, so a small residual means a small angle, not a distance.
On the four cell dome fixture in test_pieces.py, at rounds chosen by
choose_rounds, that residual comes out at about 0.0104, which is 0.598
degrees, at the corner where the c10/c11 joint meets the free rim, on
the steepest part of that fixture's dome. What is not optional is
agreement. A joint that is a fraction of a degree off flat is a
modelling nicety; a joint whose two sides disagree is broken.

report["corner_residual"] is the single worst corner across the whole
cut, same as it always was; a single number about a worst case badly
misrepresents the typical joint, so report["corner_residual_stats"]
(built by residual_stats over corner_residuals's own per-corner mapping)
carries the median, mean, p99, max and counts over a fixed set of
thresholds, and names which course the worst corner sits in. Measured on
the real Trial 2 export at 0.9 m: the typical corner (the median,
0.0196) is the same order as the synthetic fixture's own figure above
(0.0104), roughly double it rather than a tight match; a small cluster,
far higher, sits in the rim course, where the cut follows the mesh's own
irregular boundary rather than a straight chord. See
docs/BENCH.md and bench/scripts/cutting_measurements.py for the measured
distribution.

Stdlib only: the bundle imports this and the guard test forbids solver
stacks there.
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import cutting
import tessellation


def _cross(u, v):
    return [
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    ]


def _normalise(v) -> Optional[List[float]]:
    length = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) ** 0.5
    if length < 1e-12:
        return None
    return [v[0] / length, v[1] / length, v[2] / length]


def run_plane(corner_a, corner_b, chain_normals):
    """The joint plane for one facet: through both corners, along the shell.

    Built from the two corners and the average surface normal along the
    facet, which matters twice over. The plane contains its corners by
    construction, so the two facets meeting at a corner never disagree
    about where that corner goes. And the neighbouring cell walks the same
    facet from the other side: the chain is put in a canonical order
    before this is called, so both sides sum the same normals in the same
    order and land on a bit identical plane.
    """

    along = _normalise([corner_b[i] - corner_a[i] for i in range(3)])
    if along is None:
        return None
    average = [0.0, 0.0, 0.0]
    for normal in chain_normals:
        average = [average[i] + normal[i] for i in range(3)]
    average = _normalise(average)
    if average is None:
        return None
    plane_normal = _normalise(_cross(along, average))
    if plane_normal is None:
        return None
    return (list(corner_a), plane_normal)


def project_to_plane(point, plane):
    origin, normal = plane
    offset = sum((point[i] - origin[i]) * normal[i] for i in range(3))
    return [point[i] - offset * normal[i] for i in range(3)]


def project_direction(vector, plane):
    """The component of a direction lying in the plane, unit length.

    A wall is only flat if the offset direction lies in the joint plane as
    well as the point, otherwise its top and bottom edges bow apart.
    """

    _, normal = plane
    dot = sum(vector[i] * normal[i] for i in range(3))
    flattened = _normalise([vector[i] - dot * normal[i] for i in range(3)])
    return flattened if flattened is not None else list(vector)


def choose_rounds(tess: Dict, surface: cutting.Surface) -> Dict:
    """How many subdivision rounds the cap needs, by measurement.

    Start from the edge length rule, then refine while the measured chord
    deviation is still over the target and there are rounds left. Both the
    achieved deviation and which limit stopped it are reported, because a
    number that was never reached is worse than no number. "limit" says
    "rounds" whenever the round budget, not either target, is why a target
    is still missed: it is not just whichever loop happened to run last, or
    a cut that ran out of rounds during the edge pass alone would still be
    blamed on "edge" even though the edge target itself was never met.
    """

    points = tess["points"]
    longest = 0.0
    for cell in tess["cells"]:
        for a, b in cell["facets"]:
            longest = max(longest, math.hypot(
                points[a][0] - points[b][0], points[a][1] - points[b][1]))
    rounds = 0
    while rounds < cutting.MAX_ROUNDS and longest / (2 ** rounds) > cutting.CAP_EDGE_TARGET:
        rounds += 1
    edge_m = longest / (2 ** rounds)
    chord = _chord_deviation(tess, surface, rounds)
    while chord > cutting.CHORD_TARGET and rounds < cutting.MAX_ROUNDS:
        rounds += 1
        edge_m = longest / (2 ** rounds)
        chord = _chord_deviation(tess, surface, rounds)
    missed = edge_m > cutting.CAP_EDGE_TARGET or chord > cutting.CHORD_TARGET
    limit = "rounds" if (rounds >= cutting.MAX_ROUNDS and missed) else "edge"
    return {
        "rounds": rounds,
        "chord_mm": chord * 1000.0,
        "edge_m": edge_m,
        "limit": limit,
    }


def _chord_deviation(tess: Dict, surface: cutting.Surface, rounds: int) -> float:
    """How far the cap cuts inside the surface, on a sample of the cut.

    Measured by lifting each sampled triangle's own plan centroid and
    taking its distance to the plane of that triangle's three lifted
    corners. A sample rather than the whole tessellation because the round
    count is global, so a few hundred triangles settle it.
    """

    worst = 0.0
    sampled = 0
    for cell in tess["cells"]:
        if sampled > 200:
            break
        points, triangles, _ = _cap(tess, cell, rounds)
        lifted = [_lift(surface, p) for p in points]
        for a, b, c in triangles:
            sampled += 1
            pa, pb, pc = lifted[a]["point"], lifted[b]["point"], lifted[c]["point"]
            normal = _normalise(_cross(
                [pb[i] - pa[i] for i in range(3)],
                [pc[i] - pa[i] for i in range(3)],
            ))
            if normal is None:
                continue
            centre = [
                (points[a][0] + points[b][0] + points[c][0]) / 3.0,
                (points[a][1] + points[b][1] + points[c][1]) / 3.0,
            ]
            on_surface = _lift(surface, centre)["point"]
            worst = max(worst, abs(sum(
                (on_surface[i] - pa[i]) * normal[i] for i in range(3))))
    return worst


def _lift(surface: cutting.Surface, plan) -> Dict:
    found = surface.lift(plan[0], plan[1])
    return {
        "point": [plan[0], plan[1], found["z"]],
        "normal": found["normal"],
        "weights": found["weights"],
        "clamped": found["clamped"],
        "clamp_m": found["clamp_m"],
        # K3 (cutting truth, 2026-08-17): whether this point was pulled
        # onto the surface by the new boundary-polyline projection rather
        # than the old nearest-face clamp -- see cutting.Surface.lift.
        "projected": found["projected"],
        "projected_m": found["projected_m"],
    }


def _cap(tess: Dict, cell: Dict, rounds: int):
    """The cell's plan triangulation and its boundary chains.

    build_tessellation deliberately reports slivers rather than rejecting
    them, so this module has to cope with one reaching here: a ring too
    degenerate to triangulate raises from cutting.ear_clip with no idea
    which cell it came from, so that is caught here and re-raised naming
    the cell key, which is the one piece of context this function alone
    has.
    """

    points = [list(p) for p in tess["points"]]
    ring = cutting.bridge_holes(cell["outline"], cell["holes"], points) \
        if cell["holes"] else list(cell["outline"])
    try:
        triangles = cutting.ear_clip(ring, points)
    except (IndexError, ValueError) as error:
        raise ValueError(
            "cell {!r} could not be triangulated: {}".format(cell["key"], error)
        ) from error
    chains = [list(cell["outline"])] + [list(hole) for hole in cell["holes"]]
    return cutting.subdivide(points, triangles, chains, rounds)


def _facet_chain(chain: Sequence[int], per_facet: int) -> List[List[int]]:
    """Split a subdivided ring back into one run of points per facet.

    Assumes every facet was subdivided into exactly per_facet segments,
    which holds only while the round count is global (see subdivide):
    every chain edge splits every round, so a ring's length is always a
    whole multiple of per_facet. Enforced here rather than left advisory,
    because a ring that is not would silently hand back a wrap run whose
    two ends are not a real facet, which then drops out through
    planes.get with no signal that anything was wrong.
    """

    if len(chain) % per_facet:
        # A raise, not an assert: python -O drops asserts, and this one
        # guards exactly the silent failure the docstring above describes,
        # which would then ship rather than stop.
        raise ValueError(
            "a subdivided ring of {} points is not a whole multiple of {} "
            "points per facet; the round count is no longer global".format(
                len(chain), per_facet
            )
        )
    out = []
    for start in range(0, len(chain), per_facet):
        run = chain[start:start + per_facet]
        run.append(chain[(start + per_facet) % len(chain)])
        out.append(run)
    return out


def facet_planes(tess: Dict, surface: cutting.Surface) -> Dict[Tuple[int, int], tuple]:
    """One plane per facet, computed once, globally, from both ends.

    Canonical order is by welded point id, so the cell on either side
    feeds run_plane the identical sequence and gets a bit identical plane
    back. Computing this per cell, in whatever order that cell happened to
    walk its own boundary, is exactly how two neighbours end up with
    joints that nearly match.
    """

    points = tess["points"]
    planes: Dict[Tuple[int, int], tuple] = {}
    for facet in {f for cell in tess["cells"] for f in cell["facets"]}:
        a, b = facet                      # already canonical: a < b
        lifted_a = _lift(surface, points[a])
        lifted_b = _lift(surface, points[b])
        plane = run_plane(
            lifted_a["point"], lifted_b["point"],
            [lifted_a["normal"], lifted_b["normal"]],
        )
        if plane is not None:
            planes[facet] = plane
    return planes


def corner_owners(tess: Dict) -> Dict[int, Tuple[int, int]]:
    """The one facet each corner's normal is flattened into.

    A corner joins two facets and one direction cannot lie in both planes,
    so one of them has to own it. The choice is the smallest facet key
    touching that corner, which both neighbours compute identically
    without comparing notes.
    """

    owner: Dict[int, Tuple[int, int]] = {}
    for facet in sorted({f for cell in tess["cells"] for f in cell["facets"]}):
        for corner in facet:
            if corner not in owner or facet < owner[corner]:
                owner[corner] = facet
    return owner


def corner_residuals(
    tess: Dict,
    surface: cutting.Surface,
    planes: Optional[Dict[Tuple[int, int], tuple]] = None,
    owners: Optional[Dict[int, Tuple[int, int]]] = None,
) -> Dict[int, float]:
    """Every corner's own worst disagreement, one value per corner.

    A corner's stored normal is the raw surface normal flattened into its
    owning facet's plane (see corner_owners). This measures, for every
    OTHER facet across the WHOLE tessellation that also touches that
    corner (not only the facets of whichever cell happens to be walking
    it), how far that stored normal lies out of the other facet's own
    plane, and keeps the worst one. Corners with no owning facet, or whose
    owning facet has no computed plane, are absent from the returned
    mapping: nothing was ever stored for them to disagree with.

    max(corner_residuals(...).values()) is exactly the single number
    report["corner_residual"] has always carried; this just keeps the
    per-corner values apart instead of folding them into one running
    maximum, so the distribution across every corner can be reported too.
    """

    if planes is None:
        planes = facet_planes(tess, surface)
    if owners is None:
        owners = corner_owners(tess)

    facets_by_corner: Dict[int, List[Tuple[int, int]]] = {}
    for cell in tess["cells"]:
        for facet in cell["facets"]:
            for corner in facet:
                facets_by_corner.setdefault(corner, []).append(facet)

    points = tess["points"]
    out: Dict[int, float] = {}
    for corner, facet in owners.items():
        if facet not in planes:
            continue
        lifted = _lift(surface, points[corner])
        stored = project_direction(lifted["normal"], planes[facet])
        worst = 0.0
        for other in facets_by_corner.get(corner, ()):
            if other == facet or other not in planes:
                continue
            _, plane_normal = planes[other]
            worst = max(worst, abs(sum(
                stored[axis] * plane_normal[axis] for axis in range(3))))
        out[corner] = worst
    return out


RESIDUAL_THRESHOLDS = (0.01, 0.05, 0.10, 0.20, 0.30)
# The break points a review found the plain max obscures: most corners sit
# well under 0.01 (0.6 degrees), and the counts above each of these name
# how the tail actually grows rather than leaving it to one worst number.


def residual_stats(values: Sequence[float]) -> Dict:
    """count/min/median/mean/p99/max over a set of residuals, plus how many
    sit strictly over each of RESIDUAL_THRESHOLDS.

    Nearest rank percentile (the smallest value at or past the 99th
    percentile position), not an interpolated one: "the top 1 percent"
    read as a plain count of corners, not a fractional one.
    """

    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return {
            "count": 0, "min": 0.0, "median": 0.0, "mean": 0.0,
            "p99": 0.0, "max": 0.0,
            "over": [{"threshold": t, "count": 0} for t in RESIDUAL_THRESHOLDS],
        }
    median = (
        ordered[n // 2] if n % 2
        else 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])
    )
    p99 = ordered[min(n - 1, math.ceil(0.99 * n) - 1)]
    return {
        "count": n,
        "min": ordered[0],
        "median": median,
        "mean": sum(ordered) / n,
        "p99": p99,
        "max": ordered[-1],
        "over": [
            {"threshold": t, "count": sum(1 for v in ordered if v > t)}
            for t in RESIDUAL_THRESHOLDS
        ],
    }


def _courses_touching(tess: Dict, corner: int) -> List[int]:
    """Every course with a cell that has this corner on its own boundary,
    sorted, lowest (rimward) first. A corner on a shared joint can touch
    cells from more than one course."""

    courses = set()
    for cell in tess["cells"]:
        if corner in cell["outline"] or any(
            corner in hole for hole in cell["holes"]
        ):
            courses.add(cell["course"])
    return sorted(courses)


def _mean_vector(vectors) -> List[float]:
    total = [0.0, 0.0, 0.0]
    for vector in vectors:
        total = [total[i] + vector[i] for i in range(3)]
    return total


def _reference_normal(normals) -> List[float]:
    """A stand-in outward direction for orienting a fitted plane's sign:
    the mean of the piece's own shipped normals, unit length. Only the
    SIGN of the dot product against this matters (see fit_seat_plane), so
    a mean that is not itself perfectly unit length is not a problem; only
    a genuinely zero mean (normals that cancel out exactly) needs a
    fallback, which is arbitrary because there is no honest outward
    direction left to prefer."""

    unit = _normalise(_mean_vector(normals))
    return unit if unit is not None else [0.0, 0.0, 1.0]


def _smallest_symmetric_eigenpair(a00, a01, a02, a11, a12, a22):
    """The eigenvalue nearest zero and its unit eigenvector, for a 3x3 real
    symmetric matrix, in closed form.

    No numpy or scipy: bench/studio is barred from importing a solver
    stack at all (tests/studio/test_studio_guard.py), so this is the
    standard trigonometric solution for a symmetric 3x3's eigenvalues
    (Eberly, "A Robust Eigensolver for 3x3 Symmetric Matrices"; the same
    closed form is in Wikipedia's Eigenvalue algorithm article), followed
    by the null space of (A - eig*I) for the matching eigenvector, taken
    as whichever pair of that matrix's three rows has the largest cross
    product -- the most nearly orthogonal pair available, and so the most
    numerically stable choice of the three.
    """

    p1 = a01 * a01 + a02 * a02 + a12 * a12
    if p1 < 1e-24:
        # Already diagonal: the smallest diagonal entry is the smallest
        # eigenvalue and its own axis is the eigenvector -- UNLESS it ties
        # with the next smallest (within a tolerance relative to the
        # matrix's own scale), in which case two axes vary equally little
        # and no single direction is uniquely the least-varying one: a
        # genuinely degenerate spread (e.g. a sliver piece with near-zero
        # extent along two axes at once), not a plane to report. Minor,
        # fix round 1 on K2 (2026-08-17): this branch used to pick
        # whichever tied axis Python's min() happened to see first,
        # silently shipping an arbitrary (and not necessarily physical)
        # plane where fit_seat_plane's own docstring already promised
        # None; the general (non-diagonal) branch below does not have
        # this gap, since a symmetric matrix's tied eigenvalue always
        # makes (A - eig*I) rank-deficient enough that every pairwise row
        # cross product comes back zero, which _normalise already turns
        # into None.
        ordered = sorted((a00, a11, a22))
        spread = max(a00, a11, a22, 1e-18)
        if ordered[1] - ordered[0] < 1e-9 * spread:
            return ordered[0], None
        if ordered[0] == a00:
            return a00, (1.0, 0.0, 0.0)
        if ordered[0] == a11:
            return a11, (0.0, 1.0, 0.0)
        return a22, (0.0, 0.0, 1.0)

    q = (a00 + a11 + a22) / 3.0
    p2 = (a00 - q) ** 2 + (a11 - q) ** 2 + (a22 - q) ** 2 + 2.0 * p1
    p = math.sqrt(p2 / 6.0)
    b00, b01, b02 = (a00 - q) / p, a01 / p, a02 / p
    b11, b12 = (a11 - q) / p, a12 / p
    b22 = (a22 - q) / p
    det_b = (
        b00 * (b11 * b22 - b12 * b12)
        - b01 * (b01 * b22 - b12 * b02)
        + b02 * (b01 * b12 - b11 * b02)
    )
    # In exact arithmetic for a symmetric matrix -1 <= r <= 1; clamped
    # because floating point error can leave it a hair outside that range,
    # which acos would otherwise turn into a NaN.
    r = max(-1.0, min(1.0, det_b / 2.0))
    phi = math.acos(r) / 3.0
    # The three eigenvalues are q + 2p*cos(phi + k*2*pi/3) for k = 0, 1, 2;
    # cos is strictly decreasing over phi's range of [0, pi/3], so k = 0 is
    # always the largest root and k = 1 (used below) is always the
    # smallest -- this ordering is exact, not just the common case.
    eig_smallest = q + 2.0 * p * math.cos(phi + 2.0 * math.pi / 3.0)

    m00, m11, m22 = a00 - eig_smallest, a11 - eig_smallest, a22 - eig_smallest
    row0, row1, row2 = (m00, a01, a02), (a01, m11, a12), (a02, a12, m22)
    candidates = [_cross(row0, row1), _cross(row0, row2), _cross(row1, row2)]
    best = max(candidates, key=lambda v: v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    vector = _normalise(best)
    return eig_smallest, (tuple(vector) if vector is not None else None)


def fit_seat_plane(points: Sequence[Sequence[float]], reference_normal: Sequence[float]):
    """The least-squares plane through points: centroid plus the unit
    normal minimising the sum of squared perpendicular distances, oriented
    to agree with reference_normal (a piece's own outward surface normal,
    averaged) rather than carrying the eigensolve's arbitrary sign.

    The normal is the eigenvector of the SMALLEST eigenvalue of the
    points' own covariance matrix about their centroid: that eigenvalue is
    the variance of the points along its eigenvector, so minimising it is
    exactly minimising the spread the plane has to explain away, which is
    the least-squares fit by definition.

    None on fewer than three points, or on a genuinely degenerate spread
    (every point coincident or collinear, so no direction is uniquely the
    least-varying one): there is no plane to report, and the caller ships
    no seat_plane for that piece rather than a meaningless one.
    """

    n = len(points)
    if n < 3:
        return None
    cx = sum(p[0] for p in points) / n
    cy = sum(p[1] for p in points) / n
    cz = sum(p[2] for p in points) / n

    xx = xy = xz = yy = yz = zz = 0.0
    for p in points:
        dx, dy, dz = p[0] - cx, p[1] - cy, p[2] - cz
        xx += dx * dx
        xy += dx * dy
        xz += dx * dz
        yy += dy * dy
        yz += dy * dz
        zz += dz * dz

    _, normal = _smallest_symmetric_eigenpair(xx, xy, xz, yy, yz, zz)
    if normal is None:
        return None
    if sum(normal[i] * reference_normal[i] for i in range(3)) < 0.0:
        normal = (-normal[0], -normal[1], -normal[2])
    return [cx, cy, cz], list(normal)


def segment_pieces(
    tess: Dict,
    surface: cutting.Surface,
    support_points: Sequence[Sequence[float]],
) -> Tuple[List[Dict], Dict]:
    """One drawn piece per cell, in placement order, with its cut disclosed.

    is_support marks a cell if any support point lands inside it or on its
    boundary: tessellation.point_in_cell counts an edge or corner as
    inside, so a support that sits exactly on a joint marks every cell
    that shares that joint, not just one of them. That is the same rule
    the ring and wedge binning this replaces used, kept because four later
    tasks read this flag.
    """

    chosen = choose_rounds(tess, surface)
    rounds = chosen["rounds"]
    planes = facet_planes(tess, surface)
    owners = corner_owners(tess)
    welded = len(tess["points"])
    per_facet = 2 ** rounds

    # K2: a cut is either segmented into individually cast, jointed pieces
    # (bonded-courses today) or built as continuous monolithic-bands
    # (sprayed concrete); the two are structurally different cuts
    # (generators.py), never mixed within one tessellation, so this is
    # decided once for the whole cut rather than cell by cell. An
    # authored/imported cut with no pattern of its own name is treated as
    # jointed by default: an unnamed cut is not known to be seamless.
    jointed = tess.get("pattern") != "monolithic-bands"
    seat_gaps: List[float] = []

    # Computed once, globally, ahead of the per-cell loop below: one value
    # per corner rather than folded cell by cell into a single running
    # maximum, so the distribution across every corner survives to the
    # report (see corner_residuals's own docstring for why this is the
    # same number as before, just kept apart).
    residuals_by_corner = corner_residuals(tess, surface, planes, owners)

    clamp_reach: List[float] = []
    projected_reach: List[float] = []
    missing_planes = 0
    facet_counts: List[int] = []
    boundary_counts: List[int] = []
    piece_courses: List[int] = []
    out: List[Dict] = []

    for cell in tess["cells"]:
        points, triangles, chains = _cap(tess, cell, rounds)
        used = sorted({index for triangle in triangles for index in triangle})
        position = {index: i for i, index in enumerate(used)}
        lifted = {index: _lift(surface, points[index]) for index in used}
        clamp_reach.extend(
            lifted[index]["clamp_m"] for index in used if lifted[index]["clamped"]
        )
        projected_reach.extend(
            lifted[index]["projected_m"] for index in used if lifted[index]["projected"]
        )

        mid = {index: list(lifted[index]["point"]) for index in used}
        normals = {index: list(lifted[index]["normal"]) for index in used}

        facets_here = 0
        boundary_here = 0
        for chain in chains:
            boundary_here += len(chain)
            for run in _facet_chain(chain, per_facet):
                a, b = run[0], run[-1]
                facet = (a, b) if a < b else (b, a)
                plane = planes.get(facet)
                if plane is None:
                    missing_planes += 1
                    continue
                facets_here += 1
                for index in run[1:-1]:
                    mid[index] = project_to_plane(mid[index], plane)
                    normals[index] = project_direction(normals[index], plane)

        for index in used:
            if index >= welded:
                continue                   # a subdivision point, not a corner
            facet = owners.get(index)
            if facet is None or facet not in planes:
                continue
            # The stored normal a drawn casting actually ships; the
            # disagreement this creates with a corner's OTHER facets is
            # measured once, globally, in residuals_by_corner above, not
            # here cell by cell.
            normals[index] = project_direction(normals[index], planes[facet])

        faces: List[List[int]] = []
        count = len(used)
        for a, b, c in triangles:
            faces.append([position[a], position[b], position[c]])
            faces.append([
                position[c] + count, position[b] + count, position[a] + count])
        for chain in chains:
            for i in range(len(chain)):
                u, v = position[chain[i]], position[chain[(i + 1) % len(chain)]]
                faces.append([v, u, u + count, v + count])

        is_support = any(
            tessellation.point_in_cell(point, cell, tess["points"])
            for point in support_points
        )

        facet_counts.append(facets_here)
        boundary_counts.append(boundary_here)
        piece_courses.append(cell["course"])

        # K2: the seat plane is fit through the piece's own OUTLINE points
        # only (the rim, on every one of its chains -- boundary plus any
        # holes), not the fully interior subdivision points, because the
        # outline is the piece's actual resting footprint; the seat_gap
        # that plane is measured against, below, covers every cap point
        # instead, since an interior point (unconstrained by any facet
        # joint) is exactly where a doubly curved surface can bulge
        # furthest from a plane fit only through its rim.
        seat_plane = None
        seat_gap = None
        if jointed:
            outline_indices = sorted({index for chain in chains for index in chain})
            fit = fit_seat_plane(
                [mid[index] for index in outline_indices],
                _reference_normal(normals[index] for index in used),
            )
            if fit is not None:
                origin, normal = fit
                seat_gap = max(
                    abs(sum(
                        (mid[index][axis] - origin[axis]) * normal[axis]
                        for axis in range(3)
                    ))
                    for index in used
                )
                seat_plane = {"origin": origin, "normal": normal}
                seat_gaps.append(seat_gap)

        out.append({
            "key": cell["key"],
            "course": cell["course"],
            "mid": [mid[index] for index in used],
            "normals": [normals[index] for index in used],
            "sources": [lifted[index]["weights"] for index in used],
            "faces": faces,
            "is_support": is_support,
            # Sprayed (monolithic-bands) pieces, and any jointed piece the
            # fit above could not find a plane for, ship neither key: the
            # client keys buildPieceMeshes's prism-vs-curved-shell choice
            # on whether seat_plane is present, so an absent key is a real
            # signal, not a null placeholder.
            **({"seat_plane": seat_plane, "seat_gap": seat_gap} if seat_plane is not None else {}),
        })

    residual = max(residuals_by_corner.values()) if residuals_by_corner else 0.0
    stats = residual_stats(residuals_by_corner.values())
    if residuals_by_corner:
        worst_corner = max(residuals_by_corner, key=residuals_by_corner.get)
        stats["worst_corner_courses"] = _courses_touching(tess, worst_corner)
    else:
        stats["worst_corner_courses"] = []

    report = {
        # facets_per_piece is the number to compare against the ring and
        # wedge binning this replaces, whose cells carried 30 to 86
        # boundary edges. boundary_points_per_piece counts every
        # subdivided boundary point, not joints, so a five facet cell
        # reports around 40 there: read facets_per_piece for the headline.
        # max_course names which course the largest piece belongs to: a
        # rim course cell following the mesh's own irregular boundary
        # carries more facets than a straight-chorded interior one, so the
        # max alone reads as typical unless its course is named alongside
        # the median.
        "facets_per_piece": _spread(facet_counts, piece_courses),
        "boundary_points_per_piece": _spread(boundary_counts),
        # corner_residual is the single worst corner across the whole cut,
        # unchanged in meaning from before this report. corner_residual_stats
        # is the distribution that number was pulled from: the median
        # describes the typical joint, corner_residual (== stats["max"])
        # describes only its own worst one, and worst_corner_courses names
        # which course that worst corner sits in (see corner_residuals and
        # residual_stats above, and the module docstring).
        "corner_residual": residual,
        "corner_residual_stats": stats,
        "chord_mm": chosen["chord_mm"],
        "rounds": rounds,
        "edge_m": chosen["edge_m"],
        "limit": chosen["limit"],
        # clamped_points counts the cap points that landed off the render
        # mesh and were pulled back onto it (see cutting.Surface.lift).
        # clamped_max_m and clamped_median_m say by how far, in metres,
        # over exactly that population: a count with no magnitude cannot be
        # read, because the same points are either rounding noise or many
        # times the chord target depending on a number the report did not
        # carry before this was measured.
        #
        # K3 (cutting truth, 2026-08-17): before this task these three
        # fields counted every off-mesh cap point (137 on the real Trial 2
        # export at 0.9 m, up to 52.3 mm out), because the only fallback
        # was the nearest-face clamp. That clamp is now the LAST resort
        # (no boundary polyline attached, or the projection below still
        # missed the mesh), so these should read zero or near it on any
        # cut whose surface carries a boundary; a residual handful is
        # disclosed here, not hidden, same as before. See projected_*
        # immediately below for where the population that used to land
        # here now goes.
        "clamped_points": len(clamp_reach),
        "clamped_max_m": max(clamp_reach) if clamp_reach else 0.0,
        "clamped_median_m": _median(clamp_reach),
        # K3: the cap points that landed off the render mesh and were
        # projected to the nearest point of the analysis mesh's own
        # boundary polyline instead of clamped -- the mechanism that
        # replaces the old clamp for a real cut (cutting.Surface.lift).
        # projected_max_m and projected_median_m are the same shape as
        # clamped_max_m/clamped_median_m, over this population instead: a
        # projected point sits on the true rim, so this is a much smaller
        # number than the clamp it replaces, not merely a renamed count.
        "projected_points": len(projected_reach),
        "projected_max_m": max(projected_reach) if projected_reach else 0.0,
        "projected_median_m": _median(projected_reach),
        "missing_planes": missing_planes,
        # K2: the distribution of seat_gap over every jointed piece --
        # count 0 for a cut with no jointed pieces at all (a sprayed,
        # monolithic-bands cut stays curved and moulded, with no flat
        # seat to gap against), matching clamped_* above's shape for the
        # outline clamp: a bare count cannot be read, the median says what
        # a typical piece's flat cut costs it, and the max says the worst.
        "seat_gap_stats": {
            "count": len(seat_gaps),
            "median": _median(seat_gaps),
            "max": max(seat_gaps) if seat_gaps else 0.0,
        },
    }
    return out, report


def _median(values: Sequence[float]) -> float:
    """The plain median, 0.0 over nothing. Averaged across the two middles
    on an even count, the same rule residual_stats uses."""

    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    if n % 2:
        return ordered[n // 2]
    return 0.5 * (ordered[n // 2 - 1] + ordered[n // 2])


def _spread(
    values: Sequence[int], courses: Optional[Sequence[int]] = None
) -> Dict:
    """min/median/max over values; with courses (parallel to values), also
    the course of one piece that reaches the max, so a reader is not left
    to assume the max is typical when it belongs to a course of its own."""

    if not values:
        return {"min": 0, "median": 0, "max": 0}
    ordered = sorted(values)
    result = {
        "min": ordered[0],
        "median": ordered[len(ordered) // 2],
        "max": ordered[-1],
    }
    if courses is not None:
        result["max_course"] = courses[values.index(ordered[-1])]
    return result
