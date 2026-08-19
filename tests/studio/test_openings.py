"""openings.py extracts every boundary loop of a mesh and classifies them.

extract_loops generalises domain.boundary_ring's walk to every connected
boundary component instead of refusing when more than one closes.
classify then picks the outer rim (the loop whose plan polygon contains
every other loop's vertices) and validates the rest as interior openings.

Same grid fixture idiom as tests/studio/test_domain.py:27-60, miniaturised:
an N by N grid of unit quads at z = 0, with named (row, col) faces droppable
to punch interior holes.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def studio():
    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import openings
    return openings


def domain_module():
    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import domain
    return domain


def grid(side, drop=()):
    """side by side unit quads, with the listed (i, j) faces left out."""

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
            faces.append(face)
    centroids = [
        [sum(vertices[k][axis] for k in face) / 4.0 for axis in range(3)]
        for face in faces
    ]
    return vertices, faces, centroids


def test_a_single_loop_mesh_yields_one_loop():
    o = studio()
    d = domain_module()
    vertices, faces, _ = grid(3)
    loops = o.extract_loops(faces)
    assert len(loops) == 1
    assert set(loops[0]) == set(d.boundary_ring(faces))


def test_an_interior_hole_yields_two_loops():
    o = studio()
    vertices, faces, _ = grid(5, drop=((2, 2),))
    loops = o.extract_loops(faces)
    assert len(loops) == 2
    # the outer rim starts at vertex 0 (the mesh's own minimum vertex id);
    # the hole punched by dropping face (2, 2) is the 4-vertex ring around
    # vertices 14, 15, 20, 21, whose own minimum is 14.
    assert loops[0][0] == 0
    assert len(loops[0]) == 20
    assert loops[1][0] == 14
    assert len(loops[1]) == 4
    assert set(loops[1]) == {14, 15, 20, 21}
    # ordering is by minimum vertex id: the interior hole sorts second.
    assert loops[0][0] < loops[1][0]
    # the walk direction is part of the contract: from the loop's minimum
    # vertex, the SMALLER-id neighbour comes first. Vertex 14's ring
    # neighbours are 15 and 20, so the full sequence is pinned, not just
    # the membership; likewise the outer rim leaves vertex 0 toward 1,
    # not 6. A walk toward the larger neighbour would reverse both.
    assert loops[1] == [14, 15, 21, 20]
    assert loops[0][:2] == [0, 1]


def test_two_holes_yield_three_loops_deterministically():
    o = studio()
    vertices, faces, _ = grid(7, drop=((2, 2), (4, 4)))
    loops = o.extract_loops(faces)
    assert len(loops) == 3
    mins = [ring[0] for ring in loops]
    assert mins == sorted(mins)
    # stable across repeated calls on the same input
    assert o.extract_loops(faces) == loops


def test_branch_vertex_still_refuses_verbatim():
    o = studio()
    # Two quads sharing exactly one vertex (id 2): every edge of both quads
    # is singly used, so vertex 2 has four boundary neighbours, not two.
    faces = [[0, 1, 2, 3], [2, 4, 5, 6]]
    try:
        o.extract_loops(faces)
        assert False, "expected a ValueError"
    except ValueError as error:
        assert str(error) == (
            "boundary vertex 2 has 4 boundary neighbours, not 2; the "
            "rim branches here"
        )


def test_extract_loops_refuses_a_meshless_boundary():
    o = studio()
    try:
        o.extract_loops([])
        assert False, "expected a ValueError"
    except ValueError as error:
        assert str(error) == "this mesh has no boundary, so it has no rim to fit"


def test_classify_picks_the_containing_loop():
    o = studio()
    vertices, faces, _ = grid(5, drop=((2, 2),))
    loops = o.extract_loops(faces)
    outer, holes = o.classify(loops, vertices)
    assert outer == loops[0]
    assert len(outer) == 20
    assert holes == [loops[1]]
    assert len(holes[0]) == 4


def test_classify_refuses_when_no_loop_contains_the_others():
    o = studio()
    # Two disjoint unit squares: neither loop's plan polygon contains the
    # other's vertices.
    vertices = [
        [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0],
        [5.0, 5.0, 0.0], [6.0, 5.0, 0.0], [6.0, 6.0, 0.0], [5.0, 6.0, 0.0],
    ]
    faces = [[0, 1, 2, 3], [4, 5, 6, 7]]
    loops = o.extract_loops(faces)
    try:
        o.classify(loops, vertices)
        assert False, "expected a ValueError"
    except ValueError as error:
        assert str(error) == (
            "the plan has 2 boundary loops but no single loop contains "
            "the others; this surface has no outer rim to course from."
        )


def test_classify_refuses_a_self_crossing_opening():
    o = studio()
    # A large outer square containing a hand-built hole ring whose plan
    # projection is a bowtie: edges (4, 5) and (6, 7) cross at (3, 3).
    vertices = [
        [0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 10.0, 0.0], [0.0, 10.0, 0.0],
        [2.0, 2.0, 0.0], [4.0, 4.0, 0.0], [4.0, 2.0, 0.0], [2.0, 4.0, 0.0],
    ]
    outer = [0, 1, 2, 3]
    bowtie = [4, 5, 6, 7]
    loops = [outer, bowtie]
    try:
        o.classify(loops, vertices)
        assert False, "expected a ValueError"
    except ValueError as error:
        assert str(error) == (
            "an opening's boundary crosses itself in plan near (2.00, "
            "2.00); this opening cannot be trimmed to."
        )


def _area(ring):
    """Shoelace area of a plan ring, written locally per the task brief
    (three lines, no import needed) rather than pulled from tessellation.
    """

    total = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        total += x1 * y2 - x2 * y1
    return abs(total) / 2.0


def _has_point(ring, x, y, tol=1e-9):
    return any(abs(p[0] - x) < tol and abs(p[1] - y) < tol for p in ring)


def _point_set(ring, tol=9):
    return {(round(p[0], tol), round(p[1], tol)) for p in ring}


def _square(x0, y0, x1, y1):
    """A CCW unit-orientation square/rectangle outline, corners as floats."""

    return [[float(x0), float(y0)], [float(x1), float(y0)],
            [float(x1), float(y1)], [float(x0), float(y1)]]


def test_no_overlap_leaves_the_cell_untouched():
    o = studio()
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = _square(10, 10, 12, 12)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert cells == [cell]
    assert report == {
        "openings": 1,
        "cells_in_openings": 0,
        "cells_clipped": [],
        "opening_slivers": [],
        "opening_clip_failures": [],
    }


def test_a_bite_trims_onto_the_hole_boundary():
    o = studio()
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = _square(3, 1, 5, 3)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert len(cells) == 1
    result = cells[0]
    assert result["key"] == "c0p0"
    assert result["course"] == 0
    outline = result["outline"]
    # the trimmed edge runs along the hole's true boundary, so its corners
    # (3, 1) and (3, 3) are on the surviving outline.
    assert _has_point(outline, 3.0, 1.0)
    assert _has_point(outline, 3.0, 3.0)
    assert abs(_area(outline) - (16.0 - 2.0)) < 1e-9
    assert result["holes"] == []
    assert report["cells_clipped"] == ["c0p0"]
    assert report["cells_in_openings"] == 0
    assert report["opening_slivers"] == []
    assert report["opening_clip_failures"] == []


def test_a_crossing_hole_splits_into_two_components():
    o = studio()
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = _square(-1, 1.5, 5, 2.5)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert len(cells) == 2
    keys = sorted(c["key"] for c in cells)
    assert keys == ["c0p0", "c0p0b"]
    for c in cells:
        assert c["course"] == 0
        assert c["holes"] == []
        # both halves are exactly 4 wide by 1.5 tall: the strip is a tie.
        assert abs(_area(c["outline"]) - 6.0) < 1e-9
    # Controller ruling (task-2, ambiguity ledger): when split components
    # tie exactly on area, the base key goes to whichever ring the
    # stitcher closes first, not to a spatial convention (e.g. "topmost").
    # For this fixture the stitcher walks the subject's own edges before
    # the hole's reversed edges, and the subject ring beginning at its
    # first vertex (0, 0) walks into the BOTTOM strip first, so "c0p0" is
    # the bottom rectangle (y in [0, 1.5]) and "c0p0b" is the top one (y
    # in [2.5, 4]). Pinned here rather than left to sort-key luck.
    by_key = {c["key"]: c["outline"] for c in cells}
    assert max(p[1] for p in by_key["c0p0"]) <= 1.5 + 1e-9
    assert min(p[1] for p in by_key["c0p0b"]) >= 2.5 - 1e-9
    assert report["cells_clipped"] == ["c0p0"]
    assert report["cells_in_openings"] == 0
    assert report["opening_slivers"] == []
    assert report["opening_clip_failures"] == []


def test_a_swallowed_hole_becomes_an_interior_ring():
    o = studio()
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = _square(1, 1, 3, 3)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert len(cells) == 1
    result = cells[0]
    assert result["key"] == "c0p0"
    assert result["outline"] == cell["outline"]
    assert len(result["holes"]) == 1
    hole_ring = result["holes"][0]
    # same square, reversed winding; point-set match rather than pinning
    # the stitcher's arbitrary rotation/start-vertex of the ring.
    assert _point_set(hole_ring) == _point_set(hole)
    assert abs(_area(result["outline"]) - _area(hole_ring) - 12.0) < 1e-9
    assert report["cells_clipped"] == ["c0p0"]
    assert report["cells_in_openings"] == 0
    assert report["opening_slivers"] == []
    assert report["opening_clip_failures"] == []


def test_a_cell_inside_the_hole_is_dropped():
    o = studio()
    cell = {"key": "c0p0", "course": 0, "outline": _square(1, 1, 2, 2), "holes": []}
    hole = _square(0, 0, 4, 4)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert cells == []
    assert report["cells_in_openings"] == 1
    assert report["cells_clipped"] == []
    assert report["opening_slivers"] == []
    assert report["opening_clip_failures"] == []


def test_a_sliver_component_is_dropped_and_named():
    o = studio()
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = _square(-1, -1, 3.999, 5)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert cells == []
    assert report["opening_slivers"] == ["c0p0"]
    assert report["cells_clipped"] == []
    assert report["cells_in_openings"] == 0
    assert report["opening_clip_failures"] == []


def test_a_collinear_tangency_is_dropped_and_named():
    o = studio()
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = _square(4, 1, 6, 3)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert cells == []
    assert report["opening_clip_failures"] == ["c0p0"]
    assert report["cells_clipped"] == []
    assert report["cells_in_openings"] == 0
    assert report["opening_slivers"] == []


def test_two_holes_apply_sequentially():
    o = studio()
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 8, 4), "holes": []}
    swallowed = _square(1, 1, 3, 3)
    biting = _square(7, -1, 9, 5)
    cells, report = o.clip_cells([cell], [swallowed, biting], 1.0)
    assert len(cells) == 1
    result = cells[0]
    assert result["key"] == "c0p0"
    outline = result["outline"]
    # trimmed onto the true right-hand boundary at x = 7
    assert max(p[0] for p in outline) <= 7.0 + 1e-9
    assert _has_point(outline, 7.0, 0.0)
    assert _has_point(outline, 7.0, 4.0)
    # the swallowed opening survives as an interior ring
    assert len(result["holes"]) == 1
    assert _point_set(result["holes"][0]) == _point_set(swallowed)
    region_area = _area(outline) - _area(result["holes"][0])
    assert abs(region_area - 24.0) < 1e-9
    assert report["openings"] == 2
    assert report["cells_clipped"] == ["c0p0"]
    assert report["cells_in_openings"] == 0
    assert report["opening_slivers"] == []
    assert report["opening_clip_failures"] == []


# --- Fix round 1: review findings C1 (winding), C2 (duplicate keys),
# I1 (sliver threshold rebasing), I2 (unpinned outcomes) ----------------


def test_a_bite_with_a_reversed_hole_matches_the_canonical_result():
    o = studio()
    # C1: the review measured 24/400 cells and 1.93 m2 lost on a real-scale
    # oculus probe whenever the hole ring's winding opposed the cell's.
    # Same bite fixture as test_a_bite_trims_onto_the_hole_boundary, hole
    # ring wound the other way: the trimmed result must be identical (up
    # to starting point -- clip_cells does not promise to preserve which
    # vertex a rebuilt ring starts at).
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = list(reversed(_square(3, 1, 5, 3)))
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert len(cells) == 1
    result = cells[0]
    assert result["key"] == "c0p0"
    assert result["course"] == 0
    outline = result["outline"]
    assert _has_point(outline, 3.0, 1.0)
    assert _has_point(outline, 3.0, 3.0)
    assert abs(_area(outline) - 14.0) < 1e-9
    assert result["holes"] == []
    assert report["cells_clipped"] == ["c0p0"]
    assert report["opening_clip_failures"] == []


def test_a_bite_with_a_reversed_subject_matches_the_canonical_result():
    o = studio()
    # C1, mirror case: the CELL outline wound the other way instead of the
    # hole. Same expected result as the canonical bite.
    cell = {
        "key": "c0p0", "course": 0,
        "outline": list(reversed(_square(0, 0, 4, 4))), "holes": [],
    }
    hole = _square(3, 1, 5, 3)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert len(cells) == 1
    result = cells[0]
    assert result["key"] == "c0p0"
    outline = result["outline"]
    assert _has_point(outline, 3.0, 1.0)
    assert _has_point(outline, 3.0, 3.0)
    assert abs(_area(outline) - 14.0) < 1e-9
    assert result["holes"] == []
    assert report["cells_clipped"] == ["c0p0"]
    assert report["opening_clip_failures"] == []


def test_two_holes_splitting_the_same_lineage_produce_unique_keys():
    o = studio()
    # C2: hole A splits the cell into a bottom and top strip; hole B then
    # splits the bottom strip again. The old per-hole suffixing restarted
    # its alphabet each pass and produced ['c0p0', 'c0p0b', 'c0p0b'] --
    # two different surviving pieces sharing one identifier. Verified by
    # hand against the fixed implementation: the untouched top strip
    # (area 12) keeps the base key, the two bottom pieces (area 6 and
    # 4.5) take "b" and "c" in area-descending order.
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 8, 4), "holes": []}
    hole_a = _square(-1, 1.5, 9, 2.5)
    hole_b = _square(3, -1, 4, 1.7)
    cells, report = o.clip_cells([cell], [hole_a, hole_b], 1.0)
    assert len(cells) == 3
    keys = [c["key"] for c in cells]
    assert keys == ["c0p0", "c0p0b", "c0p0c"]
    assert len(set(keys)) == 3, "keys must be unique across the whole lineage"
    areas = {c["key"]: _area(c["outline"]) for c in cells}
    assert abs(areas["c0p0"] - 12.0) < 1e-9
    assert abs(areas["c0p0b"] - 6.0) < 1e-9
    assert abs(areas["c0p0c"] - 4.5) < 1e-9
    assert abs(sum(areas.values()) - 22.5) < 1e-9
    for c in cells:
        assert c["course"] == 0
        assert c["holes"] == []
    assert report["cells_clipped"] == ["c0p0"]
    assert report["opening_clip_failures"] == []


def test_sliver_threshold_uses_the_original_area_not_the_intermediate_one():
    o = studio()
    # I1: hole 1 leaves a 0.1 x 4 strip (area 0.4, 2.5% of the original 16,
    # kept); hole 2 then trims that strip down to a 0.0025 x 4 sliver
    # (area 0.01). 0.01 is 2.5% of the INTERMEDIATE area (0.4) -- above
    # 0.5% and, under the old per-hole rebasing, wrongly kept -- but only
    # 0.0625% of the ORIGINAL area (16), an order of magnitude under the
    # 0.5% bar. The spec's rule is against "the unclipped cell's area",
    # meaning the raw generator cell, not whatever survived earlier holes.
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole1 = _square(0.1, -1, 5, 5)
    hole2 = _square(-1, -1, 0.0975, 5)
    cells, report = o.clip_cells([cell], [hole1, hole2], 1.0)
    assert cells == []
    assert report["opening_slivers"] == ["c0p0"]
    # touched by hole 1 but nothing survives to the end: not "clipped".
    assert report["cells_clipped"] == []
    assert report["cells_in_openings"] == 0
    assert report["opening_clip_failures"] == []


def test_a_corner_bite_trims_through_a_shared_vertex_region():
    o = studio()
    # I2: a hole overlapping only a CORNER of the cell (the cell has no
    # vertex inside the hole and vice versa, but the hole's own corner
    # sits inside the cell). Verified by hand: (0,0)-(4,4) minus
    # (3,3)-(5,5) leaves an L-shaped hexagon, area 15.
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = _square(3, 3, 5, 5)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert len(cells) == 1
    result = cells[0]
    assert result["key"] == "c0p0"
    outline = result["outline"]
    assert _has_point(outline, 4.0, 3.0)
    assert _has_point(outline, 3.0, 3.0)
    assert _has_point(outline, 3.0, 4.0)
    assert abs(_area(outline) - 15.0) < 1e-9
    assert report["cells_clipped"] == ["c0p0"]
    assert report["opening_clip_failures"] == []


def test_a_hole_crossing_one_edge_twice_leaves_a_u_shaped_remainder():
    o = studio()
    # I2: a hole that dips into the cell from outside and crosses the SAME
    # cell edge twice (rather than splitting the cell into separate
    # components) must still stitch into one ring with a notch cut into
    # it. Verified by hand: (0,0)-(4,4) minus (1,3)-(3,5) leaves a
    # U-shaped octagon, area 14.
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 4, 4), "holes": []}
    hole = _square(1, 3, 3, 5)
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert len(cells) == 1
    result = cells[0]
    assert result["key"] == "c0p0"
    outline = result["outline"]
    # the notch's true corners are on the surviving boundary
    assert _has_point(outline, 3.0, 4.0)
    assert _has_point(outline, 3.0, 3.0)
    assert _has_point(outline, 1.0, 3.0)
    assert _has_point(outline, 1.0, 4.0)
    assert abs(_area(outline) - 14.0) < 1e-9
    assert report["cells_clipped"] == ["c0p0"]
    assert report["opening_clip_failures"] == []


def test_bbox_overlap_but_geometrically_disjoint_leaves_the_cell_untouched():
    o = studio()
    # I2: the bbox pre-test is a cheap necessary-not-sufficient filter.
    # These two triangles' bounding boxes overlap (cell (0,0)-(4,4), hole
    # (3,3)-(4.5,4.5)) but the triangles themselves never touch. Verified
    # by hand: the cell survives untouched, area 8.
    cell = {
        "key": "c0p0", "course": 0,
        "outline": [[0.0, 0.0], [4.0, 0.0], [0.0, 4.0]], "holes": [],
    }
    hole = [[4.0, 4.0], [4.5, 3.0], [3.0, 4.5]]
    cells, report = o.clip_cells([cell], [hole], 1.0)
    assert cells == [cell]
    assert abs(_area(cell["outline"]) - 8.0) < 1e-9
    assert report == {
        "openings": 1,
        "cells_in_openings": 0,
        "cells_clipped": [],
        "opening_slivers": [],
        "opening_clip_failures": [],
    }


def test_an_existing_hole_lands_on_the_component_that_contains_it():
    o = studio()
    # I2: _attach_existing_holes was only exercised by the
    # swallowed-then-bite sequence, never by a hole that SPLITS the cell.
    # hole1 swallows a small ring fully inside what will become the
    # bottom half; hole2 then splits the cell in two. The ring must land
    # only on the bottom component, and the top component must stay
    # hole-free rather than getting a copy or losing it.
    cell = {"key": "c0p0", "course": 0, "outline": _square(0, 0, 8, 4), "holes": []}
    swallowed = _square(1, 0.2, 2, 0.8)
    splitting = _square(-1, 1.5, 9, 2.5)
    cells, report = o.clip_cells([cell], [swallowed, splitting], 1.0)
    assert len(cells) == 2
    with_hole = [c for c in cells if c["holes"]]
    without_hole = [c for c in cells if not c["holes"]]
    assert len(with_hole) == 1
    assert len(without_hole) == 1
    assert len(with_hole[0]["holes"]) == 1
    assert _point_set(with_hole[0]["holes"][0]) == _point_set(swallowed)
    # the ring-bearing component is the bottom strip: every point at or
    # below y = 1.5.
    assert max(p[1] for p in with_hole[0]["outline"]) <= 1.5 + 1e-9
    assert min(p[1] for p in without_hole[0]["outline"]) >= 2.5 - 1e-9
    keys = sorted(c["key"] for c in cells)
    assert keys == ["c0p0", "c0p0b"]
    assert len(set(c["key"] for c in cells)) == 2
    assert report["cells_clipped"] == ["c0p0"]
    assert report["opening_clip_failures"] == []


def test_classify_refuses_overlapping_loops():
    o = studio()
    # An outer square containing two 2x2 holes that overlap each other in
    # the region (2, 2) to (3, 3): both are individually contained by the
    # outer rim (so an outer loop is found), but they overlap one another.
    vertices = [
        [0.0, 0.0, 0.0], [10.0, 0.0, 0.0], [10.0, 10.0, 0.0], [0.0, 10.0, 0.0],
        [1.0, 1.0, 0.0], [3.0, 1.0, 0.0], [3.0, 3.0, 0.0], [1.0, 3.0, 0.0],
        [2.0, 2.0, 0.0], [4.0, 2.0, 0.0], [4.0, 4.0, 0.0], [2.0, 4.0, 0.0],
    ]
    outer = [0, 1, 2, 3]
    hole_a = [4, 5, 6, 7]
    hole_b = [8, 9, 10, 11]
    loops = [outer, hole_a, hole_b]
    try:
        o.classify(loops, vertices)
        assert False, "expected a ValueError"
    except ValueError as error:
        assert str(error) == (
            "boundary loops overlap in plan near (3.00, 1.00); an "
            "overhanging surface has no single-height plan to cut."
        )
