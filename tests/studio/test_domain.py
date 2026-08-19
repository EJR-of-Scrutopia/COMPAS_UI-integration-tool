"""domain.py fits a polar map to the vault's own plan boundary.

Two fixtures: a 2 by 2 grid of unit quads, whose boundary radius is known
exactly by hand, and a 3 by 3 grid with one face removed, whose bay makes
it genuinely not star shaped about its own centroid.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def studio():
    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import domain
    return domain


def openings_module():
    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import openings
    return openings


def tessellation_module():
    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import tessellation
    return tessellation


def grid(side, drop=(), clockwise=False, mirror=False):
    """side by side unit quads, with the listed (i, j) faces left out.

    clockwise reverses each face's vertex order, so the same vertices and
    the same faces are wound the other way round: identical geometry, the
    normals pointing the other way, which is an ordinary authoring choice
    rather than a broken export. The reversal is anchored at the face's
    first vertex on purpose. Reversing the whole list gives the same cycle
    (a rotation of this one, so the same winding), but boundary_ring walks
    undirected adjacency and picks its direction from the order it happens
    to discover boundary edges in, and only this form turns that walk
    around. Which way the rim is walked is therefore not a function of
    winding alone, which is exactly why the wobble measure has to be read
    relative to the direction of travel.

    Fix round 1 (review finding 1, task-3-review.md): once plan_domain
    routes through openings.extract_loops (Deviation 3, task-3-report.md),
    `clockwise` above stops changing which vertex the rim is walked to
    first at all -- extract_loops's walk direction is a deterministic
    function of vertex ids, not of face winding, so it no longer gives
    plan_domain a rim walked the other way round. mirror instead negates
    every vertex's x coordinate (same vertex ids, same face winding): the
    walk visits vertices in the identical id order either way, but
    reflecting x negates every theta, which flips the SIGN of turn -- the
    thing plan_domain's own sense logic actually reads. This is what still
    exercises "sense is read from the geometry, not assumed" under the new
    walk.
    """
    vertices = [
        [float(i), float(j), 0.0]
        for j in range(side + 1) for i in range(side + 1)
    ]
    if mirror:
        vertices = [[-x, y, z] for x, y, z in vertices]
    faces = []
    for j in range(side):
        for i in range(side):
            if (i, j) in drop:
                continue
            n = side + 1
            face = [j * n + i, j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i]
            if clockwise:
                face = [face[0]] + list(reversed(face[1:]))
            faces.append(face)
    centroids = [
        [sum(vertices[k][axis] for k in face) / 4.0 for axis in range(3)]
        for face in faces
    ]
    return vertices, faces, centroids


def _turn_of(thetas):
    """The same wrap-and-sum turn computation plan_domain performs
    internally (domain.py's own steps/turn loop), reimplemented here so a
    test can measure turn directly -- plan_domain's own return dict never
    exposes it except inside failure["turn"], and this fixture is expected
    to be ACCEPTED (failure is None), so there is nothing to read it from
    otherwise.
    """

    TWO_PI = 2.0 * math.pi
    turn = 0.0
    for i in range(len(thetas)):
        step = thetas[(i + 1) % len(thetas)] - thetas[i]
        while step <= -math.pi:
            step += TWO_PI
        while step > math.pi:
            step -= TWO_PI
        turn += step
    return turn


def test_boundary_ring_is_one_closed_loop():
    d = studio()
    vertices, faces, _ = grid(2)
    ring = d.boundary_ring(faces)
    assert len(ring) == 8
    assert len(set(ring)) == 8
    assert 4 not in ring          # the centre vertex is interior


def test_radius_follows_the_real_boundary():
    d = studio()
    vertices, faces, centroids = grid(2)
    domain = d.plan_domain(vertices, faces, centroids)
    assert domain["axis"] == pytest.approx([1.0, 1.0])
    assert d.radius_at(domain, 0.0) == pytest.approx(1.0, abs=1e-12)
    assert d.radius_at(domain, math.pi / 2) == pytest.approx(1.0, abs=1e-12)
    assert d.radius_at(domain, math.pi / 4) == pytest.approx(math.sqrt(2.0), abs=1e-12)
    assert d.radius_at(domain, math.pi) == pytest.approx(1.0, abs=1e-12)


def test_plan_point_lands_on_the_rim_at_f_one():
    d = studio()
    vertices, faces, centroids = grid(2)
    domain = d.plan_domain(vertices, faces, centroids)
    point = d.plan_point(domain, 1.0, math.pi / 4)
    assert point == pytest.approx([2.0, 2.0], abs=1e-12)
    half = d.plan_point(domain, 0.5, 0.0)
    assert half == pytest.approx([1.5, 1.0], abs=1e-12)


def test_a_bay_is_reported_as_not_star_shaped():
    d = studio()
    # A 3 by 3 grid with the middle of the right column removed. The bay
    # spans x 2 to 3, y 1 to 2, and from the centroid of the remaining
    # faces the boundary corner (3, 1) sits behind it. Its backward turn is
    # measured, not just asserted nonzero: 0.752484... radians (about 43.1
    # degrees), nearly 9 times WOBBLE_TOLERANCE's 5 degrees, so this pins
    # that the threshold actually discriminates a real bay from a wobble
    # rather than merely that this one fixture still fails.
    vertices, faces, centroids = grid(3, drop={(2, 1)})
    domain = d.plan_domain(vertices, faces, centroids)
    assert domain["star_shaped"] is False
    assert domain["failure"]["backward_steps"] >= 1
    assert domain["failure"]["vertex"] in d.boundary_ring(faces)
    assert domain["backward_turn"] == pytest.approx(0.7524840212747467)
    assert domain["backward_turn"] > d.WOBBLE_TOLERANCE


def test_a_bay_wound_clockwise_is_still_refused():
    """The tolerance must not become a way of accepting a real bay.

    The same 3 by 3 bay, wound the other way. Reading "backward" as
    numerically negative measured this at 403.1142 degrees, a full turn of
    the rim added to the bay's own 43.1: refused, but for the wrong
    reason, and by an amount that says nothing about the geometry. Read
    against the direction of travel it measures the bay itself, the same
    figure test_a_bay_is_reported_as_not_star_shaped pins for the
    anticlockwise winding, and refuses on that.
    """
    d = studio()
    vertices, faces, centroids = grid(3, drop={(2, 1)}, clockwise=True)
    domain = d.plan_domain(vertices, faces, centroids)
    assert domain["star_shaped"] is False
    assert domain["failure"]["backward_steps"] >= 1
    assert domain["failure"]["vertex"] in d.boundary_ring(faces)
    assert domain["backward_turn"] == pytest.approx(0.7524840212747467)
    assert domain["backward_turn"] > d.WOBBLE_TOLERANCE


def test_a_plain_grid_is_star_shaped():
    d = studio()
    vertices, faces, centroids = grid(3)
    domain = d.plan_domain(vertices, faces, centroids)
    assert domain["star_shaped"] is True
    assert domain["failure"] is None
    assert domain["backward_turn"] == 0.0
    assert domain["backward_steps"] == 0


def test_a_plain_grid_wound_clockwise_is_star_shaped_too():
    """Reversed face normals are an authoring choice, not a bad plan.

    Identical geometry to test_a_plain_grid_is_star_shaped, wound the
    other way. Before the 2026-08-19 multi-loop wave, plan_domain walked
    the rim through boundary_ring, whose direction came from the order
    edges were first discovered while scanning faces and so flipped with
    the mesh's own winding; measuring backward steps in absolute terms
    called the whole rim backward and refused this plan at 360 degrees of
    wobble over 12 steps, on a square with no wobble in it at all.

    plan_domain now walks the rim through openings.extract_loops, whose
    walk direction is a deterministic property of vertex ids (from the
    loop's own minimum vertex, its smaller neighbour is stepped to first
    -- openings.py:36-86) rather than of edge discovery order, so the SAME
    ring comes out regardless of which way the mesh happens to be wound:
    measured below, the two calls return byte identical rings, not
    reversed ones. What still has to hold, and is the real point of this
    test, is that a clockwise winding cannot fool the winding/wobble
    computation into reading the rim as backward -- sense is read from the
    geometry (turn's own sign), not assumed, so both windings still
    measure zero wobble.
    """
    d = studio()
    vertices, faces, centroids = grid(3, clockwise=True)
    domain = d.plan_domain(vertices, faces, centroids)

    anticlockwise = d.plan_domain(*grid(3))["ring"]
    assert domain["ring"] == anticlockwise

    assert domain["star_shaped"] is True
    assert domain["failure"] is None
    assert domain["backward_turn"] == 0.0
    assert domain["backward_steps"] == 0


def test_a_mirrored_plain_grid_is_star_shaped_too():
    """Fix round 1 (review finding 1): the pair of "wound_clockwise" tests
    above no longer exercises plan_domain's own sense logic (domain.py:171)
    at all, now that openings.extract_loops's walk direction does not
    depend on face winding -- a mutation replacing `sense = -1.0 if turn <
    0.0 else 1.0` with a hardcoded `sense = 1.0` left the entire suite
    green (measured: 467 passed, 17 skipped). This test's fixture mirrors
    the PLAN instead (grid(..., mirror=True): x -> -x, same vertex ids,
    same face winding), which does still flip the walked direction, since
    extract_loops's walk is id-canonical but theta is computed from real
    coordinates: reflecting x negates every theta, so the sign of every
    angular step, and of turn itself, flips.

    Measured before pinning: turn == -6.283185307179586, i.e. -TWO_PI
    within 1e-6, so this genuinely is a rim plan_domain must read as
    walked "the other way" to accept -- under the correct sense logic
    backward_turn is 0.0 (below); under a sense = 1.0 mutant it measures
    the full 2*pi (6.283185307179586 rad) instead and star_shaped flips to
    False, which is what backward_turn < 0.01 below is pinned to catch.
    """
    d = studio()
    vertices, faces, centroids = grid(3, mirror=True)
    domain = d.plan_domain(vertices, faces, centroids)

    turn = _turn_of(domain["thetas"])
    assert turn == pytest.approx(-2.0 * math.pi, abs=1e-6)

    assert domain["star_shaped"] is True
    assert domain["failure"] is None
    assert domain["backward_turn"] < 0.01
    assert domain["backward_steps"] == 0


def test_a_mirrored_bay_is_still_refused_with_the_same_wobble():
    """The bay counterpart to the mirrored plain-grid test above: review
    finding 1 names BOTH test_a_plain_grid_wound_clockwise_is_star_shaped
    _too and test_a_bay_wound_clockwise_is_still_refused as having lost
    their grip on the sense mutant, so this closes the gap for the second
    one too, not just the first.

    Measured before pinning: mirroring the bay fixture also flips turn to
    -TWO_PI (the same -6.283185307179586), and backward_turn comes out
    0.7524840212747463 -- the same 0.752484 rad (to floating point) that
    test_a_bay_is_reported_as_not_star_shaped and
    test_a_bay_wound_clockwise_is_still_refused both already pin for this
    physical bay, confirming the mirrored construction reproduces the same
    shape rather than a different one. Under a sense = 1.0 mutant
    backward_turn instead measures 7.035669328454333 rad -- an order of
    magnitude off and well past WOBBLE_TOLERANCE either way, but the exact
    pinned value below only matches the correct implementation.
    """
    d = studio()
    vertices, faces, centroids = grid(3, drop={(2, 1)}, mirror=True)
    domain = d.plan_domain(vertices, faces, centroids)

    turn = _turn_of(domain["thetas"])
    assert turn == pytest.approx(-2.0 * math.pi, abs=1e-6)

    assert domain["star_shaped"] is False
    assert domain["failure"]["backward_steps"] >= 1
    assert domain["backward_turn"] == pytest.approx(0.7524840212747467)
    assert domain["backward_turn"] > d.WOBBLE_TOLERANCE


def test_a_plan_that_does_not_wind_once_is_refused_on_winding(monkeypatch):
    """The winding check stands on its own, with no help from the wobble.

    An L, three quads along the bottom and two up the left, whose mean
    face centroid at (1.1, 1.1) lands in the notch rather than on the
    material. Its rim sweeps out and back rather than round, so it winds
    zero times about that axis and no polar pattern can be drawn on it,
    however the wobble is read. WOBBLE_TOLERANCE is lifted past anything
    the rim could measure so that the winding condition is the only thing
    left that can refuse this plan: merge the two conditions into one, or
    drop the winding half, and this test fails.
    """
    d = studio()
    monkeypatch.setattr(d, "WOBBLE_TOLERANCE", 100.0)
    vertices, faces, centroids = grid(3, drop={(1, 1), (2, 1), (1, 2), (2, 2)})
    domain = d.plan_domain(vertices, faces, centroids)

    assert domain["axis"] == pytest.approx([1.1, 1.1])
    assert domain["backward_turn"] < d.WOBBLE_TOLERANCE
    assert domain["star_shaped"] is False
    assert domain["failure"]["turn"] == pytest.approx(0.0, abs=1e-9)
    assert domain["failure"]["vertex"] in d.boundary_ring(faces)


def test_a_small_wobble_is_tolerated_and_still_cuts_cleanly():
    """A local dip that reverses the angular order for one step, without
    making the plan fail to be star shaped in practice: the same shape of
    feature the real "Trial 2" export measures (see domain.py's
    WOBBLE_TOLERANCE comment), reproduced here on a 20 by 20 grid by
    nudging one boundary vertex off the straight edge it sits on.
    """
    d = studio()
    vertices, faces, centroids = grid(20)
    vertices[5][0] += 0.1
    vertices[5][1] += 2.0
    domain = d.plan_domain(vertices, faces, centroids)

    # Accepted, and the reporting is not just "not refused": a test that
    # checked only star_shaped would keep passing if the wobble reporting
    # were deleted entirely.
    assert domain["star_shaped"] is True
    assert domain["failure"] is None
    assert domain["backward_steps"] == 1
    assert domain["backward_turn"] > 0.0
    assert domain["backward_turn"] == pytest.approx(0.009140513255795568)
    assert domain["backward_turn"] < d.WOBBLE_TOLERANCE

    # And the tolerated wobble still produces a usable cut: no coverage
    # holes at a size the real geometry can absorb the dip at.
    generators = __import__("generators")
    tessellation = __import__("tessellation")
    tess = generators.generate("bonded-courses", domain, 1.2)
    binding = tessellation.analysis_binding(tess, centroids)
    assert binding["report"]["coverage_holes"] == []


# --- Multi-loop cutting (2026-08-19): openings classified into the plan
# domain ------------------------------------------------------------------


def _legacy_plan_domain(d, vertices, faces, centroids):
    """The pre-wave computation, reimplemented independently here (not
    calling plan_domain) from d.boundary_ring alone, so the byte-identity
    test below proves something rather than reading the same computation
    back at itself. Same axis / thetas / winding / wobble maths plan_domain
    itself carries; see domain.py's own comments for why each step reads
    the way it does.
    """

    ring = d.boundary_ring(faces)
    axis = [
        sum(p[0] for p in centroids) / len(centroids),
        sum(p[1] for p in centroids) / len(centroids),
    ]
    loop = [[vertices[i][0], vertices[i][1]] for i in ring]
    thetas = [math.atan2(p[1] - axis[1], p[0] - axis[0]) for p in loop]

    steps = []
    turn = 0.0
    for i in range(len(thetas)):
        step = thetas[(i + 1) % len(thetas)] - thetas[i]
        while step <= -math.pi:
            step += d.TWO_PI
        while step > math.pi:
            step -= d.TWO_PI
        steps.append(step)
        turn += step

    winds_once = abs(abs(turn) - d.TWO_PI) < 1e-6
    sense = -1.0 if turn < 0.0 else 1.0
    walked = [sense * step for step in steps]
    backward_indices = [i for i, s in enumerate(walked) if s < -d.STEP_EPSILON]
    backward_turn = -sum(walked[i] for i in backward_indices)
    star = winds_once and backward_turn < d.WOBBLE_TOLERANCE
    return {
        "axis": axis, "loop": loop, "ring": ring, "thetas": thetas,
        "star_shaped": star, "backward_turn": backward_turn,
    }


def test_a_single_loop_plan_gains_an_empty_holes_key():
    """holes == [] for an ordinary single-loop mesh, and every existing
    key comes out exactly as the pre-wave computation produces it --
    proven against an independent reimplementation (_legacy_plan_domain,
    built from d.boundary_ring, never from d.plan_domain), not merely
    read back against plan_domain's own new output.
    """
    d = studio()
    vertices, faces, centroids = grid(3)
    domain = d.plan_domain(vertices, faces, centroids)

    assert domain["holes"] == []

    legacy = _legacy_plan_domain(d, vertices, faces, centroids)
    assert domain["axis"] == legacy["axis"]
    assert domain["loop"] == legacy["loop"]
    assert domain["ring"] == legacy["ring"]
    assert domain["thetas"] == legacy["thetas"]
    assert domain["star_shaped"] == legacy["star_shaped"]
    assert domain["backward_turn"] == legacy["backward_turn"]


def test_an_interior_hole_is_classified_not_refused():
    """grid(5, drop=((2, 2),)) -- the exact fixture openings.py's own
    tests pin (test_classify_picks_the_containing_loop) -- would put the
    mean face centroid dead in the CENTRE of the hole it punches (measured:
    axis (2.5, 2.5), the hole's own centre), which is precisely the
    refusal the next test wants. This test wants the OTHER outcome, a
    classified opening plan_domain actually accepts, so it uses an
    off-centre single-face hole instead (grid(7), face (1, 1) dropped) and
    measures its own hole ids and plan points rather than reusing the ones
    named in the task brief for the on-axis fixture.
    """
    d = studio()
    o = openings_module()
    t = tessellation_module()
    vertices, faces, centroids = grid(7, drop=((1, 1),))

    # Measured, not guessed: the axis really does land outside this hole.
    loops = o.extract_loops(faces)
    outer, hole_rings = o.classify(loops, vertices)
    hole_loop = [[vertices[i][0], vertices[i][1]] for i in hole_rings[0]]
    axis = [
        sum(p[0] for p in centroids) / len(centroids),
        sum(p[1] for p in centroids) / len(centroids),
    ]
    assert not t.point_in_ring(axis, list(range(len(hole_loop))), hole_loop)

    domain = d.plan_domain(vertices, faces, centroids)
    assert domain["star_shaped"] is True
    assert domain["failure"] is None
    assert len(domain["holes"]) == 1
    hole = domain["holes"][0]
    assert hole["ring"] == [9, 10, 18, 17]
    assert hole["loop"] == [
        [1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0],
    ]


def test_the_axis_inside_an_opening_refuses_verbatim():
    """grid(5, drop=((2, 2),)): by symmetry the mean face centroid of the
    24 remaining faces is exactly (2.5, 2.5) -- the removed face's own
    centre -- which is measured below to fall inside the hole polygon
    before the refusal is pinned, per the task brief's instruction not to
    guess.
    """
    d = studio()
    o = openings_module()
    t = tessellation_module()
    vertices, faces, centroids = grid(5, drop=((2, 2),))

    loops = o.extract_loops(faces)
    outer, hole_rings = o.classify(loops, vertices)
    hole_loop = [[vertices[i][0], vertices[i][1]] for i in hole_rings[0]]
    axis = [
        sum(p[0] for p in centroids) / len(centroids),
        sum(p[1] for p in centroids) / len(centroids),
    ]
    assert axis == [2.5, 2.5]
    assert t.point_in_ring(axis, list(range(len(hole_loop))), hole_loop)

    try:
        d.plan_domain(vertices, faces, centroids)
        assert False, "expected a ValueError"
    except ValueError as error:
        assert str(error) == (
            "the plan's axis falls inside an opening, so the polar "
            "pattern has no crown to close on. Author the tessellation "
            "in Grasshopper and import it instead."
        )


# --- Rim remainder (2026-08-19): radius_at becomes the first exit --------
#
# domain.radius_at used to take the OUTERMOST ray-segment crossing. Where a
# tolerated rim wobble makes the boundary genuinely multi-valued along a
# ray (a small lobe that doubles back over a narrow angular window), the
# outermost crossing sits on the far side of a gap the ray has already
# left the plan through. The replacement counts crossings with a
# half-open side convention, groups crossings coincident within 1e-12 m,
# and returns the smallest radius whose group has ODD parity: the radius
# at which the ray first genuinely leaves the plan. See
# docs/superpowers/specs/2026-08-19-rim-remainder-design.md and
# .superpowers/sdd/2026-08-19-rim-remainder-probe/report.md.


def _old_radius_at(domain, theta):
    """The pre-wave algorithm, reimplemented independently here (an exact
    copy of the outermost-crossing, along_edge-tolerance body
    domain.radius_at carried before this wave) rather than calling
    domain.radius_at, so the tests below can show the new rule agreeing
    with, or genuinely diverging from, the old one -- reading the same
    computation back at itself would prove nothing.
    """
    ax, ay = domain["axis"]
    dx, dy = math.cos(theta), math.sin(theta)
    loop = domain["loop"]
    best = None
    for i in range(len(loop)):
        p = loop[i]
        q = loop[(i + 1) % len(loop)]
        ex, ey = q[0] - p[0], q[1] - p[1]
        denominator = dx * ey - dy * ex
        if abs(denominator) < 1e-15:
            continue
        px, py = p[0] - ax, p[1] - ay
        along_ray = (px * ey - py * ex) / denominator
        along_edge = (px * dy - py * dx) / denominator
        if along_ray < 0.0 or not (-1e-12 <= along_edge <= 1.0 + 1e-12):
            continue
        if best is None or along_ray > best:
            best = along_ray
    return best


def _segment_hit(axis, theta, p, q):
    """Pure line-segment-against-ray intersection, no crossing-rule logic
    at all: the shared core both the old and new radius_at build on. Used
    only to compute an expected radius independently, from a named
    segment, rather than reading it back from either implementation.
    """
    ax, ay = axis
    dx, dy = math.cos(theta), math.sin(theta)
    ex, ey = q[0] - p[0], q[1] - p[1]
    denominator = dx * ey - dy * ex
    px, py = p[0] - ax, p[1] - ay
    return (px * ey - py * ex) / denominator


def _flat_domain(loop, axis=(0.0, 0.0)):
    """The minimum a hand built domain dict needs for radius_at and
    point_in_ring: axis and loop. Neither reads the other keys
    plan_domain's own return value carries.
    """
    return {"axis": list(axis), "loop": [list(p) for p in loop]}


def test_a_ray_through_a_corner_grazes_and_still_returns_the_rim():
    """A ray passing exactly through a convex corner of a square is the
    corner-graze case the old docstring named and the new rule handles by
    construction: two edges meet at the corner, one ending there (the
    corner's own side value is exactly 0, the half-open convention's own
    negative side) and one starting there whose OTHER end sits on the
    positive side, so exactly one of the two edges flips parity and the
    corner registers once, not zero or two times -- an even group would
    never flip the parity at all.

    Unit square centred on the axis, corners at (+-0.5, +-0.5); the ray at
    theta = pi/4 runs along the diagonal and exits exactly at (0.5, 0.5).
    The expected radius is computed here from the corner's own
    coordinates (math.hypot), not read back from the function under test.
    """
    d = studio()
    loop = [[-0.5, -0.5], [0.5, -0.5], [0.5, 0.5], [-0.5, 0.5]]
    domain = _flat_domain(loop)
    expected = math.hypot(0.5, 0.5)
    assert d.radius_at(domain, math.pi / 4.0) == pytest.approx(expected, abs=1e-12)
    # Not an accident of a symmetric fixture: the duplicated old rule
    # (above) is measured to return the identical value here too. A plain
    # graze is exactly the case the two rules must agree on; the notched
    # fixture below is where they genuinely diverge.
    assert _old_radius_at(domain, math.pi / 4.0) == pytest.approx(expected, abs=1e-12)


def _notched_polygon():
    """A hand built miniature of Trial 2's own lobe (probe report section
    2: triangle 181-182-183, an outward tip the walk reaches by stepping
    forward in angle and then briefly backward before continuing on): six
    vertices, walked anticlockwise, axis at the origin.

    V0 (theta 0 deg, r 10) -> V1 (theta 3 deg, r 11, the false tip,
    forward) -> V2 (theta 1 deg, r 9, the notch: BACKWARD in angle from
    V1's own 3 deg, though still forward of V0's 0 deg) -> V3 (theta 4
    deg, r 10, forward again, back to the baseline) -> V4 (theta 180 deg,
    r 10) -> V5 (theta 270 deg, r 10) -> back to V0.

    Over the angular window 1 to 3 degrees the walk visits this stretch
    twice (once via V0-V1, once via V2-V3), so a ray in that window
    crosses the rim three times: the near branch (segment V2-V3), a
    middle crossing (segment V1-V2), and the far branch (segment V0-V1).
    Verified simple (no self-intersection) and its three crossings
    measured, in the session scratchpad, before this was written into a
    test: at theta = 2 deg the crossings come out (segment index, radius)
    (0, 10.641884), (1, 9.898492), (2, 9.307541) -- an odd count of three
    distinct radii, no coincident graze anywhere in the window, so the
    first-exit rule returns the smallest immediately, and the old
    outermost rule returns the largest.
    """
    pts_polar = [
        (0.0, 10.0), (3.0, 11.0), (1.0, 9.0), (4.0, 10.0),
        (180.0, 10.0), (270.0, 10.0),
    ]
    loop = [
        [r * math.cos(math.radians(t)), r * math.sin(math.radians(t))]
        for t, r in pts_polar
    ]
    return _flat_domain(loop)


def test_a_multi_valued_rim_returns_the_near_branch_not_the_far_lobe():
    """Inside the notch's own angular window, the first-exit rule returns
    the NEAR branch, not the far lobe the old outermost rule preferred.
    Verified below, not merely asserted: the old rule (duplicated as
    _old_radius_at) is measured on this exact fixture to return the far
    branch, a value nowhere near the near branch this test pins -- this
    test genuinely fails against the rule this wave replaces.
    """
    d = studio()
    domain = _notched_polygon()
    theta = math.radians(2.0)
    loop = domain["loop"]

    expected_near = _segment_hit(domain["axis"], theta, loop[2], loop[3])  # V2->V3
    expected_far = _segment_hit(domain["axis"], theta, loop[0], loop[1])   # V0->V1
    assert expected_near < expected_far, "the fixture must be genuinely multi-valued"

    assert d.radius_at(domain, theta) == pytest.approx(expected_near, abs=1e-12)

    old_value = _old_radius_at(domain, theta)
    assert old_value == pytest.approx(expected_far, abs=1e-12)
    assert abs(old_value - expected_near) > 0.5, (
        "the old rule must land nowhere near the near branch, or this "
        "fixture proves nothing about the two rules genuinely diverging"
    )


def _regular_ngon(n, radius=3.0):
    return [
        [radius * math.cos(2.0 * math.pi * i / n), radius * math.sin(2.0 * math.pi * i / n)]
        for i in range(n)
    ]


def test_first_exit_matches_outermost_on_star_shaped_plans():
    """On any star shaped plan the new rule and the old rule must agree:
    the spec's own claim (docs/superpowers/specs/2026-08-19-rim-remainder-
    design.md, "The rule that ships"). Checked on the unit square and a
    regular 12-gon, 720 sampled thetas across the full turn, against the
    OLD algorithm duplicated above as _old_radius_at (not domain.radius_at
    read back at itself).
    """
    d = studio()
    square = _flat_domain([[-1.0, -1.0], [1.0, -1.0], [1.0, 1.0], [-1.0, 1.0]])
    twelvegon = _flat_domain(_regular_ngon(12))

    for domain in (square, twelvegon):
        for i in range(720):
            theta = 2.0 * math.pi * i / 720.0
            new = d.radius_at(domain, theta)
            old = _old_radius_at(domain, theta)
            assert new == pytest.approx(old, abs=1e-12), (domain["loop"], theta)


def test_dense_sampling_inside_the_notch_window_stays_inside_the_polygon():
    """f = 0.999 containment, targeted at the one place a coarse sweep
    would straddle: 500 samples across the notch's own 1 to 3 degree
    window (see _notched_polygon), each placed at 0.999 of the first-exit
    radius, must all still lie inside the true polygon
    (tessellation.point_in_ring). Measured before writing this test: the
    old outermost rule leaves 4 of these same 500 samples outside the
    polygon; the first-exit rule leaves 0.
    """
    d = studio()
    t = tessellation_module()
    domain = _notched_polygon()
    loop = domain["loop"]
    axis = domain["axis"]
    ring = list(range(len(loop)))

    for i in range(500):
        theta = math.radians(1.0 + 2.0 * i / 499.0)
        radius = 0.999 * d.radius_at(domain, theta)
        point = [axis[0] + radius * math.cos(theta), axis[1] + radius * math.sin(theta)]
        assert t.point_in_ring(point, ring, loop), (theta, point)


def _backward_wobble_windows(thetas):
    """The angular windows where the rim genuinely doubles back, LOCATED
    from the stored thetas rather than named by index: this reimplements
    plan_domain's own sense/backward-step logic (domain.py's
    plan_domain, not duplicated by guesswork) against whatever thetas a
    domain carries, so a fixture regeneration that moves the notch moves
    this pin with it, without an edit here.

    Each backward step (a walked step under STEP_EPSILON, once the whole
    loop's own turn direction -- its sense -- is read from the total
    turn, exactly as plan_domain reads it) brackets one window: the raw
    theta span between that step's own two endpoints, the angles the rim
    revisits. This is the same window the probe report (section 2) names
    by hand for Trial 2 (125.1977 to 125.4314 degrees, mirrored at
    -125.4314 to -125.1977).
    """
    d = studio()
    n = len(thetas)
    steps = []
    turn = 0.0
    for i in range(n):
        step = thetas[(i + 1) % n] - thetas[i]
        while step <= -math.pi:
            step += d.TWO_PI
        while step > math.pi:
            step -= d.TWO_PI
        steps.append(step)
        turn += step
    sense = -1.0 if turn < 0.0 else 1.0
    walked = [sense * step for step in steps]

    windows = []
    for i, step in enumerate(walked):
        if step < -d.STEP_EPSILON:
            a, b = thetas[i], thetas[(i + 1) % n]
            windows.append((min(a, b), max(a, b)))
    return windows


def test_the_committed_trial_2_domain_stays_contained_in_both_wobble_windows():
    """The containment bar made permanent against a future rule
    regression: not a synthetic miniature (that is
    test_dense_sampling_inside_the_notch_window_stays_inside_the_polygon,
    above) but the real, COMMITTED tests/studio/fixtures/trial-2-
    tessellation.json domain -- the one make_fixtures.py measured off the
    real Trial 2 export and every other Trial-2 pin in this suite already
    trusts.

    The windows are LOCATED (_backward_wobble_windows, above), not
    hardcoded by vertex index, so this keeps finding the notch even if
    the fixture is ever regenerated and the notch moves. >= 500 thetas
    per window, f = 0.999, via domain.plan_point (not a hand rolled
    radius*cos/sin, so this exercises the same call the studio's own
    pattern generators make): every point must land inside the true loop
    (tessellation.point_in_ring). Measured before writing this test
    (probe report sections 4 and 8, task-2-review.md section 7): under
    the shipped first-exit rule, 0 of 1000 targeted samples fall outside
    across both windows; under the old outermost rule, 22 of 1000 do
    (verified independently in the session scratchpad by swapping
    domain.radius_at for the pre-wave outermost/along_edge body and
    re-running this exact sampling loop) -- so this pin genuinely fails
    against the rule this wave replaced, not merely against a rule that
    was never shipped.
    """
    d = studio()
    t = tessellation_module()
    fixture = json.loads(
        (FIXTURES / "trial-2-tessellation.json").read_text(encoding="utf-8")
    )
    domain = fixture["domain"]
    loop = domain["loop"]
    ring = list(range(len(loop)))

    windows = _backward_wobble_windows(domain["thetas"])
    assert len(windows) == domain["backward_steps"] == 2, (
        "the located windows must match the domain's own backward_steps "
        "count, or this is not finding what plan_domain found"
    )

    total = 0
    for lo, hi in windows:
        for k in range(500):
            theta = lo + (hi - lo) * k / 499.0
            point = d.plan_point(domain, 0.999, theta)
            total += 1
            assert t.point_in_ring(point, ring, loop), (theta, point)
    assert total == 1000


def _innermost_radius_at(domain, theta):
    """The runner-up rule the design spec rejected (probe report R1,
    section 3, "Why R6 rather than R1"; task-2-review.md Minor 2):
    innermost along_ray among the OLD along_edge-tolerance test's
    survivors, with no grouping and no parity check at all. A tangency
    (the ray merely touching the rim, rather than genuinely leaving
    through it) is just another crossing to a rule built this way, which
    is exactly the failure mode the shipped rule was chosen to avoid.
    Reimplemented independently here, not read back from either
    domain.radius_at or the notched-polygon tests' own _old_radius_at
    (which is the OUTERMOST pre-wave rule, a different rule from this
    one).
    """
    ax, ay = domain["axis"]
    dx, dy = math.cos(theta), math.sin(theta)
    loop = domain["loop"]
    best = None
    for i in range(len(loop)):
        p = loop[i]
        q = loop[(i + 1) % len(loop)]
        ex, ey = q[0] - p[0], q[1] - p[1]
        denominator = dx * ey - dy * ex
        if abs(denominator) < 1e-15:
            continue
        px, py = p[0] - ax, p[1] - ay
        along_ray = (px * ey - py * ex) / denominator
        along_edge = (px * dy - py * dx) / denominator
        if along_ray < 0.0 or not (-1e-12 <= along_edge <= 1.0 + 1e-12):
            continue
        if best is None or along_ray < best:
            best = along_ray
    return best


def _needle_domain():
    """A square rim (radius 5, axis at the origin) with a thin needle
    poking inward from its right edge, the needle's tip sitting exactly
    on the ray at theta = 0.

    Walked from (-5, 5) anticlockwise, the right edge is split into four
    points instead of two: (5, -5) -> (5, 2) -> (1, 0) [the tip] ->
    (5, 3) -> (5, 5). That cuts a thin wedge into the square from the
    right edge, entering at y = 2, narrowing to a point at the tip
    (1, 0), and leaving again at y = 3 -- both flanking points ABOVE the
    ray, and neither below it, so the needle sits entirely on one side
    of the ray and only touches it at the tip. This is deliberately a
    GRAZE, not a crossing: see the test below for the point-in-ring check
    that proves the ray's own path to the true rim at radius 5 is never
    actually blocked by the needle.

    theta = 0 rather than some other angle is deliberate: cos(0) = 1.0
    and sin(0) = 0.0 EXACTLY in IEEE754, so the half-open side test's
    dx*(z.y-ay) - dy*(z.x-ax) reduces to plain z.y with no float-rounding
    fudge the way a vertical ray through cos(pi/2) would carry -- the
    parity argument in the test docstring below is then exact, not
    approximate.
    """
    loop = [
        [-5.0, 5.0], [-5.0, -5.0], [5.0, -5.0],
        [5.0, 2.0], [1.0, 0.0], [5.0, 3.0],
        [5.0, 5.0],
    ]
    return {"axis": [0.0, 0.0], "loop": loop}


def test_an_inward_needle_returns_the_rim_not_its_own_tangent_tip():
    """The property the design spec chose the first-exit rule over the
    innermost rule for (docs/superpowers/specs/2026-08-19-rim-remainder-
    design.md, "Why not the runner-up (innermost)"; probe report section
    7, "Why R6 rather than R1"; task-2-review.md Minor 2, which measured
    5.0 against 1.0000000000001226 on a similar hand built fixture and
    offered a needle fixture to this task). Not exercised by geometry
    this repo has shipped so far (Trial 2's own wobble is a shallow
    lobe, not a needle), so this is a property pin, not a regression pin.

    Why this genuinely discriminates, reasoned here rather than merely
    asserted: at theta = 0, dx = 1.0 and dy = 0.0 exactly (see
    _needle_domain), so the half-open side test side(z) = dx*(z.y-ay) -
    dy*(z.x-ax) reduces to plain z.y (axis is the origin). The tip
    (1, 0) has y = 0.0 exactly, so it sits on the "not > 0.0" side, the
    half-open convention's own negative side. Its two neighbours,
    (5, 2) and (5, 3), both have y > 0.0: the POSITIVE side. So the edge
    INTO the tip (positive side -> the tip's zero side: different signs,
    counted) and the edge OUT of the tip (the tip's zero side ->
    positive side: different signs too, also counted) both register a
    crossing, and both land at along_ray = 1.0, the tip's own radius --
    an EVEN group of two. The parity rule (domain.radius_at) skips an
    even group by construction and moves on to the only other group, the
    single genuine exit through the right edge at radius 5.0 (an ODD
    group of one). A rule that just takes the smallest along_ray with no
    grouping and no parity -- the innermost rule the spec rejected,
    reimplemented independently above as _innermost_radius_at -- has no
    way to see that the tip's two crossings cancel each other, and
    returns the tangency itself: 1.0. That is precisely an inward needle
    collapsing the domain radius to its own tip, the failure mode
    described in the design spec's "Why not the runner-up" and the
    probe's own section 7.
    """
    d = studio()
    t = tessellation_module()
    domain = _needle_domain()
    loop = domain["loop"]
    ring = list(range(len(loop)))
    theta = 0.0

    # The needle is a true graze, not a real notch: confirm the ray's own
    # path from the axis to the rim never actually leaves the polygon,
    # so radius 5.0 is genuinely the rim and not an artefact of a
    # containment check that happens not to look between 1 and 5.
    for x in (0.0, 1.0, 2.0, 3.0, 4.0, 4.99):
        assert t.point_in_ring([x, 0.0], ring, loop), x

    shipped = d.radius_at(domain, theta)
    assert shipped == pytest.approx(5.0, abs=1e-12)
    assert shipped != pytest.approx(1.0, abs=1e-6), (
        "the shipped rule must not collapse to the needle's own tip"
    )

    tangency = _innermost_radius_at(domain, theta)
    assert tangency == pytest.approx(1.0, abs=1e-12), (
        "the fixture must genuinely present a tangency to a rule that "
        "would take it, or this test proves nothing about the two rules "
        "diverging"
    )
