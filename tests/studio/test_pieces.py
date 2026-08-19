"""pieces.py builds the casting the viewer draws, from the cut.

The fixture is a shallow dome cut into four cells, so a flat joint is a
real constraint rather than a trivially satisfied one, and so that two
neighbours have something to disagree about.
"""

from __future__ import annotations

import copy
import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


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


class _Cancelled(Exception):
    """A stand-in for bundle.py's own CutSuperseded (cut cancellation,
    2026-08-19): pieces.py must never import or know that type exists, so
    this test brings its own to prove the raise really is the caller's
    business, unmodified."""


def test_checkpoint_is_called_at_least_once_per_cell():
    """The checkpoint callable fires once at the TOP of every iteration of
    the per-cell loop, before that cell's own triangulation begins -- so a
    counting callable on this four-cell fixture sees at least one call per
    cell, including any cell the loop goes on to drop as degenerate (none
    are, on this fixture; the >= is the honest bound, not ==, because a
    future fixture with drops would still satisfy it)."""

    p = studio("pieces")
    surface, _, _ = dome_surface()
    tess = four_cells()
    calls = []
    made, _ = p.segment_pieces(
        tess, surface, [[0.0, 0.0]], checkpoint=lambda: calls.append(1)
    )
    assert len(calls) >= len(tess["cells"])
    assert len(made) == len(tess["cells"])


def test_a_raising_checkpoint_aborts_the_loop_without_mutating_the_input():
    """segment_pieces only ever reads tess; the exception a checkpoint
    raises on the second cell must propagate unmodified, and the caller's
    own tess dict must come back byte for byte the same as before the
    call -- not half rewritten by whatever the first cell's own work
    touched before the abort."""

    p = studio("pieces")
    surface, _, _ = dome_surface()
    tess = four_cells()
    before = copy.deepcopy(tess)
    calls = []

    def checkpoint():
        calls.append(1)
        if len(calls) == 2:
            raise _Cancelled("superseded")

    with pytest.raises(_Cancelled):
        p.segment_pieces(tess, surface, [[0.0, 0.0]], checkpoint=checkpoint)
    # Aborted on the second cell: the loop never reached a third call.
    assert len(calls) == 2
    assert tess == before


def test_checkpoint_none_is_byte_identical_to_no_checkpoint_at_all():
    """checkpoint=None (the default) must produce the exact same output as
    never passing the parameter at all: the whole point of a default that
    matches "not called," not merely a default that happens to also work."""

    p = studio("pieces")
    surface_implicit, _, _ = dome_surface()
    made_implicit, report_implicit = p.segment_pieces(
        four_cells(), surface_implicit, [[0.0, 0.0]]
    )
    surface_explicit, _, _ = dome_surface()
    made_explicit, report_explicit = p.segment_pieces(
        four_cells(), surface_explicit, [[0.0, 0.0]], checkpoint=None
    )
    assert made_explicit == made_implicit
    assert report_explicit == report_implicit


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


def test_rim_corners_snap_onto_the_boundary_in_plan_on_the_saddle_surface():
    """Rim-rectangular fix (2026-08-18), ask 1: an outline point whose plan
    position falls outside the surface's support now moves ONTO the
    boundary polyline in plan, not merely samples its z/normal/weights
    there (cutting.Surface.lift, pieces._lift). Same overhang pattern as
    test_clamped_points_are_disclosed_in_metres_not_only_counted, on the
    saddle surface (doubly curved, the Cutting Truth wave's own Task 1
    fixture, tests/fixtures/saddle_contract.json's exact z formula) with a
    boundary attached this time, so the K3 projection engages instead of
    the last-resort clamp: the far edge, which used to sit overhang metres
    past the surface, now sits ON it.
    """

    p = studio("pieces")
    t = studio("tessellation")
    surface, _, _ = saddle_surface()           # [-2, 2] squared
    surface.boundary = [[-2.0, -2.0], [2.0, -2.0], [2.0, 2.0], [-2.0, 2.0]]
    overhang = 0.05
    tess = t.build_tessellation(
        [{
            "key": "over", "course": 0,
            "outline": [[-2.0, -2.0], [2.0 + overhang, -2.0],
                        [2.0 + overhang, 2.0], [-2.0, 2.0]],
            "holes": [],
        }],
        "test", "generated", 4.0, 1,
    )
    made, report = p.segment_pieces(tess, surface, [])
    assert made
    assert report["clamped_points"] == 0
    assert report["projected_points"] > 0

    for piece in made:
        for point in piece["mid"]:
            assert -2.0 - 1e-6 <= point[0] <= 2.0 + 1e-6, piece["key"]
            assert -2.0 - 1e-6 <= point[1] <= 2.0 + 1e-6, piece["key"]


def test_a_piece_that_collapses_below_three_corners_is_dropped_and_disclosed():
    """Rim-rectangular fix (2026-08-18): guard degeneracy. This cell's own
    four raw corners form a real 0.02 m square (a genuine shape, not
    already a sliver), sitting entirely past the top right corner of the
    surface's own unit-square footprint in both x and y. Every one of the
    four is nearer to that single corner (1, 1) than to either adjacent
    edge, so all four project onto the identical nearest boundary point.
    After the move, this "cell" has exactly one distinct corner left --
    nowhere near the 3 a polygon needs -- so it is dropped entirely rather
    than shipped as a degenerate or self-overlapping casting, and its key
    is disclosed in report["degenerate_dropped"], not silently omitted.
    """

    p = studio("pieces")
    t = studio("tessellation")
    surface = flat_surface(width=1.0, height=1.0, nx=4, ny=4)
    surface.boundary = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

    tess = t.build_tessellation(
        [{
            "key": "collapsing", "course": 0,
            "outline": [
                [1.05, 1.05], [1.03, 1.05], [1.03, 1.03], [1.05, 1.03],
            ],
            "holes": [],
        }],
        "test", "generated", 1.0, 1,
    )
    made, report = p.segment_pieces(tess, surface, [])
    assert made == []
    assert report["degenerate_dropped"] == ["collapsing"]


def test_a_move_induced_fold_from_non_consecutive_corners_is_caught():
    """Review fix (2026-08-18), MUST FIX 7: _distinct_ring only collapses
    CONSECUTIVE duplicates, so a ring shaped A, B, A, C -- corner 0 and
    corner 2 (NOT adjacent; corner 1 sits between them in the ring) both
    project onto the identical nearest boundary point, while corner 1 and
    corner 3 stay put -- keeps 4 "distinct" points by that check alone,
    even though the moved ring now pinches through itself at the shared
    point. This is invisible to tessellation.build_tessellation's own
    folded/slivers report, computed on the RAW, pre-lift outline: this
    exact 4 point ring is genuinely simple before the move (confirmed
    below) and only self-intersects after it.

    Built by hand rather than found on a real export (the real notch
    cases are rare enough that hunting for this specific corner-order
    coincidence was not worth it): corners 0 and 2 both sit at x > 1 (off
    the unit square, both nearest to the same point on the right edge,
    (1.0, 0.5), regardless of exactly how far right each one is); corners
    1 and 3 sit at x = 0.5, safely inside.
    """

    p = studio("pieces")
    t = studio("tessellation")
    surface = flat_surface(width=1.0, height=1.0, nx=4, ny=4)
    surface.boundary = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

    raw_outline = [[1.05, 0.5], [0.5, 0.9], [1.03, 0.5], [0.5, 0.1]]
    assert t._is_simple(raw_outline), "the fixture's own raw ring must be simple"
    assert not t._is_simple([[1.0, 0.5], [0.5, 0.9], [1.0, 0.5], [0.5, 0.1]]), (
        "the fixture must actually self-intersect once projected, or this "
        "test proves nothing"
    )

    tess = t.build_tessellation(
        [{"key": "foldme", "course": 0, "outline": raw_outline, "holes": []}],
        "test", "generated", 1.0, 1,
    )
    # Invisible to the pre-lift check: the whole point of this defect.
    assert tess["report"]["folded"] == []
    assert tess["report"]["slivers"] == []

    made, report = p.segment_pieces(tess, surface, [])
    assert made == []
    assert report["degenerate_dropped"] == ["foldme"]


def test_a_malformed_authored_hole_still_fails_loudly_not_dropped():
    """Review fix (2026-08-18), MUST FIX 3: the except clause guarding
    _cap in segment_pieces must not swallow cutting.bridge_holes's own
    ValueError ("a hole is not inside its outline"), raised for a
    genuinely malformed AUTHORED hole -- an authoring error that has to
    reach the caller as a real exception, not be silently reclassified as
    a degenerate drop the way an untriangulatable ring now is (see
    pieces.UntriangulatableCell). This hole sits entirely outside its own
    outline, on purpose.
    """

    p = studio("pieces")
    t = studio("tessellation")
    surface = flat_surface()
    tess = t.build_tessellation(
        [{
            "key": "bad-hole", "course": 0,
            "outline": [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
            "holes": [[[2.0, 0.4], [2.2, 0.4], [2.2, 0.6], [2.0, 0.6]]],
        }],
        "test", "generated", 1.0, 1,
    )
    with pytest.raises(ValueError, match="not inside its outline"):
        p.segment_pieces(tess, surface, [])


def test_choose_rounds_skips_an_untriangulatable_cell_instead_of_crashing():
    """Review fix (2026-08-18), MUST FIX 4: choose_rounds (through its own
    call to _chord_deviation) reaches _cap BEFORE segment_pieces's own
    per-cell guard ever runs, to decide the round count every cell then
    subdivides at. An untriangulatable cell here used to crash the whole
    cut rather than merely being dropped later.

    This exact 6 point ring is not synthetic: it is the real, welded
    course-1 outline of cell c1p67 on the real Trial 2 export at 0.30 m
    (translated so its first point sits at the origin; translation does
    not change whether ear_clip can find an ear), the untriangulatable
    cell test_an_untriangulatable_cell_is_dropped_not_crashed already
    covers at the segment_pieces level. This test pins the same shape of
    guard one level earlier, directly against choose_rounds.
    """

    p = studio("pieces")
    t = studio("tessellation")
    surface = flat_surface(width=4.0, height=4.0, nx=8, ny=8)
    bad_ring = [
        [0.0, 0.0], [-0.0025253425958640108, -0.0008205391412818841],
        [0.7160146446535371, -1.0524795182665843],
        [0.45262581780893907, -0.6843516657593325],
        [0.35506881662975687, -0.5079613556404095],
        [-0.301073808142152, 0.42352151136338634],
    ]
    tess = t.build_tessellation(
        [
            {"key": "good", "course": 0,
             "outline": [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0]],
             "holes": []},
            {"key": "bad", "course": 0, "outline": bad_ring, "holes": []},
        ],
        "test", "generated", 1.0, 1,
    )
    chosen = p.choose_rounds(tess, surface)
    assert chosen["rounds"] >= 0
    # The real point: segment_pieces itself still runs end to end, past
    # choose_rounds, and drops the same cell it would have crashed on.
    made, report = p.segment_pieces(tess, surface, [])
    assert "bad" in report["degenerate_dropped"]
    assert [piece["key"] for piece in made] == ["good"]


def test_a_normal_piece_ships_with_no_degenerate_drops():
    """The guard degeneracy fix must not fire on ordinary geometry: the
    four cell fixture's own report carries an empty, present (not absent)
    degenerate_dropped list."""

    _, report = build()
    assert report["degenerate_dropped"] == []


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


def trial2_domain():
    """The real Trial 2 plan domain (domain.plan_domain's own return
    value), committed by tests/studio/make_fixtures.py -- the same source
    test_generators.py's own real-geometry regression pin reads. Reused
    here rather than requiring the 2521 vertex export file: everything
    domain.radius_at needs to reproduce the real rim's own notch (axis,
    loop, thetas) is in this JSON.
    """

    fixture = json.loads(
        (FIXTURES / "trial-2-tessellation.json").read_text(encoding="utf-8")
    )
    return fixture["domain"]


def trial2_surface(domain):
    """A flat render mesh whose own footprint IS the real Trial 2 plan's
    boundary polygon exactly, triangulated by cutting.ear_clip.

    None of dome_surface/flat_surface/saddle_surface above ever exercises
    cutting.Surface.lift's off-mesh fallback at all: every one of them was
    built to tile its own surface's footprint exactly (see
    test_a_clamp_free_cut_reports_no_magnitude_at_all), so nothing an
    outline generates ever lands off mesh. This surface's footprint is
    instead the real, irregular, notched rim itself (domain["loop"]), so
    an outline point domain.radius_at places outside that footprint --
    exactly the real defect K3 fixes -- genuinely lands off this mesh too,
    the same way it does on the real 2521 vertex render mesh.
    """

    cutting = studio("cutting")
    loop = domain["loop"]
    vertices = [[p[0], p[1], 0.0] for p in loop]
    triangles = cutting.ear_clip(list(range(len(loop))), loop)
    surface = cutting.Surface(vertices, [list(triangle) for triangle in triangles])
    surface.boundary = [list(p) for p in loop]
    return surface


def test_rim_points_project_to_the_boundary_on_the_real_trial_2_plan():
    """K3 (cutting truth, 2026-08-17): before this fix, domain.radius_at's
    outermost-crossing rule put some course-0 outline points (all inside
    the real Trial 2 export's own plus/minus 125.4 degree rim notch, see
    domain.WOBBLE_TOLERANCE) outside the true rim, and cutting.Surface.
    lift's only fallback clamped them into the nearest render face by up
    to 52.3 mm (Task 1's own baseline measurement, real Trial 2 export,
    0.9 m, the studio's own default size).

    This fixture is the one that actually exercises the defect (see
    trial2_surface's own docstring for why the others in this file do
    not): every off-mesh point here is real, not synthetic.
    """

    g = studio("generators")
    p = studio("pieces")
    cutting = studio("cutting")
    domain = trial2_domain()
    surface = trial2_surface(domain)
    tess = g.generate("bonded-courses", domain, 0.9)
    made, report = p.segment_pieces(tess, surface, [])
    assert made

    # The hard assert the spec's own gate names: whatever still needs the
    # old nearest-face clamp (the last resort now, not the primary
    # fallback) is within the cut's own edge tolerance of the true
    # surface -- not merely closer than it used to be.
    assert report["clamped_max_m"] <= cutting.CHORD_TARGET
    # Measured, not merely bounded: on this fixture nothing needs the old
    # clamp at all.
    assert report["clamped_points"] == 0

    # The mechanism actually engaged: this is not a fixture where nothing
    # was ever off the mesh to begin with (contrast
    # test_a_clamp_free_cut_reports_no_magnitude_at_all).
    assert report["projected_points"] > 0
    # Row-uniform courses fix (2026-08-18): generators._divisions now
    # places head joints at equal ARC LENGTH rather than equal angle, so
    # course 0's own piece boundaries (and with them, which exact points
    # need the boundary-polyline projection at all) moved from the K3
    # baseline this test used to pin (0.052321 m). Re-measured on this
    # same fixture, same size, after that fix: 0.046405 m. Still the same
    # order as the K3 baseline (both are governed by the same real rim
    # notch), not a coincidental match to the old number.
    #
    # Rim remainder fix (2026-08-19): domain.radius_at now returns the
    # first exit rather than the outermost crossing (see
    # docs/superpowers/specs/2026-08-19-rim-remainder-design.md), so an
    # f = 1 outline point can no longer land on the far side of the
    # notch's own gap -- most of what needed this projection at all was
    # exactly that population. Re-measured on this same fixture, same
    # size: 0.008679 m, an 81 percent cut in the worst overshoot, not a
    # rounding accident.
    assert report["projected_max_m"] == pytest.approx(0.008679, abs=1e-4)


def _nearest_point_on_loop(loop, x, y):
    import math
    best_d = None
    best_p = None
    n = len(loop)
    for i in range(n):
        a, b = loop[i], loop[(i + 1) % n]
        ex, ey = b[0] - a[0], b[1] - a[1]
        length2 = ex * ex + ey * ey
        if length2 < 1e-24:
            near = (a[0], a[1])
        else:
            t = min(1.0, max(0.0, ((x - a[0]) * ex + (y - a[1]) * ey) / length2))
            near = (a[0] + t * ex, a[1] + t * ey)
        d = (x - near[0]) ** 2 + (y - near[1]) ** 2
        if best_d is None or d < best_d:
            best_d = d
            best_p = near
    return best_p


def test_no_drawn_cap_point_sits_outside_the_true_rim_on_the_real_trial_2_plan():
    """The real-export spot check the rim-rectangular fix's own testing
    contract asks for: every cap point cutting.Surface.lift actually
    PROJECTS (found["projected"] is True -- the population this fix
    moves) must land on the true plan boundary polygon, within 1e-6 m, on
    this real, notched, 240-vertex rim.

    Deliberately narrower than "every point piece["mid"] ships": a point
    that lands on the render mesh unaided (never projected at all) can
    still sit up to CHORD_TARGET away from the true curved rim by
    construction -- that is what course 0's own boundary simplification
    tolerance means (see generators._simplify_boundary_run and
    docs/BENCH.md's K3 section) -- and this fix does not touch that
    population or its own, already-disclosed tolerance. What this fix
    promises, and what this test checks, is narrower and unconditional:
    whatever DID need the boundary-polyline projection sits ON the true
    boundary afterward.
    """

    g = studio("generators")
    p = studio("pieces")
    cutting = studio("cutting")
    domain = trial2_domain()
    surface = trial2_surface(domain)
    loop = domain["loop"]
    tess = g.generate("bonded-courses", domain, 0.9)

    chosen = p.choose_rounds(tess, surface)
    rounds = chosen["rounds"]
    checked = 0
    for cell in tess["cells"]:
        points, triangles, _chains = p._cap(tess, cell, rounds)
        used = sorted({index for triangle in triangles for index in triangle})
        for index in used:
            plan = points[index]
            found = surface.lift(plan[0], plan[1])
            if not found["projected"]:
                continue
            checked += 1
            near = _nearest_point_on_loop(loop, found["x"], found["y"])
            distance = math.hypot(found["x"] - near[0], found["y"] - near[1])
            assert distance <= 1e-6, (cell["key"], plan, found["x"], found["y"], distance)
    # The fixture must actually exercise points that needed the move (see
    # trial2_surface's own docstring): a check that only ever sees points
    # already on the mesh proves nothing about the fix.
    assert checked > 0


def test_an_untriangulatable_cell_is_dropped_not_crashed():
    """Rim-rectangular fix (2026-08-18): a cell whose own ring is too
    degenerate for cutting.ear_clip to find any ear at all -- not merely a
    self-crossing ring it can still triangulate inside out, the ordinary
    "folded" case tessellation.py's own report already names and draws --
    used to raise out of pieces.segment_pieces and crash the whole cut.
    Now it is caught, the piece is dropped, and its key is disclosed in
    report["degenerate_dropped"], the same guard-degeneracy machinery, one
    step earlier, before any outline point has even been lifted.

    Rim remainder (2026-08-19): this used to be pinned against the real
    Trial 2 domain at 0.30 m, where two course-1 cells near the rim notch
    (c1p67, c1p118) came out both near-zero area and topologically
    self-crossing. domain.radius_at now returns the first exit rather
    than the outermost crossing (see docs/superpowers/specs/2026-08-19-
    rim-remainder-design.md), and that alone was the entire mechanism:
    measured directly, neither cell -- nor any other, at any of the 55
    swept sizes -- is untriangulatable any more (see
    .superpowers/sdd/2026-08-19-rim-remainder-probe/report.md section 5).
    The drop-not-crash contract itself was never about that particular
    geometry, so it is pinned here instead against a synthetic hand-built
    cell: four points on a single straight line, an outline that welds to
    zero width. Every one of its vertices reads as collinear with both of
    its neighbours (cutting.ear_clip's own straight-vertex
    simplification, _COLLINEAR_TOL), so no non-collinear point survives
    to triangulate and ear_clip raises -- the exact shape of failure
    choose_rounds and segment_pieces both have to survive without
    crashing (test_choose_rounds_skips_an_untriangulatable_cell_instead_
    of_crashing above pins the same guard one level earlier, directly
    against choose_rounds).
    """

    p = studio("pieces")
    t = studio("tessellation")
    surface = flat_surface()
    tess = t.build_tessellation(
        [
            {"key": "good", "course": 0,
             "outline": [[1.0, 1.0], [2.0, 1.0], [2.0, 2.0], [1.0, 2.0]],
             "holes": []},
            {"key": "bad", "course": 0,
             "outline": [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [3.0, 0.0]],
             "holes": []},
        ],
        "test", "generated", 1.0, 1,
    )
    made, report = p.segment_pieces(tess, surface, [])
    assert made
    assert report["degenerate_dropped"] == ["bad"]
    assert [piece["key"] for piece in made] == ["good"]
