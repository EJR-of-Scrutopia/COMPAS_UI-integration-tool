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
