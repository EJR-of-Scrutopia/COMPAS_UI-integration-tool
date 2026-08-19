"""domain.py fits a polar map to the vault's own plan boundary.

Two fixtures: a 2 by 2 grid of unit quads, whose boundary radius is known
exactly by hand, and a 3 by 3 grid with one face removed, whose bay makes
it genuinely not star shaped about its own centroid.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


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


def grid(side, drop=(), clockwise=False):
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
    """
    vertices = [
        [float(i), float(j), 0.0]
        for j in range(side + 1) for i in range(side + 1)
    ]
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
