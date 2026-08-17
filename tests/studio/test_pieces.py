"""pieces.py builds the casting the viewer draws, from the cut.

The fixture is a shallow dome cut into four cells, so a flat joint is a
real constraint rather than a trivially satisfied one, and so that two
neighbours have something to disagree about.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def studio(name):
    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    return __import__(name)


def dome_z(x, y):
    return 0.4 * math.cos(0.6 * (x - 1)) * math.cos(0.6 * (y - 1))


def dome_surface(side=8):
    """A side by side quad mesh over [0, 2] squared, lifted into a dome."""

    cutting = studio("cutting")
    step = 2.0 / side
    vertices = [
        [i * step, j * step, dome_z(i * step, j * step)]
        for j in range(side + 1) for i in range(side + 1)
    ]
    faces = []
    n = side + 1
    for j in range(side):
        for i in range(side):
            faces.append([j * n + i, j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i])
    return cutting.Surface(vertices, faces), vertices, faces


def four_cells():
    t = studio("tessellation")
    raw = []
    for j in range(2):
        for i in range(2):
            raw.append({
                "key": "c{}{}".format(i, j),
                "course": j,
                "outline": [
                    [i * 1.0, j * 1.0], [i * 1.0 + 1.0, j * 1.0],
                    [i * 1.0 + 1.0, j * 1.0 + 1.0], [i * 1.0, j * 1.0 + 1.0],
                ],
                "holes": [],
            })
    return t.build_tessellation(raw, "test", "generated", 1.0, 2)


def build():
    p = studio("pieces")
    surface, _, _ = dome_surface()
    tess = four_cells()
    return p.segment_pieces(tess, surface, [[0.0, 0.0]])


def test_one_piece_per_cell_in_placement_order():
    made, _ = build()
    # Anticlockwise within each course about the cut's own centre, here
    # (1, 1): c00 sits at -135 degrees, c10 at -45, c11 at +45, c01 at
    # +135. That is the tessellation's placement order, not row major
    # authoring order, and it is correct: do not "fix" it back.
    assert [piece["key"] for piece in made] == ["c00", "c10", "c11", "c01"]
    assert [piece["course"] for piece in made] == [0, 0, 1, 1]


def test_a_joint_facet_is_flat():
    p = studio("pieces")
    surface, _, _ = dome_surface()
    tess = four_cells()
    planes = p.facet_planes(tess, surface)
    chosen = p.choose_rounds(tess, surface)
    made, _ = p.segment_pieces(tess, surface, [])
    # Every point on the shared cut between c00 and c10 lies in one plane.
    shared = [
        facet for facet in tess["cells"][0]["facets"]
        if facet in set(tess["cells"][1]["facets"])
    ]
    assert len(shared) == 1
    origin, normal = planes[shared[0]]
    piece = next(m for m in made if m["key"] == "c00")
    # The joint plane runs through the two corners along the chain's
    # average surface normal, so it is not exactly x = 1: it is slightly
    # tilted, and projecting the chain's interior points onto it moves
    # them off x = 1 by a few hundredths of a millimetre. A 1e-6 filter
    # is about 45 times tighter than that measured tilt and finds only
    # the two corners, which are never moved. 0.05 is well inside the gap
    # to the cap's own interior points (nearest x is 0.75) so it selects
    # the chain and only the chain.
    on_plane = [
        point for point in piece["mid"]
        if abs(point[0] - 1.0) < 0.05
    ]
    # Exactly the subdivided chain: one point per round-doubling, plus
    # the closing point. A short count here means the chain silently lost
    # points rather than just failing to be found.
    assert len(on_plane) == 2 ** chosen["rounds"] + 1
    for point in on_plane:
        offset = sum((point[axis] - origin[axis]) * normal[axis] for axis in range(3))
        assert abs(offset) < 1e-9


def test_neighbours_agree_on_the_shared_cut_exactly():
    made, report = build()
    left = next(m for m in made if m["key"] == "c00")
    right = next(m for m in made if m["key"] == "c10")
    # Same 0.05 filter as test_a_joint_facet_is_flat, for the same reason:
    # the joint plane is slightly tilted, so a 1e-6 filter here selects
    # only the two welded corners, which both sides get by lifting the
    # same welded plan point and neither side ever projects. Agreement
    # there is close to tautological. The three interior chain points are
    # what this module was written to make agree, and a 1e-6 filter
    # silently drops them from the check.
    def shared(piece):
        found = sorted(
            (round(point[1], 12), tuple(point), tuple(piece["normals"][i]))
            for i, point in enumerate(piece["mid"]) if abs(point[0] - 1.0) < 0.05
        )
        assert len(found) == 2 ** report["rounds"] + 1
        return found
    # Exact equality, not a tolerance: both sides compute the same plane
    # from the same canonically ordered chain, so a difference would mean
    # a real disagreement rather than a rounding difference.
    assert shared(left) == shared(right)


def test_the_corner_residual_is_disclosed_and_bounded():
    _, report = build()
    # A corner belongs to two joints and one normal cannot lie in both
    # planes. Exactly one facet owns each corner, so the other joint is a
    # hair off flat there. The number is measured, not assumed.
    #
    # It is the sine of the angle between the stored normal and the
    # non-owning facet's plane, not a distance: on this fixture that is
    # 0.0104, which is 0.598 degrees, which is about 1 mm of deviation at
    # the shipped 0.2 m thickness, at the one corner where a real joint
    # meets a free rim edge on the steepest part of the dome. This
    # fixture's dome rises 0.4 over a 2 m span against 1 m pieces, more
    # curved relative to its pieces than the real vault is relative to
    # its 0.9 m ones, so this is a stress case, not a typical one. The
    # real export's own distribution is measured in
    # bench/scripts/cutting_measurements.py and docs/BENCH.md: a single
    # worst-corner number badly misrepresents a real cut's typical joint,
    # which is why report["corner_residual_stats"] carries the whole
    # distribution below and this field alone stays only the max.
    assert 0.0 < report["corner_residual"] < 0.02


def test_the_corner_residual_stats_carry_the_whole_distribution():
    _, report = build()
    stats = report["corner_residual_stats"]
    # Nine welded corners on this fixture: a 3x3 grid shared by four cells.
    assert stats["count"] == 9
    assert stats["min"] <= stats["median"] <= stats["p99"] <= stats["max"]
    # The max here is exactly the same number report["corner_residual"]
    # already carries: this is the same measurement, not a second one.
    assert stats["max"] == report["corner_residual"]
    assert stats["min"] >= 0.0
    for entry in stats["over"]:
        assert 0 <= entry["count"] <= stats["count"]
    # The worst corner belongs to at least one real course of this fixture.
    assert stats["worst_corner_courses"]
    assert all(course in (0, 1) for course in stats["worst_corner_courses"])


def test_corner_residuals_max_matches_the_report_and_counts_every_corner():
    p = studio("pieces")
    surface, _, _ = dome_surface()
    tess = four_cells()
    planes = p.facet_planes(tess, surface)
    owners = p.corner_owners(tess)
    residuals = p.corner_residuals(tess, surface, planes, owners)
    # One value per corner, not per cell visit: four cells share a 3x3
    # grid, but every corner appears exactly once regardless of how many
    # cells touch it.
    assert len(residuals) == 9
    _, report = build()
    assert max(residuals.values()) == report["corner_residual"]


def test_a_piece_is_watertight():
    made, _ = build()
    for piece in made:
        edges = {}
        directed = []
        for face in piece["faces"]:
            for i in range(len(face)):
                a, b = face[i], face[(i + 1) % len(face)]
                directed.append((a, b))
                key = (a, b) if a < b else (b, a)
                edges[key] = edges.get(key, 0) + 1
        assert all(count == 2 for count in edges.values()), piece["key"]
        # Undirected count alone would pass a flipped face: two faces that
        # both wind the same edge the same way still cover it twice. Every
        # directed edge appearing exactly once, with its reverse present,
        # is what actually proves the piece is consistently oriented.
        assert len(directed) == len(set(directed)), piece["key"]
        seen = set(directed)
        for a, b in directed:
            assert (b, a) in seen, piece["key"]


def test_facets_per_piece_stay_small():
    made, report = build()
    assert report["facets_per_piece"]["max"] <= 8
    assert report["facets_per_piece"]["median"] <= 6


def test_facets_per_piece_names_the_course_of_its_own_max():
    # A single max badly misrepresents the cut the same way the corner
    # residual's max does (see test_the_corner_residual_stats_carry_the_
    # whole_distribution): on a real export the piece with the most facets
    # sits in the rim course, not a typical interior one, so the report
    # names which course it is rather than leaving max to read as typical.
    _, report = build()
    fpp = report["facets_per_piece"]
    assert "max_course" in fpp
    assert fpp["max_course"] in (0, 1)
    # boundary_points_per_piece gets no such note: only facets_per_piece's
    # max is singled out for the rim-course explanation.
    assert "max_course" not in report["boundary_points_per_piece"]


def test_field_weights_sum_to_one_and_index_the_render_mesh():
    made, _ = build()
    _, vertices, _ = dome_surface()
    for piece in made:
        assert len(piece["sources"]) == len(piece["mid"])
        for weights in piece["sources"]:
            assert sum(weight for _, weight in weights) == pytest.approx(1.0)
            assert all(0 <= index < len(vertices) for index, _ in weights)


def test_a_support_under_a_piece_marks_it():
    p = studio("pieces")
    surface, _, _ = dome_surface()
    tess = four_cells()
    made, _ = p.segment_pieces(tess, surface, [[0.5, 0.5]])
    marked = [piece["key"] for piece in made if piece["is_support"]]
    assert marked == ["c00"]


def test_a_support_on_a_shared_edge_marks_both_neighbours():
    # tessellation.point_in_cell counts a boundary point as inside, so a
    # support that lands exactly on a joint is not this module's choice
    # to make one sided: both cells that share that joint are marked.
    # This is the same rule the ring and wedge binning this replaces
    # used, kept because four later tasks read is_support.
    p = studio("pieces")
    surface, _, _ = dome_surface()
    tess = four_cells()
    made, _ = p.segment_pieces(tess, surface, [[1.0, 0.5]])
    marked = sorted(piece["key"] for piece in made if piece["is_support"])
    assert marked == ["c00", "c10"]


def test_the_cap_follows_the_surface_within_the_chord_target():
    p = studio("pieces")
    cutting = studio("cutting")
    surface, _, _ = dome_surface()
    tess = four_cells()
    chosen = p.choose_rounds(tess, surface)
    assert chosen["rounds"] <= cutting.MAX_ROUNDS
    assert chosen["chord_mm"] <= 5.0 or chosen["limit"] == "rounds"


def running_bond():
    """Two 2 m cells below, three cells above offset by 1 m.

    A plain bonded pattern like this puts a T junction in the middle of
    three of these five cells' edges (both course 0 cells, and the middle
    course 1 cell): the row above's internal joints land in the middle of
    the row below's cells, and vice versa. That is exactly the shape a
    Grasshopper authored brick pattern imports as, not a shape either
    shipped generator produces (see the wave 6 fix round report).
    """

    t = studio("tessellation")
    raw = [
        {"key": "c0a", "course": 0, "outline": [[0, 0], [2, 0], [2, 1], [0, 1]], "holes": []},
        {"key": "c0b", "course": 0, "outline": [[2, 0], [4, 0], [4, 1], [2, 1]], "holes": []},
        {"key": "c1a", "course": 1, "outline": [[0, 1], [1, 1], [1, 2], [0, 2]], "holes": []},
        {"key": "c1b", "course": 1, "outline": [[1, 1], [3, 1], [3, 2], [1, 2]], "holes": []},
        {"key": "c1c", "course": 1, "outline": [[3, 1], [4, 1], [4, 2], [3, 2]], "holes": []},
    ]
    return t.build_tessellation(raw, "test", "generated", 1.0, 2)


def flat_surface(width=4.0, height=2.0, nx=8, ny=4):
    """A flat render mesh big enough to cover running_bond(), z = 0.

    Flat because this fixture is about triangulation topology, not
    curvature: a duplicate boundary point is a duplicate whether or not
    the surface it is lifted onto is curved.
    """

    cutting = studio("cutting")
    vertices = [
        [i * width / nx, j * height / ny, 0.0]
        for j in range(ny + 1) for i in range(nx + 1)
    ]
    faces = []
    n = nx + 1
    for j in range(ny):
        for i in range(nx):
            faces.append([j * n + i, j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i])
    return cutting.Surface(vertices, faces)


def test_a_t_junction_produces_no_duplicate_cap_points():
    # Before the ear_clip fix, three of these five cells shipped a
    # degenerate triangle at their T junction, stranding its subdivision
    # points as extra, duplicate positions in mid: 28 duplicates in each
    # of the three affected cells (84 total), all sitting on the joint
    # line. Worse, those duplicated points sat past the welded count, so
    # the corner ownership pass skipped them and kept the raw surface
    # normal instead of the owner projected one, which a neighbour across
    # that joint would not agree with. No duplicates at all is the
    # measure that both problems are gone, not just the visible one.
    p = studio("pieces")
    surface = flat_surface()
    tess = running_bond()
    made, _ = p.segment_pieces(tess, surface, [])
    for piece in made:
        positions = [tuple(point) for point in piece["mid"]]
        assert len(positions) == len(set(positions)), piece["key"]


def test_a_clamp_free_cut_reports_no_magnitude_at_all():
    _, report = build()
    # The four cell fixture covers exactly the surface it sits on, so
    # nothing is off the mesh. A zero count has to come with zero
    # magnitudes, not with a leftover number from somewhere.
    assert report["clamped_points"] == 0
    assert report["clamped_max_m"] == 0.0
    assert report["clamped_median_m"] == 0.0


def saddle_z(x, y):
    return 0.25 * (x * x - y * y)


def saddle_surface(side=8):
    """A side by side quad mesh over [-2, 2] squared, lifted into a
    hyperbolic paraboloid: negative Gaussian curvature everywhere but the
    centre point, same z = 0.25 * (x*x - y*y) formula as
    tests/fixtures/saddle_contract.json (the Cutting Truth wave's Task 1
    fixture, added because dome_surface/flat_surface above are both
    synclastic or flat). Built directly, mirroring dome_surface()'s own
    pattern, rather than through the equilibrium/formGraph contract that
    JSON file carries for the TNA pipeline: pieces.py's own tests never
    load a contract, they build the render mesh Surface straight.
    """

    cutting = studio("cutting")
    step = 4.0 / side
    vertices = [
        [-2.0 + i * step, -2.0 + j * step, saddle_z(-2.0 + i * step, -2.0 + j * step)]
        for j in range(side + 1) for i in range(side + 1)
    ]
    faces = []
    n = side + 1
    for j in range(side):
        for i in range(side):
            faces.append([j * n + i, j * n + i + 1, (j + 1) * n + i + 1, (j + 1) * n + i])
    return cutting.Surface(vertices, faces), vertices, faces


def saddle_cells(cell=2.0):
    """An n by n grid of `cell` metre wide cells covering the same
    [-2, 2] squared span, one course per row. cell=2.0 (the default) is
    the original four cell, two course layout; a smaller cell subdivides
    the same span into more, smaller pieces, which is what K2's seat-gap
    monotonicity test (below) needs two cuts of the same surface for.
    """

    t = studio("tessellation")
    n = round(4.0 / cell)
    raw = []
    for j in range(n):
        for i in range(n):
            x0, y0 = -2.0 + i * cell, -2.0 + j * cell
            raw.append({
                "key": "s{}{}".format(i, j),
                "course": j,
                "outline": [
                    [x0, y0], [x0 + cell, y0],
                    [x0 + cell, y0 + cell], [x0, y0 + cell],
                ],
                "holes": [],
            })
    return t.build_tessellation(raw, "test", "generated", cell, n)


def test_normals_are_unit_length_on_the_saddle():
    """K1 (cutting truth, 2026-08-17)'s extrusion (buildPieceMeshes,
    studio.js) offsets each shipped point by 0 (the bottom/intrados cap)
    or thickness * taperAt(course) (the top/extrados cap) along its own
    shipped normal. pieces.py ships no thickness and builds no solid
    itself, so this cannot exercise that extrusion, or even its shape
    (offset 0 reproducing the shipped point and a positive offset along a
    normal never landing behind it are both true by construction for ANY
    unit vector and ANY non-negative offset -- they were never a real
    check of buildPieceMeshes's own arithmetic). The extrusion itself is
    now pinned directly, against the actual JS source, in test_static.py's
    test_pieces_extrude_upward_from_the_intrados.

    What this test pins is the one numeric precondition that extrusion
    genuinely depends on and that segment_pieces could genuinely violate:
    every shipped normal is a true unit vector, so a client-side offset of
    thickness * taperAt(course) actually moves a point that distance, not
    some other. Checked on a genuinely doubly curved fixture (the saddle:
    negative Gaussian curvature in both directions at once, unlike the
    dome/flat fixtures above) rather than the dome, since a non-unit
    normal is more likely to slip through the facet-plane projection step
    on a saddle's mixed curvature than on a dome's single-signed one.
    """

    p = studio("pieces")
    surface, _, _ = saddle_surface()
    tess = saddle_cells()
    made, _ = p.segment_pieces(tess, surface, [])
    assert made, "the saddle fixture must actually produce pieces"
    for piece in made:
        for normal in piece["normals"]:
            length = math.sqrt(sum(component * component for component in normal))
            assert length == pytest.approx(1.0, abs=1e-6), piece["key"]


def test_clamped_points_are_disclosed_in_metres_not_only_counted():
    """A count with no magnitude cannot be read.

    On the real Trial 2 export at the default 0.9 m the clamp reaches
    0.0523 m at its worst and 0.0246 m at the median across 137 points,
    which is ten times cutting.CHORD_TARGET rather than the float's
    rounding the code once claimed. Here the same disclosure is checked on
    a cell that deliberately overhangs its own surface by a known 0.05 m,
    the same order as the real one and small enough to verify by hand.
    """

    p = studio("pieces")
    t = studio("tessellation")
    surface, _, _ = dome_surface()          # a dome over [0, 2] squared
    overhang = 0.05
    tess = t.build_tessellation(
        [{
            "key": "over", "course": 0,
            "outline": [[0.0, 0.0], [2.0 + overhang, 0.0],
                        [2.0 + overhang, 2.0], [0.0, 2.0]],
            "holes": [],
        }],
        "test", "generated", 1.0, 1,
    )
    _, report = p.segment_pieces(tess, surface, [])

    assert report["clamped_points"] > 0
    # The far edge sits exactly overhang metres past the mesh, and nothing
    # on this cell is further out than that.
    assert report["clamped_max_m"] == pytest.approx(overhang)
    assert 0.0 < report["clamped_median_m"] <= report["clamped_max_m"]


def test_fit_seat_plane_is_none_on_a_genuinely_degenerate_line():
    """Minor, fix round 1 on K2 (2026-08-17): four collinear points have a
    diagonal covariance matrix with TWO tied zero-variance axes (y and z
    both carry no spread at all) -- a genuinely degenerate 1D spread with
    no single least-varying direction, matching fit_seat_plane's own
    documented "None on a genuinely degenerate spread" contract. Before
    this fix, the diagonal fast path picked whichever tied axis Python's
    min() happened to see first and shipped that arbitrary plane instead
    of None -- this exercises exactly the code path the review's minor
    point named, not the general eigensolve branch
    (test_fit_seat_plane_recovers_a_known_tilted_plane already covers
    that one, and a tied pair there is naturally caught by every pairwise
    row cross product coming back zero).
    """

    p = studio("pieces")
    points = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [2.0, 0.0, 0.0], [3.0, 0.0, 0.0]]
    assert p.fit_seat_plane(points, [0.0, 0.0, 1.0]) is None


def test_fit_seat_plane_recovers_a_known_tilted_plane():
    """K2 (cutting truth, 2026-08-17): the eigensolve itself, independent
    of segment_pieces or any real cut. Five points placed exactly on a
    known, deliberately tilted plane (not axis aligned, so this cannot
    pass by only handling the trivial z = constant case): the fit must
    recover that plane's own normal and a point on that plane, oriented
    to agree with a reference on the true normal's own side.
    """

    p = studio("pieces")

    def z(x, y):
        return 0.5 * x + 0.25 * y + 1.0

    points = [
        [0.0, 0.0, z(0.0, 0.0)],
        [3.0, 0.0, z(3.0, 0.0)],
        [3.0, 2.0, z(3.0, 2.0)],
        [0.0, 2.0, z(0.0, 2.0)],
        [1.5, 1.0, z(1.5, 1.0)],
    ]
    raw_normal = [-0.5, -0.25, 1.0]
    length = math.sqrt(sum(c * c for c in raw_normal))
    true_normal = [c / length for c in raw_normal]

    fit = p.fit_seat_plane(points, true_normal)
    assert fit is not None
    origin, normal = fit
    for axis in range(3):
        assert normal[axis] == pytest.approx(true_normal[axis], abs=1e-9)
    # Every point is exactly on the known plane, so the fitted origin must
    # be too: this checks the recovered point, not only the normal.
    residual = sum((origin[i] - points[0][i]) * normal[i] for i in range(3))
    assert residual == pytest.approx(0.0, abs=1e-9)
    # Orientation: passing the true normal's own negation as the
    # reference must flip the fitted sign to match it, not keep whichever
    # sign the eigensolve happened to return.
    flipped = p.fit_seat_plane(points, [-c for c in true_normal])
    for axis in range(3):
        assert flipped[1][axis] == pytest.approx(-normal[axis], abs=1e-9)


def test_seat_planes_are_exact_and_gap_free_on_a_flat_surface():
    """An oracle check independent of the eigensolve's own algebra: cut
    from a genuinely flat (z = 0) surface, every jointed piece's fitted
    seat plane must come out horizontal (normal along +/-z) with a seat
    gap of (near enough) zero, since a flat cut of a flat surface is
    already exactly seated -- there is no honest gap to disclose at all.
    """

    p = studio("pieces")
    surface = flat_surface()
    tess = running_bond()
    made, report = p.segment_pieces(tess, surface, [])
    assert made
    for piece in made:
        plane = piece["seat_plane"]
        normal = plane["normal"]
        assert abs(normal[0]) < 1e-9 and abs(normal[1]) < 1e-9, piece["key"]
        assert abs(normal[2]) == pytest.approx(1.0, abs=1e-9), piece["key"]
        assert piece["seat_gap"] == pytest.approx(0.0, abs=1e-9), piece["key"]
    assert report["seat_gap_stats"]["max"] == pytest.approx(0.0, abs=1e-9)


def test_the_prism_the_client_builds_is_flat_and_constant_thickness():
    """Server-side pin on the geometry buildPieceMeshes's K2 branch
    constructs: project every one of a jointed piece's mid points onto
    its own shipped seat plane (the belly, exactly as studio.js does),
    offset the same points by an arbitrary thickness along the plane's
    normal (the top), and check both caps stay exactly flat against their
    own plane and a constant distance apart. This is a division of
    labour, not a simulation of the deployed JS: it verifies the SERVER's
    own contribution the client's formula depends on -- a correctly unit
    normal and a plane the piece's own points are genuinely near -- the
    same role test_normals_are_unit_length_on_the_saddle plays for K1;
    the client formula itself is pinned separately, against the real
    source, in test_static.py's test_jointed_pieces_take_the_prismatic_
    path.
    """

    p = studio("pieces")
    surface, _, _ = saddle_surface()
    tess = saddle_cells()
    made, _ = p.segment_pieces(tess, surface, [])
    thickness = 0.2
    assert made
    for piece in made:
        origin, normal = piece["seat_plane"]["origin"], piece["seat_plane"]["normal"]
        length = math.sqrt(sum(c * c for c in normal))
        assert length == pytest.approx(1.0, abs=1e-9), piece["key"]
        for point in piece["mid"]:
            d = sum((point[i] - origin[i]) * normal[i] for i in range(3))
            belly = [point[i] - d * normal[i] for i in range(3)]
            belly_d = sum((belly[i] - origin[i]) * normal[i] for i in range(3))
            assert abs(belly_d) <= 1e-9, piece["key"]
            top = [belly[i] + normal[i] * thickness for i in range(3)]
            top_d = sum((top[i] - origin[i]) * normal[i] for i in range(3))
            assert abs(top_d - thickness) <= 1e-9, piece["key"]


def test_the_prism_shrink_stays_on_plane_at_a_real_joint_gap():
    """I1, fix round 1 on K2 (2026-08-17): buildPieceMeshes's joint-gap
    shrink scales (point - centre) in raw XYZ, and for a prism centre
    sits at the extrusion's mid thickness -- on neither cap's own plane --
    so (point - centre) always carries a constant nonzero component along
    the plane normal, which a uniform scale shrank too: at the default
    20 mm gap the belly lifted 1.03 mm off its own seat plane and the
    block thinned to 197.93 mm of a nominal 200. The coverage hole the
    review exploited was exactly that
    test_the_prism_the_client_builds_is_flat_and_constant_thickness above
    never applied any shrink at all. This replicates the CLIENT's exact
    FIXED arithmetic (decompose into a plane-normal component, left
    alone, and an in-plane component, the only part scaled -- see
    test_static.py's test_prism_shrink_moves_in_plane_only for the pin
    against the real source) in Python, at that same 20 mm gap, and
    checks both caps stay on plane and the thickness survives exactly.
    """

    p = studio("pieces")
    surface, _, _ = saddle_surface()
    tess = saddle_cells()
    made, _ = p.segment_pieces(tess, surface, [])
    thickness = 0.2
    gap = 0.02
    assert made
    for piece in made:
        origin, normal = piece["seat_plane"]["origin"], piece["seat_plane"]["normal"]
        belly = []
        for point in piece["mid"]:
            d = sum((point[i] - origin[i]) * normal[i] for i in range(3))
            belly.append([point[i] - d * normal[i] for i in range(3)])
        top = [[b[i] + normal[i] * thickness for i in range(3)] for b in belly]
        points = top + belly  # order does not matter for centre/extent below

        n = len(points)
        centre = [sum(pt[i] for pt in points) / n for i in range(3)]
        extent = max(
            math.sqrt(sum((pt[i] - centre[i]) ** 2 for i in range(3)))
            for pt in points
        )
        extent = max(extent, 1e-9)
        shrink = max(0.0, 1.0 - (gap / 2.0) / extent)
        assert shrink < 1.0, "the fixture must actually exercise the shrink"

        def shrunk(point, centre=centre, normal=normal, shrink=shrink):
            delta = [point[i] - centre[i] for i in range(3)]
            along = sum(delta[i] * normal[i] for i in range(3))
            axis = [along * normal[i] for i in range(3)]
            return [
                centre[i] + (delta[i] - axis[i]) * shrink + axis[i]
                for i in range(3)
            ]

        for b in belly:
            plane_offset = sum(
                (shrunk(b)[i] - origin[i]) * normal[i] for i in range(3)
            )
            assert abs(plane_offset) <= 1e-9, piece["key"]
        for t in top:
            plane_offset = sum(
                (shrunk(t)[i] - origin[i]) * normal[i] for i in range(3)
            )
            assert abs(plane_offset - thickness) <= 1e-9, piece["key"]


def test_seat_gap_stats_are_disclosed_and_the_max_is_positive_on_the_saddle():
    """A curved form MUST leave a gap under a flat cut: seat_gap_stats
    has to be present and its max strictly positive on the doubly curved
    saddle fixture, never silently reading as clean. Each piece's own
    seat_gap is also cross checked against the shipped plane and mid
    points it was supposedly measured from.
    """

    p = studio("pieces")
    surface, _, _ = saddle_surface()
    tess = saddle_cells()
    made, report = p.segment_pieces(tess, surface, [])
    stats = report["seat_gap_stats"]
    assert stats["count"] == len(made)
    assert stats["max"] > 0.0, "a flat cut on a curved form must leave a gap"
    assert 0.0 <= stats["median"] <= stats["max"]
    for piece in made:
        origin, normal = piece["seat_plane"]["origin"], piece["seat_plane"]["normal"]
        worst = max(
            abs(sum((point[i] - origin[i]) * normal[i] for i in range(3)))
            for point in piece["mid"]
        )
        assert piece["seat_gap"] == pytest.approx(worst, abs=1e-12), piece["key"]


def test_seat_gaps_grow_with_piece_size_on_the_saddle():
    """A flat cut's deviation from a curved form grows with the square of
    the piece's own footprint (the second order term of the surface's own
    curvature), so a coarser cut of the SAME saddle span must show a
    strictly larger worst seat gap than a finer cut of it.
    """

    p = studio("pieces")
    surface, _, _ = saddle_surface()
    _, coarse = p.segment_pieces(saddle_cells(cell=2.0), surface, [])
    _, fine = p.segment_pieces(saddle_cells(cell=0.5), surface, [])
    assert fine["seat_gap_stats"]["max"] > 0.0
    assert coarse["seat_gap_stats"]["max"] > fine["seat_gap_stats"]["max"], (
        "a bigger flat-cut piece must leave a bigger gap against the same "
        "curved surface, not a smaller or equal one"
    )


def test_monolithic_bands_ship_no_seat_plane_at_all():
    """Sprayed concrete's cut (pattern monolithic-bands) is moulded on the
    formwork and stays genuinely curved: it must ship no seat_plane and no
    seat_gap on any piece, and seat_gap_stats must read as a true empty
    distribution, not a hopeful zero hiding a bug that skipped every piece
    silently.
    """

    p = studio("pieces")
    t = studio("tessellation")
    surface, _, _ = saddle_surface()
    raw = [{
        "key": "band0", "course": 0,
        "outline": [[-2.0, -2.0], [2.0, -2.0], [2.0, 2.0], [-2.0, 2.0]],
        "holes": [],
    }]
    tess = t.build_tessellation(raw, "monolithic-bands", "generated", 4.0, 1)
    made, report = p.segment_pieces(tess, surface, [])
    assert made
    for piece in made:
        assert "seat_plane" not in piece, piece["key"]
        assert "seat_gap" not in piece, piece["key"]
    assert report["seat_gap_stats"] == {"count": 0, "median": 0.0, "max": 0.0}
