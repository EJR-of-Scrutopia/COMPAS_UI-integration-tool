"""Acceptance: the real Armadillo export cuts natively (multi-loop, 2026-08-19).

Task 5 of the multi-loop cutting wave. Drives the REAL upload-to-bundle
path: app.py's PUT .../compas route, which calls derive_contract.
derive_contract on nothing but the mesh (see derive_contract.py's own
docstring) when no contract exists yet for the name; then GET .../bundle,
which routes through domain.plan_domain's openings.extract_loops/classify
and generators.generate's clip pass (see openings.py). Fixture: "bench/
demo/upload from grasshopper/Aramdillo style-compas.json", skip-guarded
exactly the way test_geometry.py's TRIAL_2 check is: skipped, not failed,
when the file is not on disk (untracked demo data, not committed to this
branch, present on the controller's machine when this task was written).

Measured on this export (2026-08-19, "concrete" material, "bonded-courses"
pattern -- geometry.py's own DEFAULT_PATTERN for concrete -- size 0.4 m,
studio.js's own slider default, bench/studio/static/studio.js:63): the
mesh is 801 vertices / 1481 triangular faces with FOUR boundary loops
(outer rim 93 vertices, two elevated oculi 11 vertices each, one
ground-level ring 10 vertices at z = 0); derive_contract infers 34
support vertices (boundary vertices within 1 mm of the mesh's own
z-minimum). The cut finds 3 openings (the outer rim is not one of them):
840 pieces over 14 courses, 47 cells fully inside an opening (dropped,
counted, never drawn), 82 cells clipped onto an opening's true boundary,
1 sliver clipped away and named (["c9p9"]), 0 clip failures. The binding
report's opening_regions carries exactly those 3 openings (points, plan
area, member cells per opening); coverage_holes is empty, so the three
openings are not double-counted as coverage defects. uncut_reason is
None: this plan does not hit any of the wave's named refusals (see
bundle.CutRefused's own docstring for the complete, current list). Cold
cut wall time on the controller's machine: about 3.4 seconds for the
upload-plus-bundle round trip (not asserted, not representative of a
warm cache or a different machine; recorded for the ledger only).
"""

from __future__ import annotations

from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ARMADILLO_COMPAS = (
    REPO / "bench" / "demo" / "upload from grasshopper"
    / "Aramdillo style-compas.json"
)


def _make_client(tmp_path, monkeypatch):
    """A studio app wired to an isolated upload/studies tree.

    Same monkeypatch idiom as test_app.py's own make_client (bundle.
    UPLOAD_DIR/STUDIES_DIR/RECORDINGS_DIR redirected to tmp_path, RUNS
    cleared), kept local to this file rather than imported so an
    acceptance test that skips on a missing fixture still collects on
    its own with no cross-file coupling.
    """

    import sys

    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import app as app_module
    import bundle

    upload = tmp_path / "upload"
    studies = tmp_path / "studies"
    upload.mkdir()
    studies.mkdir()
    monkeypatch.setattr(bundle, "UPLOAD_DIR", upload)
    monkeypatch.setattr(bundle, "STUDIES_DIR", studies)
    monkeypatch.setattr(bundle, "RECORDINGS_DIR", tmp_path / "recordings")
    app_module.RUNS.clear()
    return TestClient(app_module.create_app(
        runner=lambda request: {"converged": True, "message": ""},
        cra_runner=lambda request: {
            "stands": True, "status": "optimal", "message": "",
            "blocks": len(request["blocks"]), "interfaces": 1,
            "mu": request["mu"]},
    ))


def test_the_armadillo_cuts_natively_with_its_three_openings_respected(
    tmp_path, monkeypatch
):
    """Task 5 acceptance: see this module's own docstring for every
    measured number below and why each is what it is."""

    if not ARMADILLO_COMPAS.is_file():
        pytest.skip(
            "the Armadillo demo export is not on disk (untracked demo "
            "data, not committed to this branch); re-export the "
            "\"Aramdillo style\" thrust surface from Grasshopper to run "
            "this acceptance check")

    client = _make_client(tmp_path, monkeypatch)

    # The real path: a compas-only upload, no hand-authored contract, the
    # same "one file is enough" flow P4 shipped and test_app.py's own
    # test_compas_only_upload_derives_a_contract_and_the_study_builds
    # exercises on the tiny pyramid fixture. No contract exists yet in
    # this isolated upload dir, so app.py's upload route runs
    # derive_contract.derive_contract on the real thrustMesh for real.
    upload_response = client.put(
        "/api/uploads/exports/Armadillo/compas",
        content=ARMADILLO_COMPAS.read_bytes(),
    )
    assert upload_response.status_code == 200
    upload_body = upload_response.json()
    assert upload_body["derived_contract"] is True, upload_body
    assert upload_body["derivation_error"] is None
    assert upload_body["derived_support_count"] == 34

    bundle_response = client.get(
        "/api/studies/Armadillo/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 0.4},
    )
    assert bundle_response.status_code == 200
    document = bundle_response.json()

    # No CutRefused: the outer rim is star shaped and the axis sits clear
    # of every opening (see bundle.CutRefused's own docstring, updated
    # this task, for the complete list of what would have refused it).
    assert document["uncut_reason"] is None, document["uncut_reason"]

    pieces = document["pieces"]
    assert len(pieces) > 0
    assert len(pieces) == 840, "measured piece count drifted; see this module's docstring"

    tess = document["tessellation"]
    assert tess["courses"] == 14
    assert tess["openings"] == 3
    assert tess["cells_in_openings"] == 47
    assert len(tess["cells_clipped"]) == 82

    # Disclosed, not assumed on faith: the brief asks for this length to
    # be recorded honestly, asserted to zero only if it measures zero. It
    # measures zero on this real export.
    assert isinstance(tess["opening_clip_failures"], list)
    assert len(tess["opening_clip_failures"]) == 0
    assert tess["opening_slivers"] == ["c9p9"]

    report = tess["report"]
    opening_regions = report["opening_regions"]
    assert len(opening_regions) == 3
    # The three openings live in opening_regions, not coverage_holes: a
    # cut with real, deliberate openings must not read as a defective one.
    assert report["coverage_holes"] == []
    assert report["broken_boundary"] == []
    assert report["open_facets"] == []

    # Geometry only, honestly: derive_contract fabricates no forces.
    assert document["member_forces"] == []
    assert document["loads"] == {}
    assert document["reactions"] == {}
    assert document["provenance"]["derived_geometry_only"] is not None
