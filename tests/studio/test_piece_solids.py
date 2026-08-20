"""piece_solids is a verbatim port of the client's own extrusion.

The ground truth is bench/studio/static/studio.js, buildPieceMeshes
(~3709-3790): the seat-plane branch (~3736-3762) flattens every mid point
onto the piece's own plane and offsets both caps along the PLANE normal;
the no-seat branch (~3763-3779) offsets each point along its OWN normal.
Both branches loop `for (const offset of [full, 0])` -- top block first at
offset t, bottom block second at offset 0 -- which is why every fixture
here pins the top block at vertex indices 0..count-1 and the bottom block
at count..2*count-1. Contract decision (this wave): joint_gap and taper
are always 0 for an export, so `full` is exactly the thickness argument,
never state.jointGap's shrink or taperAt's scale (see the design doc,
"DELIBERATE CONTRACT DECISIONS").

Every piece topology below is hand-built the way pieces.py itself builds
piece["faces"] (~801-810): for each cap triangle (a, b, c), a top face
[a, b, c] (unreversed) and a reversed bottom face [c+count, b+count,
a+count]; for each boundary chain, one wall quad per edge,
[v, u, u+count, v+count] with u = chain[i], v = chain[i+1]. The hole
fixture pins the convention the design doc's risk list called out: the
outer chain runs counterclockwise (viewed from +z) and the hole chain
runs CLOCKWISE, so the hole's wall normals point into the hole (outward
from the material) rather than into the material.
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
    import piece_solids

    return piece_solids


# ---------------------------------------------------------------------------
# Fixture: a flat unit square, no seat_plane, the doubled topology built
# exactly the way pieces.py builds it for one cap triangulated as two
# triangles (0, 1, 2) and (0, 2, 3), one boundary chain [0, 1, 2, 3].
# ---------------------------------------------------------------------------

def _flat_square_piece():
    mid = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 1.0, 0.0], [0.0, 1.0, 0.0]]
    normals = [[0.0, 0.0, 1.0]] * 4
    count = 4
    triangles = [(0, 1, 2), (0, 2, 3)]
    chain = [0, 1, 2, 3]
    faces = []
    for a, b, c in triangles:
        faces.append([a, b, c])
        faces.append([c + count, b + count, a + count])
    for i in range(len(chain)):
        u, v = chain[i], chain[(i + 1) % len(chain)]
        faces.append([v, u, u + count, v + count])
    return {
        "key": "c0p0",
        "course": 0,
        "mid": mid,
        "normals": normals,
        "sources": [{}] * 4,
        "faces": faces,
        "is_support": False,
    }


def test_flat_square_without_seat_plane_solidifies_by_per_vertex_normal():
    p = studio()
    piece = _flat_square_piece()
    result = p.solidify(piece, 0.2)

    # No seat_plane: JS's else branch (~3769-3778) --
    #   for (const offset of [full, 0])
    #     for i in 0..count-1: points.push(m[i] + n[i]*offset)
    # Top block (offset = thickness = 0.2) at indices 0..3, unchanged in
    # x/y (normal is [0,0,1]), z lifted by 0.2. Bottom block (offset = 0)
    # at indices 4..7 is mid verbatim.
    assert result["vertices"] == [
        [0.0, 0.0, 0.2],
        [1.0, 0.0, 0.2],
        [1.0, 1.0, 0.2],
        [0.0, 1.0, 0.2],
        [0.0, 0.0, 0.0],
        [1.0, 0.0, 0.0],
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 0.0],
    ]
    # faces are the piece's own topology, reused verbatim (same object: no
    # topology is rebuilt, see the module docstring for why).
    assert result["faces"] is piece["faces"]


def test_flat_square_verifies_closed_with_prism_volume():
    p = studio()
    piece = _flat_square_piece()
    solid = p.solidify(piece, 0.2)
    check = p.verify_solid(solid["vertices"], solid["faces"])
    assert check["closed"] is True
    # A 1x1 unit square extruded 0.2 m: volume = area * thickness = 0.2.
    assert check["volume"] == pytest.approx(0.2, abs=1e-9)


def test_dropping_a_wall_quad_breaks_closure():
    p = studio()
    piece = _flat_square_piece()
    piece["faces"] = piece["faces"][:-1]  # drop the last wall quad
    solid = p.solidify(piece, 0.2)
    check = p.verify_solid(solid["vertices"], solid["faces"])
    assert check["closed"] is False


# ---------------------------------------------------------------------------
# Fixture: the same flat square, but WITH a tilted seat_plane. Expected
# belly/top values are computed independently here, by the same arithmetic
# as JS's K2 branch (~3745-3762), so the assertion is a genuine check
# against the formula rather than the implementation.
# ---------------------------------------------------------------------------

def test_flat_square_with_seat_plane_flattens_onto_the_plane():
    p = studio()
    piece = _flat_square_piece()
    origin = [0.0, 0.0, 0.05]
    raw_normal = [0.1, 0.0, 1.0]
    mag = math.sqrt(sum(c * c for c in raw_normal))
    normal = [c / mag for c in raw_normal]
    piece["seat_plane"] = {"origin": origin, "normal": normal}
    piece["seat_gap"] = 0.0

    t = 0.2
    ox, oy, oz = origin
    nx, ny, nz = normal

    # JS ~3748-3752:
    #   const d = (m[0]-ox)*nx + (m[1]-oy)*ny + (m[2]-oz)*nz;
    #   belly.push([m[0]-d*nx, m[1]-d*ny, m[2]-d*nz]);
    # then ~3753-3762: points = [belly[i] + n*t for i] (top, offset=full)
    # followed by [belly[i] for i] (bottom, offset=0).
    expected_top = []
    expected_bottom = []
    for m in piece["mid"]:
        mx, my, mz = m
        d = (mx - ox) * nx + (my - oy) * ny + (mz - oz) * nz
        bx, by, bz = mx - d * nx, my - d * ny, mz - d * nz
        expected_bottom.append([bx, by, bz])
        expected_top.append([bx + nx * t, by + ny * t, bz + nz * t])

    result = p.solidify(piece, t)
    vertices = result["vertices"]
    for i in range(4):
        assert vertices[i] == pytest.approx(expected_top[i], abs=1e-12)
        assert vertices[4 + i] == pytest.approx(expected_bottom[i], abs=1e-12)

    # Both caps stay flat and parallel: every belly point's distance from
    # the plane is zero, and the top is offset from its own belly point by
    # exactly t along the plane normal (not each point's own surface
    # normal, since the square's own normals are all [0,0,1] != n here).
    for i in range(4):
        top = vertices[i]
        bottom = vertices[4 + i]
        delta = [top[k] - bottom[k] for k in range(3)]
        assert delta == pytest.approx([nx * t, ny * t, nz * t], abs=1e-12)


# ---------------------------------------------------------------------------
# Fixture: an annular square (a piece with a hole). Outer 2x2 square
# (area 4) with a 1x1 hole (area 1) cut from its centre. Two chains: the
# outer boundary counterclockwise (viewed from +z), the hole boundary
# clockwise, matching pieces.py's own convention for a region with a hole
# (material stays to the left of every directed boundary edge) -- the
# hole-wall winding the spec's risk list called out.
# ---------------------------------------------------------------------------

def _annulus_piece():
    outer = [[-1.0, -1.0, 0.0], [1.0, -1.0, 0.0], [1.0, 1.0, 0.0], [-1.0, 1.0, 0.0]]
    # Same four corners as outer, halved, listed BL, TL, TR, BR -- the
    # reverse rotational sense of outer's BL, BR, TR, TL, i.e. clockwise.
    inner = [[-0.5, -0.5, 0.0], [-0.5, 0.5, 0.0], [0.5, 0.5, 0.0], [0.5, -0.5, 0.0]]
    mid = outer + inner
    count = 8
    normals = [[0.0, 0.0, 1.0]] * count

    # match[i] is the inner (global) index spatially matching outer corner
    # i: O0=BL<->I4=BL, O1=BR<->I7=BR, O2=TR<->I6=TR, O3=TL<->I5=TL.
    match = [4, 7, 6, 5]
    triangles = []
    for i in range(4):
        a, b = i, (i + 1) % 4
        ia, ib = match[i], match[(i + 1) % 4]
        # Bridge the trapezoid between outer edge (a, b) and its matching
        # inner edge with two triangles, same cap-triangulation shape
        # pieces.py's own `triangles` list carries.
        triangles.append((a, b, ib))
        triangles.append((a, ib, ia))

    faces = []
    for a, b, c in triangles:
        faces.append([a, b, c])
        faces.append([c + count, b + count, a + count])
    chains = [[0, 1, 2, 3], [4, 5, 6, 7]]
    for chain in chains:
        n = len(chain)
        for i in range(n):
            u, v = chain[i], chain[(i + 1) % n]
            faces.append([v, u, u + count, v + count])

    return {
        "key": "c1p0",
        "course": 1,
        "mid": mid,
        "normals": normals,
        "sources": [{}] * count,
        "faces": faces,
        "is_support": False,
    }


def test_annulus_piece_verifies_closed_with_area_difference_volume():
    p = studio()
    piece = _annulus_piece()
    t = 0.2
    solid = p.solidify(piece, t)
    check = p.verify_solid(solid["vertices"], solid["faces"])
    assert check["closed"] is True
    outer_area = 2.0 * 2.0
    inner_area = 1.0 * 1.0
    assert check["volume"] == pytest.approx((outer_area - inner_area) * t, abs=1e-9)


# ---------------------------------------------------------------------------
# Degenerate guards.
# ---------------------------------------------------------------------------

def test_thickness_is_respected_exactly_not_rounded_or_scaled():
    p = studio()
    piece = _flat_square_piece()
    result = p.solidify(piece, 0.137)
    assert result["vertices"][0] == [0.0, 0.0, 0.137]
    assert result["vertices"][4] == [0.0, 0.0, 0.0]


def test_normals_shorter_than_mid_raises_value_error_naming_the_piece():
    p = studio()
    piece = _flat_square_piece()
    piece["key"] = "c9p9"
    piece["normals"] = piece["normals"][:-1]  # 3 normals, 4 mid points
    with pytest.raises(ValueError, match="c9p9"):
        p.solidify(piece, 0.2)
