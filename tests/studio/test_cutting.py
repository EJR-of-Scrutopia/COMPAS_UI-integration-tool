"""cutting.py turns one outline into a cap that follows the surface."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def studio():
    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import cutting
    return cutting


def area_of(points, triangles):
    total = 0.0
    for a, b, c in triangles:
        pa, pb, pc = points[a], points[b], points[c]
        total += abs(
            (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])
        ) / 2.0
    return total


def test_ear_clip_covers_a_square():
    c = studio()
    points = [[0, 0], [1, 0], [1, 1], [0, 1]]
    triangles = c.ear_clip([0, 1, 2, 3], points)
    assert len(triangles) == 2
    assert area_of(points, triangles) == pytest.approx(1.0)


def test_a_t_junction_vertex_stays_a_real_corner():
    c = studio()
    # The extra point at (0.5, 0) is collinear: it is where a neighbour's
    # head joint lands. Dropping it would leave this piece a chord where
    # the neighbour has a bend, and the joint would open once lifted.
    #
    # Plain ear clipping can never take a collinear vertex as an ear tip
    # (its ear has exactly zero area under any ordering), so without the
    # set-aside-and-splice handling in ear_clip, the ring reduces straight
    # to this vertex and its two collinear neighbours, and the final
    # triangle carries it with no area at all. That would still pass a
    # weaker version of this test: the degenerate triangle contributes
    # zero to the total area either way, and the T point is still present
    # in *a* triangle tuple, just one with no area. The two extra checks
    # below are what actually catch that.
    points = [[0, 0], [0.5, 0], [1, 0], [1, 1], [0, 1]]
    ring = [0, 1, 2, 3, 4]
    triangles = c.ear_clip(ring, points)
    assert area_of(points, triangles) == pytest.approx(1.0)
    used = {index for triangle in triangles for index in triangle}
    assert used == set(ring), "every ring vertex, including the T point, is a real corner"
    for a, b, cc in triangles:
        pa, pb, pc = points[a], points[b], points[cc]
        area2 = abs(
            (pb[0] - pa[0]) * (pc[1] - pa[1]) - (pb[1] - pa[1]) * (pc[0] - pa[0])
        )
        assert area2 > 1e-9, "a degenerate triangle slipped through"


def test_a_sliver_ring_fails_with_a_readable_error():
    c = studio()
    # A ring welded down to only two distinct points (both ends of a
    # collapsed sliver) used to die inside ear_clip with a bare IndexError
    # naming nothing. build_tessellation deliberately reports slivers
    # rather than rejecting them, so callers have to be able to tell what
    # went wrong.
    points = [[0, 0], [1, 0]]
    with pytest.raises(ValueError):
        c.ear_clip([0, 1], points)


def test_bridge_holes_makes_an_annulus_clippable():
    c = studio()
    points = [
        [0, 0], [4, 0], [4, 4], [0, 4],
        [1, 1], [1, 3], [3, 3], [3, 1],
    ]
    ring = c.bridge_holes([0, 1, 2, 3], [[4, 5, 6, 7]], points)
    triangles = c.ear_clip(ring, points)
    assert area_of(points, triangles) == pytest.approx(16.0 - 4.0, abs=1e-9)


def test_subdivision_is_uniform_and_keeps_the_boundary_chain():
    c = studio()
    points = [[0, 0], [1, 0], [0, 1]]
    points, triangles, chains = c.subdivide(points, [(0, 1, 2)], [[0, 1, 2]], 2)
    assert len(triangles) == 16
    assert area_of(points, triangles) == pytest.approx(0.5)
    # Each of the ring's 3 edges is now 4 segments.
    assert len(chains[0]) == 12


def test_a_shared_edge_midpoint_is_bit_identical_from_either_side():
    c = studio()
    left = [[0.1, 0.2], [0.7, 0.9], [0.0, 1.0]]
    right = [[0.7, 0.9], [0.1, 0.2], [1.0, 0.0]]
    a, _, _ = c.subdivide(list(left), [(0, 1, 2)], [[0, 1, 2]], 1)
    b, _, _ = c.subdivide(list(right), [(0, 1, 2)], [[0, 1, 2]], 1)
    # The midpoint of the edge the two triangles share, from both sides.
    assert a[3] == b[3]


def test_lift_interpolates_the_surface_exactly():
    c = studio()
    vertices = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 1.0], [2.0, 0.0, 2.0],
        [0.0, 1.0, 1.0], [1.0, 1.0, 2.0], [2.0, 1.0, 3.0],
    ]
    faces = [[0, 1, 4, 3], [1, 2, 5, 4]]
    surface = c.Surface(vertices, faces)
    lifted = surface.lift(0.5, 0.5)
    assert lifted["z"] == pytest.approx(1.0)
    assert lifted["clamped"] is False
    assert sum(weight for _, weight in lifted["weights"]) == pytest.approx(1.0)
    assert all(0 <= index < len(vertices) for index, _ in lifted["weights"])


def test_lift_at_a_vertex_reduces_to_that_vertex():
    c = studio()
    vertices = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 1.0], [2.0, 0.0, 2.0],
        [0.0, 1.0, 1.0], [1.0, 1.0, 2.0], [2.0, 1.0, 3.0],
    ]
    surface = c.Surface(vertices, [[0, 1, 4, 3], [1, 2, 5, 4]])
    lifted = surface.lift(1.0, 1.0)
    heavy = [(index, weight) for index, weight in lifted["weights"] if weight > 1e-9]
    assert heavy == [(4, pytest.approx(1.0))]


def test_a_point_off_the_surface_is_clamped_and_counted():
    c = studio()
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    surface = c.Surface(vertices, [[0, 1, 2, 3]])
    lifted = surface.lift(1.5, 0.5)
    assert lifted["clamped"] is True
    assert sum(weight for _, weight in lifted["weights"]) == pytest.approx(1.0)


def test_a_clamp_says_how_far_it_reached_in_metres():
    """A count of clamped points cannot be read without a magnitude.

    On the real Trial 2 export at 0.9 m the clamp reaches 52 mm at its
    worst, ten times CHORD_TARGET, because domain.radius_at deliberately
    takes the outermost rim crossing where the tolerated wobble makes the
    boundary multi-valued. Half a metre here, on a unit square, is the same
    number measured on geometry small enough to check by hand.
    """

    c = studio()
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    surface = c.Surface(vertices, [[0, 1, 2, 3]])

    off = surface.lift(1.5, 0.5)
    assert off["clamped"] is True
    assert off["clamp_m"] == pytest.approx(0.5)

    # Diagonally off the corner: 3-4-5, so 0.5 m out.
    corner = surface.lift(1.3, 1.4)
    assert corner["clamped"] is True
    assert corner["clamp_m"] == pytest.approx(0.5)

    # A point on the mesh reports zero rather than nothing, so a caller can
    # sum or sort clamp_m without asking about clamped first.
    on = surface.lift(0.5, 0.5)
    assert on["clamped"] is False
    assert on["clamp_m"] == 0.0


def test_a_point_off_the_surface_projects_to_the_boundary_when_one_is_attached():
    """K3 (cutting truth, 2026-08-17): with no boundary attached (every
    other lift test in this file), Surface keeps the old nearest-face
    clamp exactly as before -- see test_a_clamp_says_how_far_it_reached_
    in_metres, unchanged by this task. Attaching one changes the fallback:
    the point is projected to the nearest point of the boundary instead.

    On this square, mesh footprint and boundary coincide exactly, so old
    and new agree numerically (both 0.5 m); what this pins is that the
    NEW mechanism engaged (projected True, clamped False), not merely
    that the magnitude happens to match.
    """

    c = studio()
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    surface = c.Surface(vertices, [[0, 1, 2, 3]])
    surface.boundary = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

    off = surface.lift(1.5, 0.5)
    assert off["clamped"] is False
    assert off["clamp_m"] == 0.0
    assert off["projected"] is True
    assert off["projected_m"] == pytest.approx(0.5)

    # A point on the mesh is unaffected: still not clamped, and now also
    # not counted as projected, the same "zero rather than nothing" rule
    # clamp_m already followed.
    on = surface.lift(0.5, 0.5)
    assert on["clamped"] is False
    assert on["projected"] is False
    assert on["projected_m"] == 0.0


def test_projection_finds_the_true_nearest_boundary_point_past_a_reentrant_corner():
    """A concave (reentrant) footprint, the shape a real rim notch takes:
    three unit squares forming an L (missing the top right quadrant), so
    a point diagonally outside the notch has two equally near candidate
    boundary points -- (1.3, 1) on the bottom face's own top edge and
    (1, 1.3) on the side face's own right edge, both exactly 0.3 m away,
    hand computed. The OLD clamp picked a face by centroid distance alone
    and blended barycentric weights inside whichever triangle that face's
    OWN topology happened to fan first, with no guarantee the result was
    the true nearest point of the mesh's own boundary at all -- this is
    exactly the shape of error the real rim's notch produced (see
    cutting.Surface.lift's own K3 docstring paragraph). The new mechanism
    measures the true nearest boundary point directly, so this is hand
    verifiable independent of which face the old clamp would have chosen.
    """

    c = studio()
    # 0:(0,0) 1:(1,0) 2:(1,1) 3:(0,1) 4:(2,0) 5:(2,1) 6:(1,2) 7:(0,2)
    vertices = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
        [2.0, 0.0, 0.0], [2.0, 1.0, 0.0], [1.0, 2.0, 0.0], [0.0, 2.0, 0.0],
    ]
    faces = [
        [0, 1, 2, 3],   # A
        [1, 4, 5, 2],   # B
        [3, 2, 6, 7],   # C
    ]
    surface = c.Surface(vertices, faces)
    surface.boundary = [
        [0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [1.0, 1.0], [1.0, 2.0], [0.0, 2.0],
    ]

    found = surface.lift(1.3, 1.3)
    assert found["projected"] is True
    assert found["clamped"] is False
    assert found["projected_m"] == pytest.approx(0.3, abs=1e-9)


def test_lift_reports_x_y_unchanged_when_the_point_needs_no_move():
    """Rim-rectangular fix (2026-08-18): lift() now always carries the
    plan position the sample was actually taken at ("x"/"y" in the
    returned dict), the same "no absent keys" rule clamp_m and
    projected_m already follow. A point that lands on the mesh unaided
    needs no move at all: x/y echo the original request exactly."""

    c = studio()
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    surface = c.Surface(vertices, [[0, 1, 2, 3]])
    found = surface.lift(0.5, 0.5)
    assert (found["x"], found["y"]) == (0.5, 0.5)


def test_lift_moves_x_y_to_the_projected_boundary_point():
    """Rim-rectangular fix (2026-08-18): before this fix, only the SAMPLE
    (z, normal, weights) moved to the boundary-projected point; the point's
    own plan position was left at the caller's original request (see
    docs/specs/2026-08-17-cutting-truth-design.md's retrospective
    correction: "it is the sample that moves to the rim, not the point
    itself"). Now lift()'s own returned "x"/"y" carry the PROJECTED
    position whenever the boundary-polyline projection is what found this
    sample, so a caller that ships the point verbatim (pieces._lift) draws
    the corner ON the rim, not merely samples it there.
    """

    c = studio()
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    surface = c.Surface(vertices, [[0, 1, 2, 3]])
    surface.boundary = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

    found = surface.lift(1.5, 0.5)
    assert found["projected"] is True
    assert (found["x"], found["y"]) == pytest.approx((1.0, 0.5))
    # Never the caller's own original, unprojected request.
    assert (found["x"], found["y"]) != (1.5, 0.5)


def test_lift_leaves_x_y_at_the_original_request_for_the_last_resort_clamp():
    """The last-resort nearest-face clamp (no boundary attached, or the
    projection itself still missed the mesh) is explicitly NOT extended by
    the rim-rectangular fix: its own reach is already disclosed through
    clamp_m, and the fix contract's "snap to the nearest point of the
    boundary polyline" names the K3 projection machinery specifically, not
    this older fallback. x/y stay at the caller's own original request
    here, same as before this fix.
    """

    c = studio()
    vertices = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    surface = c.Surface(vertices, [[0, 1, 2, 3]])
    found = surface.lift(1.5, 0.5)
    assert found["clamped"] is True
    assert (found["x"], found["y"]) == (1.5, 0.5)


def test_ear_clip_takes_the_largest_ear_and_avoids_slivers():
    c = studio()
    # The largest ear selection rule avoids slivers. When these caps are
    # subdivided and lifted onto the vault surface, sliver triangles produce
    # noisy surface normals on the drawn casting.
    #
    # Fixture: 8-vertex simple polygon that exposes the difference between
    # largest-ear and first-available selection. Measured results:
    #   largest ear (shipped):  0.100930
    #   first available:        0.000338
    # The factor of 298 difference is exactly the problem the rule solves.
    # The threshold 0.01 sits about 30x above first-available and 10x below
    # largest-ear, so it fails loudly if the selection rule is swapped.
    points = [
        [0.642407, 0.0], [0.40025, 0.40025], [0.0, 0.767683], [-0.10957, 0.10957],
        [-0.736031, 0.0], [-0.520895, -0.520895], [-0.0, -0.302062], [0.510753, -0.510753],
    ]
    ring = [0, 1, 2, 3, 4, 5, 6, 7]

    triangles = c.ear_clip(ring, points)
    # Total area is preserved.
    assert area_of(points, triangles) == pytest.approx(0.876139146936, abs=1e-9)
    # Minimum triangle area is above the threshold, proving largest-ear
    # selection is in place.
    min_area = min(
        abs(
            (points[a][0] - points[b][0]) * (points[c][1] - points[b][1])
            - (points[a][1] - points[b][1]) * (points[c][0] - points[b][0])
        ) / 2.0
        for a, b, c in triangles
    )
    assert min_area >= 0.01
