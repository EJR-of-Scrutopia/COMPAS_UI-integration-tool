"""The client's own extrusion, run server side, and proven watertight.

The studio viewer (bench/studio/static/studio.js, buildPieceMeshes,
~3709-3790) turns every intrados-only piece record from pieces.py into a
displayed solid at draw time: it never ships a solid, it draws one. The
pieces export needs that same solid on disk, so this module is a verbatim
transcription of the two branches that build it (~3736-3779), not a
reinterpretation:

- Jointed piece WITH a seat_plane (origin o, unit normal n) -- JS
  ~3745-3762. Every cap point m is flattened onto the plane first:
  d = (m-o).n, belly = m - d*n. Both caps are built from that SAME belly,
  offset along the PLANE's normal, not each point's own surface normal,
  so the block stays a true prism with two parallel flat faces:
      for (const offset of [full, 0])
        for i in 0..count-1: points.push(belly[i] + n*offset)
- Piece WITHOUT a seat_plane -- JS ~3769-3778. Each point keeps its own
  surface normal, so the curvature survives the extrusion:
      for (const offset of [full, 0])
        for i in 0..count-1: points.push(m[i] + normals[i]*offset)

Both branches loop offset over [full, 0]: the FIRST count points are the
top block (offset = thickness) and the SECOND count are the bottom block
(offset = 0), which is why solidify's output vertex array is exactly
2*count long with that split. `full` in the client is
provenance.thickness scaled by a per-course taper and shrunk further by
half the live joint gap (state.jointGap); this wave's contract fixes
joint_gap = 0.0 and taper = 0.0 for every export always (see
docs/superpowers/specs/2026-08-20-pieces-export-design.md, "DELIBERATE
CONTRACT DECISIONS") -- true touching blocks at fabrication size, not the
viewer's cosmetic render -- so `full` here is simply the thickness
argument, unmodified.

faces are the piece's own topology (pieces.py ~801-810: top cap
triangles unreversed, bottom cap triangles reversed, one wall quad per
boundary-chain edge, holes included) REUSED VERBATIM. No topology is
rebuilt anywhere in this module; solidify returns the SAME list object
piece["faces"] points at (not a copy), because the export route only
ever reads it to serialise JSON and never mutates it, and an 840-piece
Armadillo export has no reason to duplicate that many face lists for no
behavioural difference.

verify_solid is the integrity check the design doc calls for: a mesh is
watertight when every undirected edge of its fan-triangulated faces
(quads split as two triangles) is used by exactly two triangles, in
opposite directions -- and its signed volume, by the divergence theorem
(sum of v0 . (v1 x v2) / 6 over every triangle), is positive only when
every face's winding points outward. Both properties are pinned by
tests/studio/test_piece_solids.py, including the case pieces.py's own
hole convention depends on: a hole's boundary chain runs the OPPOSITE
rotational sense from the outer boundary, so its wall's outward normal
points into the hole rather than into the material.

Stdlib only: bench/studio never imports a solver stack (see
tests/studio/test_studio_guard.py).
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple


def solidify(piece: Mapping[str, Any], thickness: float) -> Dict[str, Any]:
    """Extrude one piece record to its final solid, per the client's own
    algorithm (see the module docstring for the JS line references).

    Returns {"vertices": [[x, y, z] * 2*count], "faces": piece["faces"]}:
    the top block first at indices 0..count-1 (offset = thickness), the
    bottom block second at count..2*count-1 (offset = 0), matching the
    client's `for (const offset of [full, 0])` loop order exactly.
    """

    key = piece.get("key", "?")
    mid: Sequence[Sequence[float]] = piece["mid"]
    count = len(mid)
    normals: Sequence[Sequence[float]] = piece.get("normals") or []
    if len(normals) < count:
        raise ValueError(
            "piece {}: normals shorter than mid ({} < {})".format(
                key, len(normals), count
            )
        )

    seat_plane = piece.get("seat_plane")
    vertices: List[List[float]] = []

    if seat_plane:
        # JS ~3745-3752 (K2): the belly is every mid point flattened onto
        # the piece's own seat plane.
        ox, oy, oz = seat_plane["origin"]
        nx, ny, nz = seat_plane["normal"]
        belly: List[Tuple[float, float, float]] = []
        for mx, my, mz in mid:
            d = (mx - ox) * nx + (my - oy) * ny + (mz - oz) * nz
            belly.append((mx - d * nx, my - d * ny, mz - d * nz))
        # JS ~3753-3762: both caps offset from the SAME belly, along the
        # plane normal -- top first (offset = thickness), bottom second
        # (offset = 0).
        for offset in (thickness, 0.0):
            for bx, by, bz in belly:
                vertices.append([bx + nx * offset, by + ny * offset, bz + nz * offset])
    else:
        # JS ~3769-3778: no seat plane, so each point keeps its own
        # surface normal -- top first (offset = thickness), bottom second
        # (offset = 0).
        for offset in (thickness, 0.0):
            for i in range(count):
                mx, my, mz = mid[i]
                nx, ny, nz = normals[i]
                vertices.append([mx + nx * offset, my + ny * offset, mz + nz * offset])

    return {"vertices": vertices, "faces": piece["faces"]}


def verify_solid(
    vertices: Sequence[Sequence[float]], faces: Sequence[Sequence[int]]
) -> Dict[str, Any]:
    """closed: every undirected edge of the fan-triangulated faces is used
    by exactly two triangles, in opposite directions. volume: the signed
    volume by the divergence theorem, positive for a correctly wound
    (outward-facing) solid.
    """

    edge_count: Dict[Tuple[int, int], int] = {}
    volume = 0.0
    for face in faces:
        for corner in range(1, len(face) - 1):
            a, b, c = face[0], face[corner], face[corner + 1]
            for u, v in ((a, b), (b, c), (c, a)):
                edge_count[(u, v)] = edge_count.get((u, v), 0) + 1
            v0 = vertices[a]
            v1 = vertices[b]
            v2 = vertices[c]
            cx = v1[1] * v2[2] - v1[2] * v2[1]
            cy = v1[2] * v2[0] - v1[0] * v2[2]
            cz = v1[0] * v2[1] - v1[1] * v2[0]
            volume += (v0[0] * cx + v0[1] * cy + v0[2] * cz) / 6.0

    closed = True
    for (u, v), n in edge_count.items():
        if n != 1 or edge_count.get((v, u), 0) != 1:
            closed = False
            break

    return {"closed": closed, "volume": volume}
