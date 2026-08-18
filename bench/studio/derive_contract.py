"""Derive a minimal, honest contract from a compas-only export (P4).

Param's ask: uploading just the *-compas.json half (the mesh geometry a
Grasshopper "form export" ships) should be enough to see the vault in the
studio, without also authoring the *-contract.json half (equilibrium,
supports, forces) by hand. This module derives the SMALLEST contract
geometry.py's own parsers (mesh_arrays / support_ids / member_forces_newtons
/ node_loads_newtons / support_reactions_newtons) accept, from nothing but
the compas mesh's own vertices and faces:

- equilibrium.vertices / formGraph.faces: read straight off the compas
  Mesh's vertex/face dicts (see _mesh_vertices_and_faces).
- equilibrium.resolvedSupportNodeIds: INFERRED, not measured -- see
  infer_support_ids for the exact rule and its tolerance. No contract
  carries support flags for a compas-only export, so this is the honest
  geometric stand-in a bare mesh actually supports.
- equilibrium.edges / memberForces / loads / reactions: empty, in the
  shapes geometry.py's own parsers already treat as "no data" (never
  raise on an empty list -- see member_forces_newtons's own docstring).
- A top-level "provenance.derived" marker names the whole document as
  geometry only, so nothing downstream -- the Data panel, a future
  reader of this file -- can mistake it for a real analysis export.

Pure: no filesystem, no upload naming (app.py decides the "-contract.json"
filename and whether an existing file blocks the write). stdlib only, like
geometry.py, so the "studio never imports a solver stack" guard
(test_studio_guard.py) never has to know this module exists.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, Union

# The exact rule (P4 brief: "state the exact rule and tolerance"): a vertex
# counts as a support when BOTH hold --
#   1. it sits on the mesh's own boundary (an edge used by exactly one
#      face -- the same singly-used-edge rule domain.boundary_ring uses),
#   2. its z is within this tolerance of the WHOLE MESH's own z-minimum
#      (not just the boundary's), since the ground a vault actually rests
#      on is wherever its lowest point sits, and a bare mesh with no
#      "is this a foot" flag has no other reference for it.
# 1 mm in the metre-scaled meshes this studio works in already: real vault
# feet in the shipped demo exports land within a few micrometres of each
# other at zero, not merely close.
SUPPORT_Z_TOLERANCE = 1e-3

# Embedded verbatim in the derived document's provenance.derived field, so
# a reader (the Data panel, a human opening the file) sees the same words
# app.py's own response and studio.js's own import-time note use.
#
# Review sweep (2026-08-18): the supports clause is load-bearing honesty.
# infer_support_ids GUESSES the grounded set (boundary vertices within
# 1 mm of the mesh z-minimum), and a staged CRA run rests its whole
# stands/collapses verdict on that guess -- a vault whose feet sit at
# more than one level silently loses the higher ones. The marker says so
# wherever it is shown rather than implying only the forces are absent.
DERIVED_MARKER = (
    "geometry only, from compas thrustMesh; no analysis in this export, "
    "and supports are INFERRED (boundary vertices within 1 mm of the "
    "lowest point) -- a staged verdict rests on that guess")


def _parse_thrust_mesh(thrust_mesh: Union[str, Mapping[str, Any]]) -> Mapping[str, Any]:
    """thrustMesh ships as a JSON-encoded STRING (a compas datastructure's
    own to_json/to_data round trip double-encodes it), but this tolerates an
    already-parsed mapping too -- defensive against a caller, or a future
    export format, that skips the double encoding."""

    if isinstance(thrust_mesh, str):
        try:
            thrust_mesh = json.loads(thrust_mesh)
        except json.JSONDecodeError as error:
            raise ValueError("thrustMesh is a string but not valid JSON: {}".format(error))
    if not isinstance(thrust_mesh, Mapping):
        raise ValueError(
            "thrustMesh is neither a JSON-encoded string nor an object "
            "(got {})".format(type(thrust_mesh).__name__)
        )
    return thrust_mesh


def _mesh_vertices_and_faces(thrust_mesh: Mapping[str, Any]):
    """The compas Mesh datastructure's own data.vertex / data.face dicts,
    ordered into plain lists. Both are keyed by STRING integer ids ("0",
    "1", ...); sorted numerically, not lexicographically, or vertex "10"
    would sort before vertex "2" and every face's vertex indices -- which
    reference those same ids directly -- would silently point at the
    wrong row."""

    data = thrust_mesh.get("data")
    if not isinstance(data, Mapping):
        raise ValueError(
            "thrustMesh has no 'data' block; is this a compas Mesh export?"
        )
    vertex = data.get("vertex")
    face = data.get("face")
    if not isinstance(vertex, Mapping) or not vertex:
        raise ValueError("thrustMesh.data.vertex is missing or empty")
    if not isinstance(face, Mapping) or not face:
        raise ValueError("thrustMesh.data.face is missing or empty")

    vertex_ids = sorted(int(k) for k in vertex.keys())
    if vertex_ids != list(range(len(vertex_ids))):
        raise ValueError(
            "thrustMesh vertex keys are not a contiguous 0..N-1 range "
            "({} keys, {}..{}); formGraph.faces indexes directly into "
            "equilibrium.vertices (geometry.py's own contract), and a gap "
            "would silently point every face at the wrong vertex".format(
                len(vertex_ids), vertex_ids[0] if vertex_ids else "?",
                vertex_ids[-1] if vertex_ids else "?",
            )
        )
    vertices: List[Dict[str, float]] = []
    for i in vertex_ids:
        row = vertex[str(i)]
        if not isinstance(row, Mapping) or not all(k in row for k in ("x", "y", "z")):
            raise ValueError("thrustMesh vertex {} is missing x/y/z".format(i))
        vertices.append({
            "x": float(row["x"]), "y": float(row["y"]), "z": float(row["z"]),
        })

    face_ids = sorted(int(k) for k in face.keys())
    faces: List[List[int]] = []
    for i in face_ids:
        row = face[str(i)]
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            raise ValueError(
                "thrustMesh face {} is not a vertex-index list of at "
                "least 3".format(i)
            )
        indices = [int(v) for v in row]
        for index in indices:
            if not (0 <= index < len(vertices)):
                raise ValueError(
                    "thrustMesh face {} references vertex {}, outside "
                    "0..{}".format(i, index, len(vertices) - 1)
                )
        faces.append(indices)
    if not faces:
        raise ValueError("thrustMesh has no faces to build a surface from")
    return vertices, faces


def _boundary_vertex_ids(faces: List[List[int]]) -> set:
    """Vertex ids touching an edge used by exactly one face: the mesh's own
    rim(s). Mirrors domain.boundary_ring's own singly-used-edge rule
    (duplicated rather than imported: this module has no other reason to
    depend on domain.py, and the rule is three lines)."""

    users: Dict[tuple, int] = {}
    for face in faces:
        count = len(face)
        for i in range(count):
            a, b = face[i], face[(i + 1) % count]
            key = (a, b) if a < b else (b, a)
            users[key] = users.get(key, 0) + 1
    boundary_ids = set()
    for (a, b), count in users.items():
        if count == 1:
            boundary_ids.add(a)
            boundary_ids.add(b)
    return boundary_ids


def infer_support_ids(
    vertices: List[Mapping[str, float]],
    faces: List[List[int]],
    tolerance: float = SUPPORT_Z_TOLERANCE,
) -> List[int]:
    """Boundary vertices within `tolerance` of the whole mesh's z-minimum --
    see this module's own docstring and SUPPORT_Z_TOLERANCE for the exact
    rule and why. Sorted, so the result (and any diagnostic that counts it)
    is deterministic run to run."""

    if not vertices or not faces:
        return []
    boundary_ids = _boundary_vertex_ids(faces)
    if not boundary_ids:
        return []
    z_min = min(v["z"] for v in vertices)
    return sorted(
        i for i in boundary_ids if abs(vertices[i]["z"] - z_min) <= tolerance
    )


def derive_contract(
    compas_document: Mapping[str, Any],
    tolerance: float = SUPPORT_Z_TOLERANCE,
) -> Dict[str, Any]:
    """The minimal contract geometry.py's own parsers accept, built from
    nothing but a compas-only export's thrustMesh. Raises ValueError, never
    silently, when the mesh cannot be read at all -- the same contract
    app.py's existing contract-upload validation already keeps (a message a
    caller can act on, not a generic failure)."""

    thrust_mesh_raw = compas_document.get("thrustMesh") if isinstance(compas_document, Mapping) else None
    if thrust_mesh_raw is None:
        raise ValueError(
            "this export has no thrustMesh; is it a compas export at all?"
        )
    thrust_mesh = _parse_thrust_mesh(thrust_mesh_raw)
    vertices, faces = _mesh_vertices_and_faces(thrust_mesh)
    supports = infer_support_ids(vertices, faces, tolerance)

    return {
        "equilibrium": {
            "vertices": vertices,
            "edges": [],
            "resolvedSupportNodeIds": supports,
            "memberForces": [],
            "loads": [],
            "reactions": [],
        },
        "formGraph": {
            "faces": [{"vertices": face} for face in faces],
        },
        "provenance": {
            "derived": DERIVED_MARKER,
            "source": "thrustMesh",
            "support_tolerance_m": tolerance,
            "support_count": len(supports),
            "vertex_count": len(vertices),
            "face_count": len(faces),
        },
    }
