from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest_data import tiny_contract

REPO = Path(__file__).resolve().parents[2]


def studio(tmp_path=None):
    import sys

    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import bundle
    import geometry

    return geometry, bundle


def fake_export(tmp_path, monkeypatch):
    """Point bundle.py at a temp upload/studies pair with the tiny contract."""

    geometry, bundle = studio()
    # Each fake export is a fresh scenario, but bundle._cut_memo is a
    # process-global keyed only on (export_name, pattern, size): without
    # clearing it, an earlier test's memoized cut for "Tiny" would leak
    # into a later test that expects its own upload dir's sidecar to be
    # read fresh. conftest.py's autouse fixture clears it around every
    # studio test now, mirroring what a real re-upload does through
    # app._invalidate_studio_cache.
    upload = tmp_path / "upload"
    studies = tmp_path / "studies"
    upload.mkdir()
    studies.mkdir()
    (upload / "Tiny-contract.json").write_text(
        json.dumps(tiny_contract()), encoding="utf-8"
    )
    (upload / "Tiny-compas.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(bundle, "UPLOAD_DIR", upload)
    monkeypatch.setattr(bundle, "STUDIES_DIR", studies)
    return bundle, upload, studies


def test_bundle_builds_without_staging_or_verification(tmp_path, monkeypatch):
    bundle, _, studies = fake_export(tmp_path, monkeypatch)
    document = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert document["slug"] == "tiny"
    assert document["staging"] is None
    assert document["verification"] is None
    assert len(document["analysis_mesh"]["faces"]) == 4
    assert len(document["render_mesh"]["faces"]) == 16
    assert document["supports"] == [0, 2, 6, 8]
    assert document["loads"]["4"] == [0.0, 0.0, -1000.0]
    assert document["reactions"] == {}
    assert document["member_forces"] == []
    # tiny_contract's four faces are one course of bonded courses at this
    # target size (see test_the_bundle_ships_the_tessellation_and_its_report
    # for the tessellation report itself); this pins the analysis binding
    # that replaces the old ring/wedge "segments" shape.
    assert len(document["binding"]["assignment"]) == 4
    assert (
        studies / "tiny" / "studio"
        / "bundle-concrete-bonded-courses-s900-t200.json"
    ).is_file()


def test_bundle_embeds_staging_and_verification_when_present(tmp_path, monkeypatch):
    bundle, _, studies = fake_export(tmp_path, monkeypatch)
    target = studies / "tiny" / "studio"
    target.mkdir(parents=True)
    (target / "staging-concrete-bonded-courses-s900-t200.json").write_text(
        json.dumps({"size": 0.9, "stages": []}), encoding="utf-8"
    )
    (studies / "tiny" / "fea-verification.json").write_text(
        json.dumps({"material": "C30/37 unreinforced"}), encoding="utf-8"
    )
    document = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert document["staging"] == {"size": 0.9, "stages": []}
    assert document["verification"]["material"] == "C30/37 unreinforced"


def test_bundle_ships_converted_member_forces_when_present(tmp_path, monkeypatch):
    bundle, upload, _ = fake_export(tmp_path, monkeypatch)
    contract = tiny_contract()
    contract["equilibrium"]["memberForces"] = [-2.0] * 12
    (upload / "Tiny-contract.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )
    document = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert document["member_forces"] == [-2000.0] * 12


def test_load_or_build_serves_the_cache_without_rebuilding(tmp_path, monkeypatch):
    bundle, _, studies = fake_export(tmp_path, monkeypatch)
    first = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    path = bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    cached = json.loads(path.read_text(encoding="utf-8"))
    cached["generated"] = "MARKER"
    path.write_text(json.dumps(cached), encoding="utf-8")
    second = bundle.load_or_build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert second["generated"] == "MARKER"
    assert first["generated"] != "MARKER"


def test_unknown_export_fails_with_the_available_names(tmp_path, monkeypatch):
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="Tiny"):
        bundle.build_bundle("Nope", "concrete", "bonded-courses", 0.9)


def bay_contract():
    """A 3x3 grid of unit quads with the (2, 1) face removed.

    The bay makes the plan genuinely not star shaped about its own axis --
    the same fixture shape test_app.py's own bay_contract() uses to drive
    this through the API; this copy exercises build_bundle directly. See
    that docstring for the geometric reasoning.
    """
    side, n = 3, 4
    verts = [
        {"x": float(i), "y": float(j), "z": 0.0}
        for j in range(n) for i in range(n)
    ]
    faces = []
    fid = 0
    for j in range(side):
        for i in range(side):
            if (i, j) == (2, 1):
                continue
            faces.append({
                "id": fid,
                "vertices": [
                    j * n + i, j * n + i + 1,
                    (j + 1) * n + i + 1, (j + 1) * n + i,
                ],
            })
            fid += 1
    edges = []
    for face in faces:
        v = face["vertices"]
        for k in range(4):
            edges.append({"u": v[k], "v": v[(k + 1) % 4]})
    return {
        "equilibrium": {
            "vertices": verts, "edges": edges, "loads": [],
            "resolvedSupportNodeIds": [0],
        },
        "formGraph": {"faces": faces},
    }


def holed_contract():
    """A 9x9 grid of unit quads on a paraboloid, apex over the grid's own
    centre, with the off-centre 2x2 block of faces (2, 2), (2, 3), (3, 2),
    (3, 3) dropped -- one interior opening, well clear of the plan's own
    axis. The same geometry test_app.py's own holed_contract() drives
    through the API (see that docstring), here exercising build_bundle
    directly.
    """
    side, n = 9, 10
    center = side / 2.0

    def z(x, y):
        return 2.0 - ((x - center) ** 2) / 20.0 - ((y - center) ** 2) / 20.0

    verts = [
        {"x": float(i), "y": float(j), "z": z(float(i), float(j))}
        for j in range(n) for i in range(n)
    ]
    drop = {(2, 2), (2, 3), (3, 2), (3, 3)}
    faces = []
    fid = 0
    for j in range(side):
        for i in range(side):
            if (i, j) in drop:
                continue
            faces.append({
                "id": fid,
                "vertices": [
                    j * n + i, j * n + i + 1,
                    (j + 1) * n + i + 1, (j + 1) * n + i,
                ],
            })
            fid += 1
    edges = []
    for face in faces:
        v = face["vertices"]
        for k in range(4):
            edges.append({"u": v[k], "v": v[(k + 1) % 4]})
    return {
        "equilibrium": {
            "vertices": verts, "edges": edges, "loads": [],
            "resolvedSupportNodeIds": [0],
        },
        "formGraph": {"faces": faces},
    }


def test_a_cut_refusal_ships_uncut_not_written_to_disk(tmp_path, monkeypatch):
    """P5 (presentation batch, 2026-08-18): build_bundle's own half of the
    contract get_bundle relies on (test_app.py pins the HTTP shape). The
    engine's refusal (generators.generate's "not star shaped" message,
    reached through CutRefused) must not raise out of build_bundle at all:
    the bundle ships with pieces empty and uncut_reason set to the
    message, and -- the cache decision -- it is never written to
    bundle_path, so a later, cuttable re-request (a different pattern, a
    fixed export) is never blocked from a real cut by a stale uncut file
    sitting at that path.
    """
    bundle, upload, studies = fake_export(tmp_path, monkeypatch)
    (upload / "Bay-contract.json").write_text(
        json.dumps(bay_contract()), encoding="utf-8"
    )
    (upload / "Bay-compas.json").write_text("{}", encoding="utf-8")
    document = bundle.build_bundle("Bay", "concrete", "bonded-courses", 0.9)
    assert document["pieces"] == []
    assert document["tessellation"] is None
    assert document["binding"] is None
    assert document["staging"] is None
    reason = document["uncut_reason"]
    assert reason and "not star shaped" in reason
    assert document["analysis_mesh"]["faces"], "the mesh ships regardless"
    assert document["pattern"] == "bonded-courses"
    target = bundle.bundle_path("bay", "concrete", "bonded-courses", 0.9, 0.2)
    assert not target.exists(), "an uncut bundle must not be cached to disk"
    # load_or_build_bundle must therefore recompute it fresh every time,
    # rather than serving a stale uncut document from a path nothing wrote.
    again = bundle.load_or_build_bundle("Bay", "concrete", "bonded-courses", 0.9)
    assert again["uncut_reason"] == reason
    assert not target.exists()


def test_a_malformed_authored_tessellation_still_raises_plain_valueerror(
    tmp_path, monkeypatch
):
    """CutRefused must not swallow a malformed AUTHORED tessellation: that
    is bad input (tessellation.from_document raising on a broken cell),
    not a valid plan the engine declines to cover, and get_bundle's own
    400 contract for it (test_app.py's test_a_malformed_authored_
    tessellation_is_a_400_naming_the_cell) depends on it staying a plain
    ValueError, not the CutRefused subclass build_bundle now catches.
    """
    bundle, upload, _ = fake_export(tmp_path, monkeypatch)
    contract = tiny_contract()
    contract["tessellation"] = {
        "schema": "bench.tessellation/1", "units": "m", "domain": "plan",
        "pattern": "authored", "cells": ["oops"],
    }
    (upload / "Tiny-contract.json").write_text(
        json.dumps(contract), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="cell 0") as excinfo:
        bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert not isinstance(excinfo.value, bundle.CutRefused)


def test_bundles_are_cached_per_thickness(tmp_path, monkeypatch):
    bundle, _, studies = fake_export(tmp_path, monkeypatch)
    default = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    thin = bundle.build_bundle(
        "Tiny", "concrete", "bonded-courses", 0.9, thickness=0.1
    )
    assert default["provenance"]["thickness"] == 0.2
    assert thin["provenance"]["thickness"] == 0.1
    # K1 (cutting truth, 2026-08-17): the surface pieces.py ships is now
    # the intrados, named explicitly so a viewer can tell the convention a
    # bundle was built under; every thickness variant carries it.
    assert default["provenance"]["surface"] == "intrados"
    assert thin["provenance"]["surface"] == "intrados"
    assert (
        studies / "tiny" / "studio"
        / "bundle-concrete-bonded-courses-s900-t200.json"
    ).is_file()
    assert (
        studies / "tiny" / "studio"
        / "bundle-concrete-bonded-courses-s900-t100.json"
    ).is_file()


def test_the_bundle_ships_drawn_pieces_on_the_render_mesh(tmp_path, monkeypatch):
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    document = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    pieces = document["pieces"]
    assert pieces, "the bundle must carry the pieces the viewer draws"
    # A key is the casting's identity in the viewer: its tint, its texture
    # offset and its entry in the placement index all hang off it.
    # segment_pieces builds exactly one piece per tessellation cell (see
    # test_one_piece_per_cell_in_placement_order in test_pieces.py), so both
    # the key uniqueness and the piece-per-cell count below are structural
    # guarantees of the current architecture, not properties this fixture
    # happens to have. (An older pieces.py, retired, could split one cell
    # into more than one drawn casting; that shape no longer exists.)
    keys = [piece["key"] for piece in pieces]
    assert len(set(keys)) == len(keys), "two castings cannot share one key"
    assert len(keys) == len(document["binding"]["order"]), (
        "one piece per cell is structural"
    )
    render_vertex_count = len(document["render_mesh"]["vertices"])
    for piece in pieces:
        assert len(piece["mid"]) == len(piece["normals"]) == len(piece["sources"])
        # Each piece vertex carries its barycentric weights over the render
        # mesh triangle it was lifted from -- (vertex_index, weight) pairs,
        # not a bare index -- so a field defined on the render mesh can be
        # interpolated at a point that is not one of its own vertices.
        for source in piece["sources"]:
            for vertex_index, _weight in source:
                assert 0 <= vertex_index < render_vertex_count, (
                    "piece vertex sources must index the render mesh, not "
                    "the analysis mesh"
                )
        assert piece["faces"], "a piece needs faces"


def test_timber_with_monolithic_bands_ships_no_seat_plane(tmp_path, monkeypatch):
    """I2, fix round 1 on K2 (2026-08-17): a jointed piece's seat_plane is
    decided by the CUT's pattern (pieces.segment_pieces has no material
    argument at all -- material and thickness never reach _cut_for, see
    bundle.py's own comment on that memoisation), not by whether the
    requested material is nominally a jointed one. The pattern control is
    independently overridable from the UI per material
    (studio.js's patternChosen survives a material change), so a user can
    really request timber (jointed by default, bonded-courses) with
    monolithic-bands (the sprayed generator): this is a combination
    reachable today through the real UI, not a hypothetical one. It must
    build cleanly and ship no seat_plane on any piece; the client falls
    back to K1's curved extrusion for a cut that has no real joints to
    begin with, whatever the material label says.
    """

    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    document = bundle.build_bundle("Tiny", "timber", "monolithic-bands", 0.9)
    assert document["pieces"], "the mismatched pairing must still cut and draw"
    for piece in document["pieces"]:
        assert "seat_plane" not in piece, piece["key"]
        assert "seat_gap" not in piece, piece["key"]
    assert document["tessellation"]["seat_gap_stats"] == {
        "count": 0, "median": 0.0, "max": 0.0,
    }


def test_stale_cached_bundles_missing_pieces_are_rebuilt(tmp_path, monkeypatch):
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    fresh = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    cached_path = bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    stale = dict(fresh)
    del stale["pieces"]
    cached_path.write_text(json.dumps(stale), encoding="utf-8")
    loaded = bundle.load_or_build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert loaded["pieces"], "stale cached bundle without pieces must be rebuilt"


def test_cached_bundles_with_two_castings_under_one_key_are_rebuilt(
    tmp_path, monkeypatch
):
    # A bundle written before pieces.py distinguished the separate patches
    # of a split cell holds two castings under one key, and the viewer
    # cannot tell them apart: same tint, same texture offset, one entry in
    # the placement index. That is stale in the same sense as a missing
    # field, so the cache has to notice it rather than serve it forever.
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    fresh = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    cached_path = bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    stale = dict(fresh)
    stale["pieces"] = [dict(piece) for piece in fresh["pieces"]]
    assert len(stale["pieces"]) > 1
    stale["pieces"][1]["key"] = stale["pieces"][0]["key"]
    cached_path.write_text(json.dumps(stale), encoding="utf-8")
    loaded = bundle.load_or_build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    keys = [piece["key"] for piece in loaded["pieces"]]
    assert len(set(keys)) == len(keys), "the duplicate key must be rebuilt away"


def test_the_bundle_ships_the_tessellation_and_its_report(tmp_path, monkeypatch):
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    document = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9, 0.2)
    assert document["tessellation"]["pattern"] == "bonded-courses"
    assert document["tessellation"]["source"] == "generated"
    assert document["tessellation"]["target_size"] == 0.9
    assert document["tessellation"]["courses"] >= 1
    assert document["tessellation"]["cells"] == len(document["pieces"])
    assert "chord_mm" in document["tessellation"]
    assert "corner_residual" in document["tessellation"]
    # tiny_contract's plan is a perfect square about its own centroid, so
    # its rim has no backward step at all; the fields still have to be
    # present (not just non-crashing) for a reader to see the wobble on a
    # real, less regular export. See test_domain.py for the nonzero case.
    assert document["tessellation"]["backward_turn_degrees"] == 0.0
    assert document["tessellation"]["backward_steps"] == 0
    # K3 (cutting truth, 2026-08-17): both fields must be present, not
    # crash for want of a boundary polyline ever mattering on this export.
    # tiny_contract's rim has no backward step and no notch, so nothing
    # here needs the old nearest-face clamp at all. Under the old
    # outermost crossing rule, a handful of boundary-corner outline points
    # still landed a float's width outside the primary containment test
    # (radius_at's own ray cast is a different computation from the
    # render mesh's stored vertex coordinates -- a corner graze took the
    # max of two crossings agreeing to within an ulp), and the projection
    # mechanism correctly caught those too, at 1e-16 m, machine epsilon,
    # nowhere near cutting.CHORD_TARGET.
    #
    # Rim remainder (2026-08-19): radius_at now returns the single counted
    # crossing at a graze rather than the max of two near-duplicates (see
    # docs/superpowers/specs/2026-08-19-rim-remainder-design.md), and on
    # this exact square that last-ulp drift now lands every corner exactly
    # on the mesh: measured here, both fields read as a true, clean zero,
    # not a residual hiding a bug that skipped the check silently.
    assert document["tessellation"]["clamped_points"] == 0
    assert document["tessellation"]["projected_points"] == 0
    assert document["tessellation"]["projected_max_m"] == 0.0


def test_the_openings_block_rides_the_summary(tmp_path, monkeypatch):
    """Multi-loop (2026-08-19): the five openings fields ride the
    tessellation summary the same way backward_turn_degrees/backward_steps
    do -- but ABSENT rather than None when the cut has no openings, since
    unlike backward_turn (measured on every generated domain) these five
    only exist on tess at all when generators.generate actually ran the
    clip pass. Tiny (fake_export's own fixture, used unmodified in
    test_the_bundle_ships_the_tessellation_and_its_report above) has no
    opening at all, so it is the no-openings half of this same assertion.
    """
    bundle, upload, _ = fake_export(tmp_path, monkeypatch)
    keys = (
        "openings", "cells_in_openings", "cells_clipped",
        "opening_slivers", "opening_clip_failures",
    )

    no_openings = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    for key in keys:
        assert key not in no_openings["tessellation"], (
            "a cut with no openings must not gain {!r}".format(key)
        )

    (upload / "Holed-contract.json").write_text(
        json.dumps(holed_contract()), encoding="utf-8"
    )
    (upload / "Holed-compas.json").write_text("{}", encoding="utf-8")
    holed = bundle.build_bundle("Holed", "concrete", "bonded-courses", 1.0)
    assert holed["uncut_reason"] is None
    for key in keys:
        assert key in holed["tessellation"], key
    assert holed["tessellation"]["openings"] == 1
    assert holed["tessellation"]["cells_clipped"] != []
    # opening_regions rides along too, but nested inside the tessellation
    # report -- the same generic "report" pass-through the five direct
    # keys above ride alongside, not a sixth top level field of its own.
    assert len(holed["tessellation"]["report"]["opening_regions"]) == 1


def test_the_cache_key_carries_size_and_pattern(tmp_path):
    b = studio()[1]
    first = b.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    second = b.bundle_path("tiny", "concrete", "monolithic-bands", 0.9, 0.2)
    third = b.bundle_path("tiny", "concrete", "bonded-courses", 1.2, 0.2)
    assert first != second and first != third
    assert "s900" in first.name


def test_a_bundle_without_a_tessellation_is_stale():
    b = studio()[1]
    assert "tessellation" in b.REQUIRED_BUNDLE_KEYS


def test_a_bundle_cached_before_a_tessellation_field_existed_is_stale(
    tmp_path, monkeypatch
):
    # Final fix wave. REQUIRED_BUNDLE_KEYS named only the two top level
    # keys, so a field added inside the tessellation summary mid-wave left
    # every bundle cached before it perfectly valid to this gate, and the
    # viewer read it unguarded: the Data button appeared to do nothing at
    # all on any machine that ran this branch while the wave was in
    # progress, the owner's included. A sub-field the viewer reads makes a
    # cache exactly as stale as a missing top level key does.
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    fresh = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    cached_path = bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    for path in (
        "tessellation.corner_residual_stats",
        "tessellation.facets_per_piece",
        "tessellation.boundary_points_per_piece",
        "tessellation.clamped_max_m",
        "tessellation.clamped_median_m",
        "tessellation.report.folded",
        # K2 (cutting truth, 2026-08-17): the seat-gap distribution, read
        # by the Data panel beside the corner residual stats.
        "tessellation.seat_gap_stats",
        # K3 (cutting truth, 2026-08-17): the count of points the new
        # boundary projection handled, read by the Data panel beside
        # clamped_max_m/clamped_median_m above.
        "tessellation.projected_points",
    ):
        assert path in bundle.REQUIRED_BUNDLE_KEYS, (
            "{} is read by the Data panel and must invalidate a cache that "
            "predates it".format(path)
        )
        parts = path.split(".")
        stale = json.loads(json.dumps(fresh))
        node = stale
        for part in parts[:-1]:
            node = node[part]
        del node[parts[-1]]
        cached_path.write_text(json.dumps(stale), encoding="utf-8")
        loaded = bundle.load_or_build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
        node = loaded
        for part in parts:
            assert part in node, (
                "a bundle missing {} was served rather than re-cut".format(path)
            )
            node = node[part]


def test_a_bundle_cached_before_the_boundary_loop_count_existed_is_stale(
    tmp_path, monkeypatch
):
    """Final fix wave (2026-08-19). The multi-loop task rerouted the lift
    attachment to walk every boundary loop (outer rim plus every opening's
    own rim) instead of just the outer one, but added no REQUIRED_BUNDLE_
    KEYS entry for it, so a bundle cached before that change (outer-only
    attachment, or none at all on a mesh the old domain.boundary_ring
    refused) kept passing every freshness gate and was served forever,
    still clamping cap points a fresh cut would now project onto the true
    rim. boundary_loops is the fix: an honest, always-present count of how
    many loops the attachment found (openings or not -- unlike the five
    openings fields pinned absent above, this one is not conditional on a
    clip pass ever running), so its absence alone is enough to force the
    rebuild.
    """

    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    fresh = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert "boundary_loops" in fresh["tessellation"]
    assert "tessellation.boundary_loops" in bundle.REQUIRED_BUNDLE_KEYS
    cached_path = bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    stale = json.loads(json.dumps(fresh))
    del stale["tessellation"]["boundary_loops"]
    cached_path.write_text(json.dumps(stale), encoding="utf-8")
    loaded = bundle.load_or_build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert "boundary_loops" in loaded["tessellation"], (
        "a bundle missing tessellation.boundary_loops was served rather "
        "than re-cut"
    )


def authored_sidecar():
    """One cell, "a", covering the bottom half of tiny_contract's plan.

    Half, not all, so the stage plan built from it carries a formwork
    total that is visibly the wrong number for the whole vault: exactly
    the mismatch the staleness gate exists to keep out of the HUD.
    """
    return {
        "schema": "bench.tessellation/1",
        "units": "m",
        "domain": "plan",
        "pattern": "authored",
        "cells": [
            {"key": "a", "course": 0,
             "outline": [[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]]},
        ],
    }


def authored_sidecar_with_a_degenerate_cell():
    """Two cells: "a" covers the whole tiny_contract plan, [0, 2] squared.
    "b" is a small (0.02 m) real quad sitting entirely past the domain's
    own top right corner (2, 2), in both x and y, so every one of its own
    four corners lands off the render mesh and projects onto the
    identical nearest boundary point, the corner itself -- the same
    collapse test_a_piece_that_collapses_below_three_corners_is_dropped_
    and_disclosed (test_pieces.py) exercises directly against pieces.py.
    Here the point is the CUT still names "b" (tessellation.
    build_tessellation, and staging.stage_plan built from it) even though
    pieces.segment_pieces drops it from the drawn pieces.
    """
    return {
        "schema": "bench.tessellation/1",
        "units": "m",
        "domain": "plan",
        "pattern": "authored",
        "cells": [
            {"key": "a", "course": 0,
             "outline": [[0.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0]]},
            {"key": "b", "course": 0,
             "outline": [[2.05, 2.05], [2.03, 2.05], [2.03, 2.03], [2.05, 2.03]]},
        ],
    }


def test_a_degenerate_dropped_cell_does_not_silently_drop_the_staging_plan(
    tmp_path, monkeypatch
):
    """Review fix (2026-08-18), MUST FIX 1, end to end. Before this fix,
    bundle._staging_matches's plain subset test silently dropped the
    whole staging plan (and with it the formwork animation and the CRA
    verdict) with no message at all, whenever the cut's own guard-
    degeneracy pass dropped even one cell the plan legitimately named --
    exactly what the real Trial 2 export does at 0.30 m (see
    .superpowers/sdd/2026-08-18-rim-spikes/diagnosis.md and outcome.md).
    """
    bundle, upload, _ = fake_export(tmp_path, monkeypatch)
    sidecar = bundle.tessellation_sidecar("Tiny")
    sidecar.write_text(
        json.dumps(authored_sidecar_with_a_degenerate_cell()), encoding="utf-8"
    )

    import staging as staging_module
    staged = staging_module.run_staging(
        {"contract": upload / "Tiny-contract.json",
         "geometry": upload / "Tiny-compas.json"},
        material="concrete", pattern="bonded-courses", size=0.9,
        out_path=bundle.staging_path("tiny", "concrete", "bonded-courses", 0.9, 0.2),
        runner=lambda request: {"converged": True, "message": ""},
        include_cra=False,
    )
    named = {s for stage in staged["stages"] for s in stage["segments"]}
    assert "b" in named, "the cut itself must still stage the cell that later drops"

    document = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9, 0.2)
    drawn = {piece["key"] for piece in document["pieces"]}
    assert drawn == {"a"}, "cell b must have been dropped as degenerate, not drawn"
    assert document["tessellation"]["degenerate_dropped"] == ["b"]
    assert document["staging"] is not None, (
        "a plan naming a degenerate-dropped key must still ship"
    )


def staged_against(bundle, upload):
    import staging as staging_module

    return staging_module.run_staging(
        {"contract": upload / "Tiny-contract.json",
         "geometry": upload / "Tiny-compas.json"},
        material="concrete", pattern="bonded-courses", size=0.9,
        out_path=bundle.staging_path("tiny", "concrete", "bonded-courses",
                                     0.9, 0.2),
        runner=lambda request: {"converged": True, "message": ""},
        include_cra=False,
    )


def test_staging_built_from_another_cut_is_dropped_not_embedded(
    tmp_path, monkeypatch
):
    """A stage plan naming cells this cut does not draw must not ship.

    The sequence is the one a user reaches by hand: stage against an
    authored sidecar, lose the sidecar (it is in neither the bundle cache
    key nor app._invalidate_studio_cache), then delete bundle-*.json to
    force a re-cut, which is the documented workaround and which leaves
    staging-*.json behind. The rebuilt bundle draws generated cells; the
    stale plan on disk still names the authored cell "a".

    Nothing crashes when the two disagree, so a test that only asserted
    "no exception" would pass against the broken build. The assertion has
    to be that the plan is gone.
    """
    bundle, upload, _ = fake_export(tmp_path, monkeypatch)

    sidecar = bundle.tessellation_sidecar("Tiny")
    sidecar.write_text(json.dumps(authored_sidecar()), encoding="utf-8")
    staged = staged_against(bundle, upload)
    assert [s["segments"] for s in staged["stages"]] == [["a"]]
    # app.py writes the pair together, so the honest starting point is a
    # bundle that agrees with its plan.
    first = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9, 0.2)
    assert first["staging"] is not None
    assert [piece["key"] for piece in first["pieces"]] == ["a"]

    # The sidecar goes; the bundle is deleted to force a re-cut; staging
    # stays on disk exactly as it was. Deleting the bundle file alone no
    # longer forces the re-cut now that build_bundle goes through the cut
    # memo (Task 5): the memo, keyed on export/pattern/size, is in neither
    # the on-disk cache key nor this file deletion, same gap as the
    # sidecar itself. In the running server this is cleared for free by
    # app._invalidate_studio_cache on every re-upload; here, in the same
    # process as the first cut, it has to be cleared explicitly to reach
    # the state a real re-upload would leave behind.
    sidecar.unlink()
    bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2).unlink()
    bundle.clear_cut_memo()
    assert bundle.staging_path(
        "tiny", "concrete", "bonded-courses", 0.9, 0.2).is_file()

    rebuilt = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9, 0.2)
    drawn = {piece["key"] for piece in rebuilt["pieces"]}
    assert "a" not in drawn, "the re-cut must have generated its own cells"
    assert rebuilt["staging"] is None, (
        "a stage plan naming cell 'a' was embedded against pieces keyed "
        "{}".format(sorted(drawn))
    )


def test_staging_from_the_same_cut_is_still_embedded(tmp_path, monkeypatch):
    """The gate must not throw away a plan that does match.

    A matching plan names exactly the drawn cells, so the guard has to
    admit it. A gate that dropped everything would pass the test above
    while making the whole staging feature dead.
    """
    bundle, upload, _ = fake_export(tmp_path, monkeypatch)
    staged_against(bundle, upload)
    document = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9, 0.2)
    assert document["staging"] is not None
    named = {s for stage in document["staging"]["stages"]
             for s in stage["segments"]}
    assert named == {piece["key"] for piece in document["pieces"]}


def test_the_staleness_gate_compares_segments_against_piece_keys():
    """The gate itself, exercised on both sides of the subset test."""
    b = studio()[1]
    made = [{"key": "c0p0"}, {"key": "c0p1"}]
    assert b._staging_matches({"stages": [{"segments": ["c0p0"]}]}, made)
    assert b._staging_matches(
        {"stages": [{"segments": ["c0p0"]},
                    {"segments": ["c0p0", "c0p1"]}]}, made)
    assert not b._staging_matches({"stages": [{"segments": ["a"]}]}, made)
    assert not b._staging_matches(
        {"stages": [{"segments": ["c0p0", "gone"]}]}, made)
    assert not b._staging_matches(None, made)
    # An empty plan names nothing, so it cannot contradict the cut.
    assert b._staging_matches({"stages": []}, made)


def test_the_staleness_gate_tolerates_degenerate_dropped_keys():
    """Review fix (2026-08-18), MUST FIX 1: a cell the tessellation itself
    names, and that a stage plan therefore legitimately stages, can still
    be dropped by pieces.segment_pieces's own guard-degeneracy pass
    (untriangulatable, or collapsed below 3 corners after the
    rim-rectangular snap -- see pieces.py). That is a real cell of THIS
    cut that never became a drawn piece, not a mismatch with a different
    cut's plan, which is the only thing this gate exists to catch. The
    degenerate_dropped argument lets the gate tell the two apart.
    """
    b = studio()[1]
    made = [{"key": "c0p0"}, {"key": "c0p1"}]
    assert b._staging_matches(
        {"stages": [{"segments": ["c0p0", "c0p1", "c1p67"]}]}, made, ["c1p67"])
    # A key on neither list is still a real mismatch.
    assert not b._staging_matches(
        {"stages": [{"segments": ["c0p0", "gone"]}]}, made, ["c1p67"])
    # No degenerate_dropped argument at all keeps the old, strict rule.
    assert not b._staging_matches(
        {"stages": [{"segments": ["c0p0", "c1p67"]}]}, made)


def test_the_cut_is_reused_across_material_and_thickness(tmp_path, monkeypatch):
    # The cut's inputs are export geometry, pattern and size: material
    # and thickness never reach it. Switching material at an already-cut
    # size must reuse the cut rather than re-run it, which is what makes
    # a material swap near-instant in the viewer.
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    bundle.clear_cut_memo()
    calls = []
    real = bundle.build_tessellation_for

    def counting(*args, **kwargs):
        calls.append(args[0])
        return real(*args, **kwargs)

    monkeypatch.setattr(bundle, "build_tessellation_for", counting)
    bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    bundle.build_bundle("Tiny", "timber", "bonded-courses", 0.9, thickness=0.3)
    assert calls == ["Tiny"], "the second build must hit the cut memo"
    # A different size is a different cut.
    bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.6)
    assert calls == ["Tiny", "Tiny"]
    # Clearing the memo (what an export re-upload does through
    # app._invalidate_studio_cache) forces a fresh cut, so a stale cut
    # can never outlive its export.
    bundle.clear_cut_memo()
    bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.6)
    assert calls == ["Tiny", "Tiny", "Tiny"]


def _studio_module(name):
    """Import a bench/studio module by name, after fake_export/studio()
    has already put bench/studio on sys.path."""
    import importlib

    return importlib.import_module(name)


def test_single_flight_joins_a_cold_identical_key(tmp_path, monkeypatch):
    """(a) Cut cancellation, task 2 acceptance bar: two callers requesting
    the identical cold cut key concurrently must run segment_pieces
    exactly ONCE, and both must receive the SAME result object -- not two
    equal-but-separate computes, the whole point of joining at the
    _cut_for layer where the memo already lives (see bundle._cut_for's
    own docstring).

    Deterministic via an Event handshake, not a sleep: the fake
    segment_pieces signals "started" (proof the builder has already
    registered itself in _cut_inflight, since that registration happens
    strictly before build_tessellation_for/segment_pieces are ever
    called) before blocking on "release", so the second thread is only
    started once a join is guaranteed to be possible. Whichever thread
    the OS actually schedules to reach _cut_for's own lock-guarded check
    first, the outcome is the same: segment_pieces runs once, both
    threads read the identical result (either as the builder or by
    joining/reading straight out of the now-populated memo).
    """
    import threading

    bundle, upload, studies = fake_export(tmp_path, monkeypatch)
    pieces = _studio_module("pieces")

    started = threading.Event()
    release = threading.Event()
    calls = []
    real_segment_pieces = pieces.segment_pieces

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        calls.append(1)
        started.set()
        assert release.wait(timeout=5), "release was never set"
        return real_segment_pieces(tess, surface, support_points, checkpoint=checkpoint)

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    pairs = bundle.geometry.available_exports(bundle.UPLOAD_DIR)
    contract = bundle.geometry.load_contract(pairs["Tiny"]["contract"])
    arrays = bundle.geometry.mesh_arrays(contract)
    render = bundle._render_mesh(arrays["vertices"], arrays["faces"])

    results = {}

    def call(name):
        results[name] = bundle._cut_for(
            "Tiny", contract, arrays, render, "bonded-courses", 0.9)

    t1 = threading.Thread(target=call, args=("first",))
    t1.start()
    assert started.wait(timeout=5), "the builder never started"

    t2 = threading.Thread(target=call, args=("second",))
    t2.start()

    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive(), "a thread never finished"

    assert len(calls) == 1, (
        "segment_pieces must run exactly once for a single-flight join, "
        "ran {} times".format(len(calls))
    )
    assert results["first"] is results["second"], (
        "a joiner must share the builder's own result object, not a "
        "separately computed equal one"
    )


def test_identical_key_newer_interactive_request_joins_not_supersedes(tmp_path, monkeypatch):
    """(d) Cut cancellation, task 2 acceptance bar: a second interactive
    request for the SAME (export, pattern, size) key must join the
    first's in-flight build rather than superseding it, even though its
    own token is strictly newer than the first's -- an identical key
    never supersedes (bundle.superseded's own docstring), because the
    second request finds the key already building and joins instead of
    starting a build of its own.
    """
    import threading

    bundle, upload, studies = fake_export(tmp_path, monkeypatch)
    pieces = _studio_module("pieces")

    started = threading.Event()
    release = threading.Event()
    calls = []
    real_segment_pieces = pieces.segment_pieces

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        calls.append(1)
        started.set()
        assert release.wait(timeout=5), "release was never set"
        if checkpoint is not None:
            # Must NOT raise: the second, newer registration below shares
            # this exact key, so it must never read as a supersession.
            checkpoint()
        return real_segment_pieces(tess, surface, support_points, checkpoint=checkpoint)

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    key = ("Tiny", "bonded-courses", 0.9)
    results = {}
    errors = {}

    def call_first():
        token = bundle.register_interactive("Tiny", key)
        try:
            results["first"] = bundle.build_bundle(
                "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=token)
        except Exception as error:
            errors["first"] = error

    t1 = threading.Thread(target=call_first)
    t1.start()
    assert started.wait(timeout=5), "the first build never started"

    def call_second():
        # The SAME key, a strictly newer token: must join, not supersede.
        token = bundle.register_interactive("Tiny", key)
        try:
            results["second"] = bundle.build_bundle(
                "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=token)
        except Exception as error:
            errors["second"] = error

    t2 = threading.Thread(target=call_second)
    t2.start()

    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive(), "a thread never finished"

    assert not errors, "an identical key must never raise CutSuperseded: {}".format(errors)
    assert len(calls) == 1, "an identical key must join, not trigger a second cut"
    assert results["first"]["pieces"] == results["second"]["pieces"]


def test_a_staging_shaped_build_completes_despite_interactive_supersession(tmp_path, monkeypatch):
    """(c) Cut cancellation, task 2 acceptance bar: build_bundle called
    with no interactive_token (the staging path's own shape -- see
    app.py's start_run() work(), which never passes one) builds no
    checkpoint at all and so can never be superseded, even while a
    DIFFERENT, later interactive registration for the same export exists.
    A run's cut must complete even if the user flips patterns while it
    runs (see the design doc's own "out of scope" list).
    """
    import threading

    bundle, upload, studies = fake_export(tmp_path, monkeypatch)
    pieces = _studio_module("pieces")

    started = threading.Event()
    release = threading.Event()
    real_segment_pieces = pieces.segment_pieces

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        assert checkpoint is None, (
            "a staging-shaped build (no interactive_token) must never "
            "receive a checkpoint at all"
        )
        started.set()
        assert release.wait(timeout=5), "release was never set"
        return real_segment_pieces(tess, surface, support_points, checkpoint=checkpoint)

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    result = {}

    def call_staging():
        result["document"] = bundle.build_bundle(
            "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=None)

    t = threading.Thread(target=call_staging)
    t.start()
    assert started.wait(timeout=5), "the staging build never started"

    # A newer interactive request, a DIFFERENT key, registers for this
    # very export while the staging build (no token, no checkpoint) is
    # blocked mid-cut -- the condition that WOULD supersede an
    # interactive build of the staging build's own key.
    bundle.register_interactive("Tiny", ("Tiny", "monolithic-bands", 1.2))

    release.set()
    t.join(timeout=5)
    assert not t.is_alive(), "the staging build never finished"

    assert result["document"]["uncut_reason"] is None
    assert result["document"]["pieces"], (
        "a staging-shaped build must complete its cut even while "
        "interactive supersession fires for its export"
    )


def test_a_fresh_bundle_carries_the_crossing_rule_stamp(tmp_path, monkeypatch):
    """(e) Cut cancellation, task 2 acceptance bar: a fresh bundle carries
    tessellation.crossing_rule == domain.CROSSING_RULE, and that key is
    part of REQUIRED_BUNDLE_KEYS so a cache built before it existed is
    stale (see the staleness-rebuild test below, mirroring the
    boundary_loops staleness test above)."""
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    domain = _studio_module("domain")
    fresh = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert fresh["tessellation"]["crossing_rule"] == "first-exit-2026-08-19"
    assert fresh["tessellation"]["crossing_rule"] == domain.CROSSING_RULE
    assert "tessellation.crossing_rule" in bundle.REQUIRED_BUNDLE_KEYS


def test_a_bundle_cached_under_an_earlier_crossing_rule_is_stale(tmp_path, monkeypatch):
    """Cut cancellation rider (2026-08-19): a bundle cached before this
    task carries no crossing_rule at all -- and, in the future, one
    cached under whatever rule replaces first-exit-2026-08-19 will carry
    an outdated value instead. Either way, a cache whose stamp does not
    match domain.CROSSING_RULE must be rebuilt, the same staleness shape
    as test_a_bundle_cached_before_the_boundary_loop_count_existed_is_
    stale above.
    """
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    fresh = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert "crossing_rule" in fresh["tessellation"]
    cached_path = bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    stale = json.loads(json.dumps(fresh))
    del stale["tessellation"]["crossing_rule"]
    cached_path.write_text(json.dumps(stale), encoding="utf-8")
    loaded = bundle.load_or_build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert "crossing_rule" in loaded["tessellation"], (
        "a bundle missing tessellation.crossing_rule was served rather "
        "than re-cut"
    )
    assert loaded["tessellation"]["crossing_rule"] == "first-exit-2026-08-19"


def test_a_bundle_cached_under_an_outdated_crossing_rule_value_is_stale(tmp_path, monkeypatch):
    """Fix round 1, review finding I4 (Important): REQUIRED_BUNDLE_KEYS
    alone is presence-only -- a cached bundle whose crossing_rule field
    EXISTS but carries an OUTDATED VALUE (from a previous CROSSING_RULE
    bump, not merely a bundle cut before the field existed at all, which
    the test above already covers) would pass every entry in that tuple
    unchanged, so a future bump of the constant would silently invalidate
    nothing. REQUIRED_BUNDLE_VALUES closes that: load_or_build_bundle's
    freshness gate compares the VALUE, not just presence.
    """
    bundle, _, _ = fake_export(tmp_path, monkeypatch)
    fresh = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    cached_path = bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    stale = json.loads(json.dumps(fresh))
    stale["tessellation"]["crossing_rule"] = "outermost-legacy"
    cached_path.write_text(json.dumps(stale), encoding="utf-8")
    loaded = bundle.load_or_build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert loaded["tessellation"]["crossing_rule"] == "first-exit-2026-08-19", (
        "a bundle carrying an OUTDATED crossing_rule VALUE was served "
        "rather than re-cut"
    )


def test_required_bundle_values_pins_the_crossing_rule():
    """REQUIRED_BUNDLE_VALUES' one entry today, and what it must equal --
    a direct pin so a future edit that lets the two drift apart (the
    constant bumped in domain.py without updating the dict, or vice
    versa) fails here rather than only showing up as a silent staleness
    miss."""
    bundle = studio()[1]
    domain = _studio_module("domain")
    assert bundle.REQUIRED_BUNDLE_VALUES == {
        "tessellation.crossing_rule": domain.CROSSING_RULE
    }


def test_a_builder_raising_baseexception_does_not_leak_the_holder(tmp_path, monkeypatch):
    """Fix round 1, review finding I3 (Important): the holder's error slot
    is documented as Optional[BaseException], but the original except
    clause caught only Exception, so a BaseException (KeyboardInterrupt,
    SystemExit, or anything else outside the Exception hierarchy) escaped
    the cleanup entirely and left the holder in _cut_inflight forever --
    permanent, since a joiner's wait is deliberately untimed. _cut_for now
    cleans up in a finally block that runs regardless of what was raised.

    Single-threaded and deterministic: no Event handshake is needed here,
    since the whole point is what happens AFTER the raise, in the same
    thread that raised it.
    """
    bundle, upload, studies = fake_export(tmp_path, monkeypatch)
    pieces = _studio_module("pieces")

    real_segment_pieces = pieces.segment_pieces
    calls = []

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        calls.append(1)
        if len(calls) == 1:
            raise KeyboardInterrupt("simulated interrupt mid-cut")
        return real_segment_pieces(tess, surface, support_points, checkpoint=checkpoint)

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    key = ("Tiny", "bonded-courses", 0.9)
    with pytest.raises(KeyboardInterrupt):
        bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)

    assert key not in bundle._cut_inflight, (
        "the holder must not leak after a BaseException"
    )

    # A fresh request for the same key must compute normally, not hang
    # forever waiting on a holder whose event was never set.
    document = bundle.build_bundle("Tiny", "concrete", "bonded-courses", 0.9)
    assert document["pieces"], "the next request for this key must compute normally"
    assert len(calls) == 2


def test_an_interactive_joiner_is_also_superseded_when_its_builder_is(tmp_path, monkeypatch):
    """Fix round 1: pins the half of review finding C1 that must NOT
    change. An INTERACTIVE joiner (its own token, the SAME key as the
    build it joins) is not exempt the way a token-less joiner now is:
    when the build it joined is superseded, the joiner is, at that same
    moment, also genuinely superseded (see the review's own coherence
    argument, interleaving path 5, and bundle.CutSuperseded's own
    docstring), so it correctly re-raises CutSuperseded rather than
    silently retrying. Both the builder's own caller and the joiner's own
    caller must see the cancellation.
    """
    import threading

    bundle, upload, studies = fake_export(tmp_path, monkeypatch)
    pieces = _studio_module("pieces")

    started = threading.Event()
    release = threading.Event()
    real_segment_pieces = pieces.segment_pieces

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        started.set()
        assert release.wait(timeout=5), "release was never set"
        if checkpoint is not None:
            checkpoint()
        return real_segment_pieces(tess, surface, support_points, checkpoint=checkpoint)

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    key = ("Tiny", "bonded-courses", 0.9)
    outcomes = {}

    def call_builder():
        token = bundle.register_interactive("Tiny", key)
        try:
            outcomes["builder"] = bundle.build_bundle(
                "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=token)
        except Exception as error:
            outcomes["builder"] = error

    t_builder = threading.Thread(target=call_builder)
    t_builder.start()
    assert started.wait(timeout=5), "the builder never started"

    def call_interactive_joiner():
        # The SAME key, a strictly newer token: joins, does not build.
        token = bundle.register_interactive("Tiny", key)
        try:
            outcomes["joiner"] = bundle.build_bundle(
                "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=token)
        except Exception as error:
            outcomes["joiner"] = error

    t_joiner = threading.Thread(target=call_interactive_joiner)
    t_joiner.start()

    # A newer, DIFFERENT key for the same export: supersedes both the
    # builder and the joiner sharing its key.
    bundle.register_interactive("Tiny", ("Tiny", "monolithic-bands", 1.2))
    release.set()
    t_builder.join(timeout=5)
    t_joiner.join(timeout=5)
    assert not t_builder.is_alive() and not t_joiner.is_alive()

    assert isinstance(outcomes["builder"], bundle.CutSuperseded), outcomes["builder"]
    assert isinstance(outcomes["joiner"], bundle.CutSuperseded), outcomes["joiner"]


def test_a_token_less_joiner_recomputes_after_the_build_it_joined_is_superseded(
    tmp_path, monkeypatch
):
    """Fix round 1, review finding C1 (Critical): a token-less caller (the
    staging path's own shape -- see app.py's start_run() work(), which
    never passes an interactive_token) that JOINS an in-flight
    INTERACTIVE build must not inherit that build's CutSuperseded when the
    interactive build is later cancelled. The spec's isolation clause
    promises a token-less build can never be cancelled by interactive
    supersession; before this fix, joining a build that later gets
    cancelled was exactly the path that promise did not hold on (the
    review's probe A reproduced it: "FAIL SPEC: a staging-shaped build
    completes despite supersession"). The token-less joiner must instead
    fall through and compute the cut itself once the joined build dies,
    completing with a real result.
    """
    import threading

    bundle, upload, studies = fake_export(tmp_path, monkeypatch)
    pieces = _studio_module("pieces")

    started = threading.Event()
    release = threading.Event()
    real_segment_pieces = pieces.segment_pieces
    calls = []

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        calls.append(1)
        mine = len(calls)
        if mine == 1:
            started.set()
            assert release.wait(timeout=5), "release was never set"
            if checkpoint is not None:
                checkpoint()  # raises CutSuperseded once released
        return real_segment_pieces(tess, surface, support_points, checkpoint=checkpoint)

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    key = ("Tiny", "bonded-courses", 0.9)
    outcomes = {}

    def call_interactive_builder():
        token = bundle.register_interactive("Tiny", key)
        try:
            outcomes["builder"] = bundle.build_bundle(
                "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=token)
        except Exception as error:
            outcomes["builder"] = error

    t_builder = threading.Thread(target=call_interactive_builder)
    t_builder.start()
    assert started.wait(timeout=5), "the interactive builder never started"

    def call_staging_joiner():
        # No interactive_token at all: the staging path's own shape.
        outcomes["joiner"] = bundle.build_bundle(
            "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=None)

    t_joiner = threading.Thread(target=call_staging_joiner)
    t_joiner.start()

    # A newer, DIFFERENT key for the same export: supersedes the
    # interactive builder (and, before this fix, the joiner too).
    bundle.register_interactive("Tiny", ("Tiny", "monolithic-bands", 1.2))
    release.set()
    t_builder.join(timeout=5)
    t_joiner.join(timeout=5)
    assert not t_builder.is_alive() and not t_joiner.is_alive()

    assert isinstance(outcomes["builder"], bundle.CutSuperseded), (
        "the interactive builder itself must still be superseded"
    )
    assert not isinstance(outcomes["joiner"], BaseException), (
        "a token-less joiner must not inherit the builder's "
        "CutSuperseded: {}".format(outcomes["joiner"])
    )
    assert outcomes["joiner"]["uncut_reason"] is None
    assert outcomes["joiner"]["pieces"], (
        "a token-less joiner must complete with a real result once the "
        "build it joined is superseded"
    )


def test_a_joiner_recomputes_after_a_reupload_clears_the_memo_mid_build(
    tmp_path, monkeypatch
):
    """Fix round 1, review finding C2 (Critical): a joiner must respect
    the same generation-counter protection the memo already has (see the
    module comment above _cut_memo, "a stale cut cannot outlive its
    export"). Before this fix, a request that arrived after a re-upload
    (which calls clear_cut_memo) could still JOIN a build that started
    BEFORE the clear, and build_bundle would then write a document
    combining that stale cut with the joiner's own, freshly loaded
    (post-clear) geometry to the disk cache -- the review's own probe B
    reproduced exactly this (analysis mesh at the new height, pieces cut
    at the old one, both written to disk). The joiner must instead notice
    the generation mismatch and recompute against the geometry its own
    caller actually loaded.
    """
    import threading

    bundle, upload, studies = fake_export(tmp_path, monkeypatch)
    pieces = _studio_module("pieces")

    started = threading.Event()
    release = threading.Event()
    real_segment_pieces = pieces.segment_pieces

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        started.set()
        assert release.wait(timeout=5), "release was never set"
        return real_segment_pieces(tess, surface, support_points, checkpoint=checkpoint)

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    results = {}

    def call_builder():
        results["builder"] = bundle.build_bundle(
            "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=None)

    t1 = threading.Thread(target=call_builder)
    t1.start()
    assert started.wait(timeout=5), "the builder never started"

    # A re-upload while the builder is still blocked mid-cut: new, taller
    # geometry (the centre vertex moves from z=1.0 to z=6.0), and the
    # clear_cut_memo it triggers (app._invalidate_studio_cache's own
    # call, reproduced directly here since this test drives bundle.py,
    # not the route).
    tall = tiny_contract()
    for vertex in tall["equilibrium"]["vertices"]:
        vertex["z"] = vertex.get("z", 0.0) + 5.0
    (upload / "Tiny-contract.json").write_text(json.dumps(tall), encoding="utf-8")
    bundle.clear_cut_memo()

    def call_joiner():
        results["joiner"] = bundle.build_bundle(
            "Tiny", "concrete", "bonded-courses", 0.9, interactive_token=None)

    t2 = threading.Thread(target=call_joiner)
    t2.start()

    release.set()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert not t1.is_alive() and not t2.is_alive(), "a thread never finished"

    def max_piece_z(document):
        return max(point[2] for piece in document["pieces"] for point in piece["mid"])

    assert max_piece_z(results["builder"]) < 2.0, (
        "the builder's own cut must reflect the OLD geometry it loaded"
    )
    assert max_piece_z(results["joiner"]) > 4.0, (
        "the joiner must recompute against the NEW geometry its own "
        "caller loaded, not adopt the pre-clear builder's stale cut"
    )

    cached_path = bundle.bundle_path("tiny", "concrete", "bonded-courses", 0.9, 0.2)
    on_disk = json.loads(cached_path.read_text(encoding="utf-8"))
    assert max_piece_z(on_disk) > 4.0, (
        "the disk cache must carry the post-upload geometry, not a "
        "mixed document built from the joiner's new mesh and the "
        "builder's stale, pre-clear cut"
    )
