"""P4 (presentation batch, 2026-08-18): derive_contract.derive_contract,
the pure function behind "one file is enough". Fixture is a tiny
synthetic compas mesh (tests/studio/fixtures/tiny-pyramid-compas.json,
5 vertices/4 faces), never the real 0.57 MB Armadillo export -- that one
is verified live (a probe run against a real server) and its numbers are
reported in outcome.md, not re-embedded here as a slow, opaque fixture.

The fixture: a square base (vertices 0-3, all z=0) and an apex (vertex 4,
z=1), four triangular faces, no bottom face -- an open pyramid. Every base
edge is used by exactly one face (the open bottom), so the four base
vertices are the mesh's whole boundary; every base-to-apex edge is shared
by two adjacent faces, so the apex is interior. All four base vertices sit
at the mesh's own z-minimum (0.0), so infer_support_ids must find exactly
those four and no others.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "tiny-pyramid-compas.json"


def studio():
    import sys

    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import derive_contract

    return derive_contract


def pyramid_document():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_derive_contract_reads_the_string_encoded_thrust_mesh():
    d = studio()
    contract = d.derive_contract(pyramid_document())
    vertices = contract["equilibrium"]["vertices"]
    assert len(vertices) == 5
    assert vertices[4] == {"x": 1.0, "y": 1.0, "z": 1.0}
    faces = contract["formGraph"]["faces"]
    assert faces == [
        {"vertices": [0, 1, 4]}, {"vertices": [1, 2, 4]},
        {"vertices": [2, 3, 4]}, {"vertices": [3, 0, 4]},
    ]


def test_derive_contract_accepts_an_already_parsed_thrust_mesh_too():
    # Defensive support for a caller (or a future export format) that skips
    # the double JSON encoding: the SAME document, with thrustMesh
    # pre-parsed into a dict, must derive identically.
    d = studio()
    document = pyramid_document()
    document["thrustMesh"] = json.loads(document["thrustMesh"])
    assert isinstance(document["thrustMesh"], dict)
    contract = d.derive_contract(document)
    assert len(contract["equilibrium"]["vertices"]) == 5
    assert contract["equilibrium"]["resolvedSupportNodeIds"] == [0, 1, 2, 3]


def test_derive_contract_infers_exactly_the_four_grounded_feet():
    # The exact rule, pinned: a boundary vertex (an edge used by exactly
    # one face) whose z sits within SUPPORT_Z_TOLERANCE of the whole
    # mesh's own z-minimum. The apex (interior, and not at z-min) must be
    # excluded; every base vertex (boundary, at z-min) must be included.
    d = studio()
    contract = d.derive_contract(pyramid_document())
    assert contract["equilibrium"]["resolvedSupportNodeIds"] == [0, 1, 2, 3]
    assert contract["provenance"]["support_count"] == 4


def test_infer_support_ids_rule_is_boundary_and_z_tolerance():
    d = studio()
    # A 2x2 grid of 4 vertices: 0,1 on the ground (z=0), 2 within
    # tolerance of it (z=0.0005), 3 clearly above it (z=0.01). One
    # triangle face makes 0,1,2 boundary (every edge singly used) and
    # leaves 3 out of every face entirely (not boundary, not interior --
    # simply absent from the mesh's own topology).
    vertices = [
        {"x": 0.0, "y": 0.0, "z": 0.0},
        {"x": 1.0, "y": 0.0, "z": 0.0},
        {"x": 0.5, "y": 1.0, "z": 0.0005},
        {"x": 2.0, "y": 2.0, "z": 0.01},
    ]
    faces = [[0, 1, 2]]
    supports = d.infer_support_ids(vertices, faces, tolerance=1e-3)
    assert supports == [0, 1, 2]
    # Vertex 3 is not a face vertex at all, so it can never be "on the
    # boundary" regardless of z -- infer_support_ids only ever answers
    # from the mesh's own topology, never a bare coordinate scan.
    assert 3 not in supports


def test_infer_support_ids_tolerance_is_a_hard_cutoff():
    d = studio()
    vertices = [
        {"x": 0.0, "y": 0.0, "z": 0.0},
        {"x": 1.0, "y": 0.0, "z": 0.001},   # exactly at tolerance: included
        {"x": 0.0, "y": 1.0, "z": 0.0010001},  # a hair over: excluded
    ]
    faces = [[0, 1, 2]]
    supports = d.infer_support_ids(vertices, faces, tolerance=1e-3)
    assert supports == [0, 1]


def test_infer_support_ids_excludes_interior_vertices_even_at_z_min():
    # An interior vertex sitting at the mesh's own z-minimum is still not
    # a support: the rule is boundary AND z-tolerance, not either alone.
    # A 4-triangle fan around a centre vertex, all six rim/centre points
    # at z=0 except one rim point raised, makes the centre interior
    # (every edge to it shared by two faces) while every rim point stays
    # boundary.
    d = studio()
    vertices = [
        {"x": 0.0, "y": 0.0, "z": 0.0},   # 0: centre
        {"x": 1.0, "y": 0.0, "z": 0.0},   # 1: rim
        {"x": 0.0, "y": 1.0, "z": 0.0},   # 2: rim
        {"x": -1.0, "y": 0.0, "z": 0.0},  # 3: rim
        {"x": 0.0, "y": -1.0, "z": 0.0},  # 4: rim
    ]
    faces = [[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 1]]
    supports = d.infer_support_ids(vertices, faces, tolerance=1e-3)
    assert 0 not in supports, "the centre is interior, not a support, despite sitting at z-min"
    assert supports == [1, 2, 3, 4]


def test_derive_contract_stamps_a_geometry_only_provenance_marker():
    d = studio()
    contract = d.derive_contract(pyramid_document())
    assert contract["provenance"]["derived"] == d.DERIVED_MARKER
    assert "no analysis in this export" in d.DERIVED_MARKER
    assert contract["provenance"]["vertex_count"] == 5
    assert contract["provenance"]["face_count"] == 4


def test_derive_contract_ships_zero_forces_loads_reactions_and_edges():
    # geometry.py's own parsers treat an empty list as "no data" and never
    # raise -- member_forces_newtons returns [] before it would even check
    # edges length; node_loads_newtons/support_reactions_newtons return {}.
    # Pinned here against geometry.py directly, not just re-checked in
    # derive_contract's own output, so a future geometry.py change that
    # stops tolerating an empty list is caught by the module it actually
    # breaks.
    import sys
    sys.path.insert(0, str(REPO / "bench" / "studio"))
    import geometry

    d = studio()
    contract = d.derive_contract(pyramid_document())
    assert geometry.member_forces_newtons(contract) == []
    assert geometry.node_loads_newtons(contract) == {}
    assert geometry.support_reactions_newtons(contract) == {}
    arrays = geometry.mesh_arrays(contract)
    assert arrays["edges"] == []
    assert geometry.support_ids(contract) == [0, 1, 2, 3]


@pytest.mark.parametrize("bad_document,message_fragment", [
    ({}, "no thrustMesh"),
    ({"thrustMesh": "not json"}, "not valid JSON"),
    ({"thrustMesh": "42"}, "neither a JSON-encoded string nor an object"),
    ({"thrustMesh": {"dtype": "compas.datastructures/Mesh"}}, "no 'data' block"),
    ({"thrustMesh": {"data": {"face": {"0": [0, 1, 2]}}}}, "vertex is missing or empty"),
    ({"thrustMesh": {"data": {"vertex": {"0": {"x": 0, "y": 0, "z": 0}}}}}, "face is missing or empty"),
])
def test_derive_contract_names_the_actual_break(bad_document, message_fragment):
    d = studio()
    with pytest.raises(ValueError, match=message_fragment):
        d.derive_contract(bad_document)


def test_derive_contract_rejects_a_gap_in_vertex_ids():
    # formGraph.faces indexes directly into equilibrium.vertices (geometry.
    # py's own contract), so a vertex id gap would silently misalign every
    # face against the wrong row rather than raising -- this must be
    # caught here, before that can happen.
    d = studio()
    document = {
        "thrustMesh": {
            "data": {
                "vertex": {
                    "0": {"x": 0.0, "y": 0.0, "z": 0.0},
                    "2": {"x": 1.0, "y": 0.0, "z": 0.0},  # "1" is missing
                },
                "face": {"0": [0, 2]},
            }
        }
    }
    with pytest.raises(ValueError, match="contiguous 0..N-1"):
        d.derive_contract(document)


def test_derive_contract_rejects_a_face_index_out_of_range():
    d = studio()
    document = {
        "thrustMesh": {
            "data": {
                "vertex": {"0": {"x": 0.0, "y": 0.0, "z": 0.0}},
                "face": {"0": [0, 1, 2]},
            }
        }
    }
    with pytest.raises(ValueError, match="outside 0..0"):
        d.derive_contract(document)
