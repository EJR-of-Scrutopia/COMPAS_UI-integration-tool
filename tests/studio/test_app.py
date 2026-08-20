from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from conftest_data import tiny_contract

REPO = Path(__file__).resolve().parents[2]


def make_client(tmp_path, monkeypatch, runner=None):
    import sys

    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import app as app_module
    import bundle

    upload = tmp_path / "upload"
    studies = tmp_path / "studies"
    upload.mkdir(exist_ok=True)
    studies.mkdir(exist_ok=True)
    (upload / "Tiny-contract.json").write_text(
        json.dumps(tiny_contract()), encoding="utf-8"
    )
    (upload / "Tiny-compas.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(bundle, "UPLOAD_DIR", upload)
    monkeypatch.setattr(bundle, "STUDIES_DIR", studies)
    # Frames and stitched videos land outside the studies tree (and, in
    # production, outside the repo and OneDrive entirely) -- see
    # bundle.RECORDINGS_DIR's rationale.
    monkeypatch.setattr(bundle, "RECORDINGS_DIR", tmp_path / "recordings")
    app_module.RUNS.clear()
    if runner is None:
        runner = lambda request: {"converged": True, "message": ""}
    return TestClient(app_module.create_app(
        runner=runner,
        cra_runner=lambda request: {
            "stands": True, "status": "optimal", "message": "",
            "blocks": len(request["blocks"]), "interfaces": 1,
            "mu": request["mu"]},
    )), studies


def wait_for(client, run_id, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = client.get("/api/runs/{}".format(run_id)).json()
        if state["state"] in ("done", "failed"):
            return state
        time.sleep(0.05)
    raise AssertionError("run never finished: {}".format(state))


def bay_contract():
    """A 3x3 grid of unit quads with the (2, 1) face removed.

    The bay makes the plan genuinely not star shaped about its own axis --
    the same fixture shape as test_domain.py's grid(3, drop={(2, 1)}), here
    expressed as a full equilibrium/formGraph contract so it can drive the
    real bundle build. generators.generate refuses a plan like this, and
    that refusal has to reach the client as a 400, not a stack trace.
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
    axis. Same geometry as tests/studio/test_generators.py's own
    holed_paraboloid_domain() fixture (see that docstring for the
    measurement that the axis lands outside the hole), expressed as a
    full equilibrium/formGraph contract, bay_contract's own construction
    above, so it can drive the real bundle build end to end: multi-loop
    cutting's whole point is that a plan like this now cuts natively
    instead of refusing.
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


def authored_tiny_contract():
    """tiny_contract with an authored tessellation embedded in the contract
    itself, so build_bundle routes through tessellation.from_document
    instead of a generated pattern. An authored cut ignores the requested
    size entirely, so its target_size is None (see
    tessellation.build_tessellation).
    """
    contract = tiny_contract()
    contract["tessellation"] = {
        "schema": "bench.tessellation/1",
        "units": "m",
        "domain": "plan",
        "pattern": "authored",
        "cells": [
            {"key": "a", "course": 0,
             "outline": [[0, 0], [2, 0], [2, 2], [0, 2]]},
        ],
    }
    return contract


def test_studies_lists_the_export_and_ffmpeg_flag(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    payload = client.get("/api/studies").json()
    assert [s["export"] for s in payload["studies"]] == ["Tiny"]
    assert isinstance(payload["ffmpeg"], bool)


def test_bundle_endpoint_validates_and_serves(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    ok = client.get("/api/studies/Tiny/bundle", params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9})
    assert ok.status_code == 200
    assert ok.json()["slug"] == "tiny"
    missing = client.get("/api/studies/Nope/bundle", params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9})
    assert missing.status_code == 404
    assert "Tiny" in missing.json()["detail"]
    bad = client.get("/api/studies/Tiny/bundle",
                     params={"material": "adamantium", "pattern": "bonded-courses", "size": 0.9})
    assert bad.status_code == 400
    out_of_range = client.get("/api/studies/Tiny/bundle",
                              params={"material": "concrete", "pattern": "bonded-courses", "size": 9.0})
    assert out_of_range.status_code == 400


def test_a_plan_the_engine_refuses_ships_a_200_with_uncut_reason(tmp_path, monkeypatch):
    """A vault with a bay (re-entrant plan) is not star shaped, and no
    polar pattern can cover it. Before this wave no geometry could reach
    this failure at all, since the old ring/wedge binning worked on any
    centroid cloud; then, through the presentation-batch wave, get_bundle
    surfaced generators.generate's own message as a 400 rather than an
    unhandled 500.

    DELIBERATE CONTRACT CHANGE (P5, 2026-08-18): a 400 here meant an
    otherwise valid upload -- one that parsed, appeared in the study list
    and auto-selected -- loaded nothing at all, on the strength of a
    pre-existing, documented engine constraint (domain.py's own module
    docstring: the plan must be a single star-shaped loop) that this task
    does not relax. The engine's message still has to reach the client
    (that half of the old test's intent is unchanged, see the assertions
    below), but now as a 200 whose uncut_reason carries it, with the
    analysis mesh, provenance and empty pieces shipped alongside it, so an
    uncuttable study still loads and shows its form. See
    bundle.CutRefused for the exact mechanism and bundle.build_bundle for
    where it is caught.
    """
    client, _ = make_client(tmp_path, monkeypatch)
    upload = tmp_path / "upload"
    (upload / "Bay-contract.json").write_text(
        json.dumps(bay_contract()), encoding="utf-8"
    )
    (upload / "Bay-compas.json").write_text("{}", encoding="utf-8")
    response = client.get(
        "/api/studies/Bay/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9},
    )
    assert response.status_code == 200
    document = response.json()
    reason = document["uncut_reason"]
    assert reason
    assert "not star shaped" in reason
    assert "Author the tessellation in Grasshopper and import it instead" in reason
    assert document["pieces"] == []
    assert document["tessellation"] is None
    assert document["staging"] is None
    assert document["binding"] is None
    # The mesh and the contract's own fields are unaffected by the cut
    # refusing: they are read before the cut is ever attempted.
    assert document["analysis_mesh"]["faces"], "the analysis mesh still ships"
    assert document["pattern"] == "bonded-courses", (
        "no cut pattern exists, so the document falls back to the requested one"
    )


def test_a_holed_contract_cuts_natively_with_pieces(tmp_path, monkeypatch):
    """Multi-loop cutting's own point, proven at the app level: a plan
    with one star-shaped outer rim and an interior opening -- refused
    outright before this wave -- now cuts natively, drawn pieces and all,
    and the openings block rides the tessellation summary out to the
    client.
    """
    client, _ = make_client(tmp_path, monkeypatch)
    upload = tmp_path / "upload"
    (upload / "Holed-contract.json").write_text(
        json.dumps(holed_contract()), encoding="utf-8"
    )
    (upload / "Holed-compas.json").write_text("{}", encoding="utf-8")
    response = client.get(
        "/api/studies/Holed/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 1.0},
    )
    assert response.status_code == 200
    document = response.json()
    assert document["uncut_reason"] is None
    assert document["pieces"], "a native holed cut must ship drawn pieces"
    assert document["tessellation"] is not None
    assert document["tessellation"]["openings"] == 1


def test_an_authored_bundles_size_round_trips_through_the_api(tmp_path, monkeypatch):
    """Task 8 fix round 1, C1: an authored cut ignores the requested size,
    so tess["target_size"] is None. The bundle's top level "size" field
    used to echo tess["target_size"] straight through (0.0 before the
    tessellation.py sentinel fix, None after it), and applyCut copied that
    poisoned value into state.size client side. The very next reload
    (a material switch, a thickness commit, anything that calls loadStudy
    again) sent that value back to this endpoint and got a 400, with no
    way out except dragging the size slider by hand.

    The top level "size" must be the REQUESTED size instead, which this
    endpoint is guaranteed to accept back: that is the round trip this
    test drives for real, through two live requests, not just a range
    check on the first response.
    """
    client, studies = make_client(tmp_path, monkeypatch)
    upload = tmp_path / "upload"
    (upload / "Authored-contract.json").write_text(
        json.dumps(authored_tiny_contract()), encoding="utf-8"
    )
    (upload / "Authored-compas.json").write_text("{}", encoding="utf-8")

    first = client.get(
        "/api/studies/Authored/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9},
    )
    assert first.status_code == 200, first.json()
    document = first.json()
    assert document["tessellation"]["source"] == "imported"
    # The cut's own honest record: it truly has no target size, not one of
    # zero metres.
    assert document["tessellation"]["target_size"] is None
    round_tripped_size = document["size"]
    assert round_tripped_size == 0.9, (
        "the top level size must be the REQUESTED size, not the cut's own "
        "target_size"
    )

    second = client.get(
        "/api/studies/Authored/bundle",
        params={
            "material": "concrete", "pattern": "bonded-courses",
            "size": round_tripped_size,
        },
    )
    assert second.status_code == 200, (
        "the value the first response reported as the bundle's own size "
        "must be a value this same endpoint accepts back: {}".format(
            second.json() if second.headers.get("content-type", "").startswith(
                "application/json") else second.status_code
        )
    )


def test_run_lifecycle_reaches_done_and_embeds_staging(tmp_path, monkeypatch):
    client, studies = make_client(tmp_path, monkeypatch)
    started = client.post("/api/runs", json={"export": "Tiny", "material": "concrete",
                                    "pattern": "bonded-courses", "size": 0.9})
    assert started.status_code == 202
    run_id = started.json()["run"]
    state = wait_for(client, run_id)
    assert state["state"] == "done", state["message"]
    assert (
        studies / "tiny" / "studio"
        / "staging-concrete-bonded-courses-s900-t200.json"
    ).is_file()
    document = client.get(
        "/api/studies/Tiny/bundle", params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9}
    ).json()
    assert document["staging"] is not None
    # Tiny (see conftest_data.tiny_contract) is small enough that at this
    # target size the whole plan is one course: see
    # tests/studio/test_staging.py for the pinned contract.
    assert len(document["staging"]["stages"]) == 1
    assert document["staging"]["size"] == 0.9


def test_bundle_url_is_percent_encoded_for_spaced_export_names(tmp_path, monkeypatch):
    """bundle_url must URL-encode the export path segment.

    'Trial 2' is a real export name in this repo; every spaced export must
    not leak a literal space into bundle_url, since that contradicts the
    documented output format ('Trial%202') and breaks naive URL joining on
    the client. This proves the encoding round-trips: the encoded bundle_url
    actually resolves through the same TestClient.
    """
    client, studies = make_client(tmp_path, monkeypatch)
    upload = tmp_path / "upload"
    (upload / "Tiny Two-contract.json").write_text(
        json.dumps(tiny_contract()), encoding="utf-8"
    )
    (upload / "Tiny Two-compas.json").write_text("{}", encoding="utf-8")

    started = client.post(
        "/api/runs", json={"export": "Tiny Two", "material": "concrete",
                            "pattern": "bonded-courses", "size": 0.9}
    )
    assert started.status_code == 202
    state = wait_for(client, started.json()["run"])
    assert state["state"] == "done", state["message"]

    bundle_url = state["bundle_url"]
    assert "Tiny%20Two" in bundle_url
    assert " " not in bundle_url

    round_trip = client.get(bundle_url)
    assert round_trip.status_code == 200


def test_second_run_on_the_same_export_is_409(tmp_path, monkeypatch):
    import threading

    release = threading.Event()

    def slow_runner(request):
        release.wait(timeout=5)
        return {"converged": True, "message": ""}

    client, _ = make_client(tmp_path, monkeypatch, runner=slow_runner)
    first = client.post("/api/runs", json={"export": "Tiny", "material": "concrete",
                                    "pattern": "bonded-courses", "size": 0.9})
    assert first.status_code == 202
    second = client.post("/api/runs", json={"export": "Tiny", "material": "timber",
                                    "pattern": "bonded-courses", "size": 0.9})
    assert second.status_code == 409
    assert second.json()["run"] == first.json()["run"]
    release.set()
    wait_for(client, first.json()["run"])


def test_failed_staging_reports_failed_not_stuck(tmp_path, monkeypatch):
    def broken_runner(request):
        raise RuntimeError("the fea venv is on fire")

    client, _ = make_client(tmp_path, monkeypatch, runner=broken_runner)
    started = client.post("/api/runs", json={"export": "Tiny", "material": "concrete",
                                    "pattern": "bonded-courses", "size": 0.9})
    state = wait_for(client, started.json()["run"])
    assert state["state"] == "failed"
    assert "on fire" in state["message"]


def test_frames_and_stitch_guardrails(tmp_path, monkeypatch):
    client, studies = make_client(tmp_path, monkeypatch)
    started = client.post("/api/runs", json={"export": "Tiny", "material": "concrete",
                                    "pattern": "bonded-courses", "size": 0.9})
    run_id = started.json()["run"]
    wait_for(client, run_id)
    posted = client.post(
        "/api/frames/{}?frame=1".format(run_id),
        content=b"\x89PNG fake bytes",
        headers={"content-type": "application/octet-stream"},
    )
    assert posted.status_code == 200
    assert (tmp_path / "recordings" / "tiny" / "frames" / "frame-000001.png").is_file()
    assert not (studies / "tiny" / "studio" / "frames").exists(), (
        "frames must not land inside the studies tree (OneDrive sync scope)"
    )
    assert client.post("/api/frames/nonsense?frame=1", content=b"x").status_code == 404


def test_posting_frame_one_clears_stale_frames_from_a_previous_recording(tmp_path, monkeypatch):
    """A shorter second recording must not inherit the first take's tail.

    frame-%06d.png accumulates in the same directory across recordings; if
    frame 1 does not clear it, a longer first take leaves frame-000047.png
    etc. behind, and ffmpeg silently stitches that stale tail into the new,
    shorter video. Posting frame 1 again is the recording-restart signal.
    """
    client, studies = make_client(tmp_path, monkeypatch)
    started = client.post("/api/runs", json={"export": "Tiny", "material": "concrete",
                                    "pattern": "bonded-courses", "size": 0.9})
    run_id = started.json()["run"]
    wait_for(client, run_id)
    frames = tmp_path / "recordings" / "tiny" / "frames"

    for frame in (1, 2, 3):
        response = client.post(
            "/api/frames/{}?frame={}".format(run_id, frame),
            content="first take frame {}".format(frame).encode("utf-8"),
            headers={"content-type": "application/octet-stream"},
        )
        assert response.status_code == 200
    assert sorted(p.name for p in frames.glob("frame-*.png")) == [
        "frame-000001.png", "frame-000002.png", "frame-000003.png",
    ]

    second_take = client.post(
        "/api/frames/{}?frame=1".format(run_id),
        content=b"second take frame 1",
        headers={"content-type": "application/octet-stream"},
    )
    assert second_take.status_code == 200
    assert sorted(p.name for p in frames.glob("frame-*.png")) == ["frame-000001.png"]
    assert (frames / "frame-000001.png").read_bytes() == b"second take frame 1"

    # Stitch-guard behaviour is unchanged: still 404s with no frames, still
    # refuses when ffmpeg is missing, still stitches when both are present.
    assert client.post("/api/frames/nonsense/stitch").status_code == 404


def test_frames_accept_a_study_slug_without_a_run(tmp_path, monkeypatch):
    client, studies = make_client(tmp_path, monkeypatch)
    client.get("/api/studies/Tiny/bundle", params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9})
    posted = client.post(
        "/api/frames/study-tiny?frame=3",
        content=b"png bytes",
        headers={"content-type": "application/octet-stream"},
    )
    assert posted.status_code == 200
    assert (tmp_path / "recordings" / "tiny" / "frames" / "frame-000003.png").is_file()
    assert client.post("/api/frames/study-nope?frame=1", content=b"x").status_code == 404
    # Path traversal in the slug must never resolve outside STUDIES_DIR. Either
    # the router rejects the encoded slash before frames_dir ever runs, or
    # frames_dir's own "/", "\\", ".." guard catches it first; both land as
    # 400 or 404, and either is acceptable as long as the guard exists.
    traversal_encoded = client.post("/api/frames/study-..%2F..?frame=1", content=b"x")
    assert traversal_encoded.status_code in (400, 404)
    traversal_plain = client.post("/api/frames/study-..?frame=1", content=b"x")
    assert traversal_plain.status_code in (400, 404)


def test_thickness_is_validated_and_reaches_the_bundle(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    ok = client.get("/api/studies/Tiny/bundle",
                    params={"material": "concrete", "pattern": "bonded-courses",
                            "size": 0.9, "thickness": 0.3})
    assert ok.status_code == 200
    assert ok.json()["provenance"]["thickness"] == 0.3
    bad = client.get("/api/studies/Tiny/bundle",
                     params={"material": "concrete", "pattern": "bonded-courses",
                             "size": 0.9, "thickness": 0.9})
    assert bad.status_code == 400
    run = client.post("/api/runs", json={
        "export": "Tiny", "material": "concrete", "pattern": "bonded-courses",
        "size": 0.9, "thickness": 0.3})
    assert run.status_code == 202
    state = wait_for(client, run.json()["run"])
    assert state["state"] == "done", state["message"]
    assert "thickness=0.3" in state["bundle_url"]


def test_column_files_are_listed_and_path_traversal_is_rejected(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    import app as app_module

    columns = tmp_path / "columns"
    columns.mkdir()
    (columns / "piers.json").write_text('{"vertices": [], "faces": []}', encoding="utf-8")
    monkeypatch.setattr(app_module, "COLUMNS_DIR", columns)
    assert client.get("/api/studies").json()["columns"] == ["piers.json"]
    assert client.get("/api/columns/piers.json").status_code == 200
    assert client.get("/api/columns/..%2Fsecrets.json").status_code in (400, 404)


def test_export_upload_stores_a_valid_pair_and_lists_it(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    body = json.dumps(tiny_contract()).encode()
    first = client.put("/api/uploads/exports/Fresh/contract", content=body)
    assert first.status_code == 200
    assert first.json()["pair_complete"] is False
    second = client.put("/api/uploads/exports/Fresh/compas",
                        content=b'{"thrustMesh": "{}"}')
    assert second.json()["pair_complete"] is True
    exports = [s["export"] for s in client.get("/api/studies").json()["studies"]]
    assert "Fresh" in exports


def _pyramid_compas_document():
    fixture = Path(__file__).resolve().parent / "fixtures" / "tiny-pyramid-compas.json"
    return json.loads(fixture.read_text(encoding="utf-8"))


def test_compas_only_upload_derives_a_contract_and_the_study_builds(tmp_path, monkeypatch):
    """P4 (presentation batch, 2026-08-18): Param's ask -- upload just the
    compas half, no hand-authored contract, and the study still works end
    to end, forces/loads/reactions honestly empty rather than fabricated."""

    client, _ = make_client(tmp_path, monkeypatch)
    response = client.put(
        "/api/uploads/exports/Pyramid/compas",
        content=json.dumps(_pyramid_compas_document()).encode(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pair_complete"] is True
    assert body["derived_contract"] is True
    assert body["derived_support_count"] == 4
    assert body["derivation_error"] is None

    exports = [s["export"] for s in client.get("/api/studies").json()["studies"]]
    assert "Pyramid" in exports

    bundle_response = client.get(
        "/api/studies/Pyramid/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 0.5},
    )
    assert bundle_response.status_code == 200
    document = bundle_response.json()
    assert len(document["pieces"]) > 0
    # Honest degradation: no contract carried analysis, so none is
    # fabricated -- the existing layer-availability machinery (studio.js)
    # already reads exactly these empty shapes to disable the forces/
    # reactions layers, unchanged by this task.
    assert document["member_forces"] == []
    assert document["loads"] == {}
    assert document["reactions"] == {}
    assert document["provenance"]["derived_geometry_only"] is not None
    assert "no analysis in this export" in document["provenance"]["derived_geometry_only"]


def test_the_index_stamps_the_studio_script_url(tmp_path, monkeypatch):
    """Revalidation headers alone were not enough: Chromium's heuristic
    cache served a stale module script across plain refreshes (2026-08-18,
    live, twice). The index rewrites the script URL with studio.js's own
    mtime, so fresh HTML always names a URL the browser never cached."""

    import re as re_module
    client, _ = make_client(tmp_path, monkeypatch)
    html = client.get("/").text
    assert "/static/studio.js?v=dev" not in html, (
        "the dev placeholder must be stamped, never served"
    )
    assert re_module.search(r"/static/studio\.js\?v=\d+", html)


def test_static_files_and_the_index_ask_the_browser_to_revalidate(tmp_path, monkeypatch):
    """A plain refresh after a server update once served the new
    index.html with the OLD cached studio.js (2026-08-18, live). no-cache
    means revalidate, not no caching: unchanged files still answer 304."""

    client, _ = make_client(tmp_path, monkeypatch)
    for path in ("/", "/static/studio.js"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers.get("cache-control") == "no-cache"
    api = client.get("/api/studies")
    assert api.headers.get("cache-control") != "no-cache"


def _tiny_tessellation_document():
    return {
        "schema": "bench.tessellation/1",
        "units": "m",
        "domain": "plan",
        "pattern": "authored",
        "cells": [
            {"key": "a", "course": 0,
             "outline": [[0, 0], [2, 0], [2, 2], [0, 2]]},
        ],
    }


def test_a_tessellation_upload_gives_the_study_an_authored_cut(tmp_path, monkeypatch):
    """2026-08-18: the plugin Export component writes the
    bench.tessellation/1 sidecar, and the studio's import accepts it as a
    third kind. Uploading it for an existing export stores the sidecar
    under exactly the name bundle.tessellation_sidecar pairs on, and the
    next bundle cuts from the authored cells instead of a generated
    pattern."""

    client, _ = make_client(tmp_path, monkeypatch)
    response = client.put(
        "/api/uploads/exports/Tiny/tessellation",
        content=json.dumps(_tiny_tessellation_document()).encode(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["stored"] == "Tiny-tessellation.json"
    assert body["authored_tessellation"] == "Tiny-tessellation.json"
    assert (tmp_path / "upload" / "Tiny-tessellation.json").is_file()

    bundle_response = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9},
    )
    assert bundle_response.status_code == 200
    document = bundle_response.json()
    assert len(document["pieces"]) == 1, (
        "one authored cell must mean exactly one piece: the generated "
        "pattern would have cut more"
    )
    assert document["pieces"][0]["key"] == "a"


def test_a_tessellation_upload_for_a_missing_export_is_a_400(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    response = client.put(
        "/api/uploads/exports/Nope/tessellation",
        content=json.dumps(_tiny_tessellation_document()).encode(),
    )
    assert response.status_code == 400
    assert "upload its form export first" in response.json()["detail"]


def test_a_tessellation_upload_without_cells_is_a_400(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    for bad in ({"schema": "bench.tessellation/1"},
                {"schema": "bench.tessellation/1", "cells": []},
                {"schema": "wrong/1", "cells": [{"key": "a"}]}):
        response = client.put(
            "/api/uploads/exports/Tiny/tessellation",
            content=json.dumps(bad).encode(),
        )
        assert response.status_code == 400


def test_compas_upload_never_shadows_an_existing_contract(tmp_path, monkeypatch):
    """The derived-contract write must never run while a contract already
    exists for this name -- real or a prior derivation -- or a compas
    re-upload could silently clobber a hand-authored analysis contract."""

    client, _ = make_client(tmp_path, monkeypatch)
    upload_dir = tmp_path / "upload"
    before = (upload_dir / "Tiny-contract.json").read_text(encoding="utf-8")

    response = client.put(
        "/api/uploads/exports/Tiny/compas",
        content=json.dumps(_pyramid_compas_document()).encode(),
    )
    assert response.status_code == 200
    assert response.json()["derived_contract"] is False
    assert response.json()["derived_support_count"] is None

    after = (upload_dir / "Tiny-contract.json").read_text(encoding="utf-8")
    assert before == after, "Tiny's real contract must survive a later compas upload untouched"


def test_compas_upload_with_unreadable_thrust_mesh_stores_but_does_not_derive(tmp_path, monkeypatch):
    """A malformed thrustMesh must not fail the compas upload outright (the
    file is stored exactly as it always was, pre-P4) -- only the derivation
    step is skipped, and named in the response rather than silently
    dropped."""

    client, _ = make_client(tmp_path, monkeypatch)
    response = client.put(
        "/api/uploads/exports/Broken/compas",
        content=b'{"thrustMesh": "not json"}',
    )
    assert response.status_code == 200
    body = response.json()
    assert body["derived_contract"] is False
    assert body["derivation_error"] is not None
    assert "not valid JSON" in body["derivation_error"]
    assert body["pair_complete"] is False
    exports = [s["export"] for s in client.get("/api/studies").json()["studies"]]
    assert "Broken" not in exports


def test_export_upload_rejects_garbage_and_traversal(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    assert client.put("/api/uploads/exports/Bad/contract",
                      content=b"not json").status_code == 400
    assert client.put("/api/uploads/exports/Bad/contract",
                      content=b'{"no": "equilibrium"}').status_code == 400
    assert client.put("/api/uploads/exports/../evil/contract",
                      content=b"{}").status_code in (400, 404)
    assert client.put("/api/uploads/exports/Bad/nonsense",
                      content=b"{}").status_code == 400
    listed = [s["export"] for s in client.get("/api/studies").json()["studies"]]
    assert "Bad" not in listed


def test_reupload_with_changed_geometry_invalidates_bundle_and_staging_caches(tmp_path, monkeypatch):
    """C1: re-importing changed geometry under the same name must not keep
    serving the old cached bundle. GET a bundle (which caches it), run a
    staging pass (which caches that too), then re-upload the contract with
    a moved vertex; both caches must be gone, frames/recording must survive,
    and a fresh GET must show the new geometry."""
    client, studies = make_client(tmp_path, monkeypatch)
    started = client.post("/api/runs", json={"export": "Tiny", "material": "concrete",
                                    "pattern": "bonded-courses", "size": 0.9})
    wait_for(client, started.json()["run"])

    studio_dir = studies / "tiny" / "studio"
    bundle_cache = studio_dir / "bundle-concrete-bonded-courses-s900-t200.json"
    staging_cache = studio_dir / "staging-concrete-bonded-courses-s900-t200.json"
    assert bundle_cache.is_file()
    assert staging_cache.is_file()

    frames_dir = studio_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    (frames_dir / "frame-000001.png").write_bytes(b"kept")
    (studio_dir / "recording.mp4").write_bytes(b"kept")

    contract = tiny_contract()
    contract["equilibrium"]["vertices"][0]["z"] = 9.0
    reupload = client.put(
        "/api/uploads/exports/Tiny/contract", content=json.dumps(contract).encode()
    )
    assert reupload.status_code == 200

    assert not bundle_cache.is_file()
    assert not staging_cache.is_file()
    assert (frames_dir / "frame-000001.png").is_file()
    assert (studio_dir / "recording.mp4").is_file()

    fresh = client.get(
        "/api/studies/Tiny/bundle", params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9}
    )
    assert fresh.status_code == 200
    assert fresh.json()["analysis_mesh"]["vertices"][0][2] == 9.0


def test_upload_during_a_live_run_is_409(tmp_path, monkeypatch):
    """I1: uploading over an export name with a queued or running run must
    409 with the live run's id, mirroring start_run's own liveness check."""
    import threading

    release = threading.Event()

    def slow_runner(request):
        release.wait(timeout=5)
        return {"converged": True, "message": ""}

    client, _ = make_client(tmp_path, monkeypatch, runner=slow_runner)
    started = client.post("/api/runs", json={"export": "Tiny", "material": "concrete",
                                    "pattern": "bonded-courses", "size": 0.9})
    assert started.status_code == 202
    run_id = started.json()["run"]

    upload = client.put(
        "/api/uploads/exports/Tiny/contract", content=json.dumps(tiny_contract()).encode()
    )
    assert upload.status_code == 409
    assert upload.json()["run"] == run_id

    release.set()
    state = wait_for(client, run_id)
    assert state["state"] == "done", state["message"]


def test_export_upload_rejects_member_forces_edge_count_mismatch(tmp_path, monkeypatch):
    """I2: a contract-mode upload with memberForces that do not line up
    one-to-one with edges must be rejected 400, naming the mismatch, instead
    of importing green and 500ing on every subsequent view."""
    client, _ = make_client(tmp_path, monkeypatch)
    contract = tiny_contract()
    assert len(contract["equilibrium"]["edges"]) == 12
    contract["equilibrium"]["memberForces"] = [-2.0] * 5
    response = client.put(
        "/api/uploads/exports/Mismatch/contract", content=json.dumps(contract).encode()
    )
    assert response.status_code == 400
    assert "5" in response.json()["detail"]
    assert not (tmp_path / "upload" / "Mismatch-contract.json").is_file()
    listed = [s["export"] for s in client.get("/api/studies").json()["studies"]]
    assert "Mismatch" not in listed


def test_columns_upload_validates_shape(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    import app as app_module

    columns = tmp_path / "columns"
    columns.mkdir()
    monkeypatch.setattr(app_module, "COLUMNS_DIR", columns)
    good = client.put("/api/uploads/columns/piers.json",
                      content=b'{"vertices": [[0,0,0]], "faces": [[0,0,0]]}')
    assert good.status_code == 200
    assert (columns / "piers.json").is_file()
    assert client.put("/api/uploads/columns/junk.json",
                      content=b'{"nope": 1}').status_code == 400
    assert client.put("/api/uploads/columns/..%2Fx.json",
                      content=b"{}").status_code in (400, 404)


def test_size_out_of_range_is_rejected_by_name(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    response = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses",
                "size": 9.0, "thickness": 0.2},
    )
    assert response.status_code == 400
    assert "0.15" in response.json()["detail"]


def test_an_unknown_pattern_is_rejected_by_name(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    response = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "herringbone",
                "size": 0.9, "thickness": 0.2},
    )
    assert response.status_code == 400
    assert "bonded-courses" in response.json()["detail"]


def test_studies_lists_patterns_and_their_defaults(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    payload = client.get("/api/studies").json()
    assert "bonded-courses" in payload["patterns"]
    assert payload["pattern_defaults"]["concrete-sprayed"] == "monolithic-bands"
    assert "guastavino-herringbone" in payload["patterns_planned"]


def test_a_malformed_authored_tessellation_is_a_400_naming_the_cell(
    tmp_path, monkeypatch
):
    """The 400 contract must hold for a wrong container type too.

    from_document validated values by name but never the shape of the JSON
    it was handed, so a wrong container escaped as a bare AttributeError
    or TypeError. get_bundle catches only ValueError, and rightly so, so
    each of these answered 500 with no detail body: a Grasshopper author
    got neither the cell key nor which file to open, on the one route this
    whole feature is built around. The bad-units case is the control: that
    contract has always been kept.
    """
    client, _ = make_client(tmp_path, monkeypatch)
    upload = tmp_path / "upload"
    (upload / "Bad-compas.json").write_text("{}", encoding="utf-8")
    base = {
        "schema": "bench.tessellation/1", "units": "m", "domain": "plan",
        "pattern": "authored",
    }
    square = [[0, 0], [2, 0], [2, 2], [0, 2]]
    cases = [
        ("bad units, the control",
         dict(base, units="mm", cells=[{"key": "a", "course": 0,
                                        "outline": square}]), "mm"),
        ("a bare string among the cells", dict(base, cells=["oops"]), "cell 0"),
        ("a non-list outline",
         dict(base, cells=[{"key": "a", "course": 0, "outline": 7}]), "a"),
        ("non-list holes",
         dict(base, cells=[{"key": "a", "course": 0, "outline": square,
                            "holes": 5}]), "a"),
        ("a negative course",
         dict(base, cells=[{"key": "sunk", "course": -1,
                            "outline": square}]), "sunk"),
    ]
    for label, tess, expected in cases:
        contract = tiny_contract()
        contract["tessellation"] = tess
        (upload / "Bad-contract.json").write_text(
            json.dumps(contract), encoding="utf-8"
        )
        for stale in (tmp_path / "studies").glob("bad/studio/*.json"):
            stale.unlink()
        response = client.get(
            "/api/studies/Bad/bundle",
            params={"material": "concrete", "pattern": "bonded-courses",
                    "size": 0.9},
        )
        assert response.status_code == 400, "{}: got {} {!r}".format(
            label, response.status_code, response.text[:200])
        assert expected in response.json()["detail"], "{}: {}".format(
            label, response.json()["detail"])


def test_a_non_numeric_size_or_thickness_is_a_400_not_a_500(tmp_path, monkeypatch):
    """POST /api/runs coerced with float() before _validate ever ran.

    A missing size correctly gave 400 (float(0.0) then the range check),
    but a size the client typed as text and a null thickness both raised
    out of the coercion itself and answered 500. The body is a request
    the user can fix, so it is a 400 that says which field.
    """
    client, _ = make_client(tmp_path, monkeypatch)
    for body, expected in (
        ({"export": "Tiny", "material": "concrete",
          "pattern": "bonded-courses", "size": "abc"}, "size"),
        ({"export": "Tiny", "material": "concrete",
          "pattern": "bonded-courses", "size": 0.9, "thickness": None},
         "thickness"),
    ):
        response = client.post("/api/runs", json=body)
        assert response.status_code == 400, "{} gave {} {!r}".format(
            body, response.status_code, response.text[:200])
        assert expected in response.json()["detail"]
    # The range check still owns a number that is merely out of bounds.
    out_of_range = client.post("/api/runs", json={
        "export": "Tiny", "material": "concrete",
        "pattern": "bonded-courses", "size": 99.0})
    assert out_of_range.status_code == 400
    assert "between" in out_of_range.json()["detail"]


def test_a_run_reports_the_stage_count_and_says_what_it_is_doing(
    tmp_path, monkeypatch
):
    """run["of"] is 0 until the cut is known, which is the slow part.

    The count of stages comes from the cut, so it cannot be known when the
    run is created; what the server can do is say which phase it is in
    rather than leaving the reader with a bare "0/0". The run carries a
    phase from the moment it starts, and "of" is filled in the moment the
    first stage begins.
    """
    client, _ = make_client(tmp_path, monkeypatch)
    started = client.post("/api/runs", json={
        "export": "Tiny", "material": "concrete",
        "pattern": "bonded-courses", "size": 0.9})
    run_id = started.json()["run"]
    state = wait_for(client, run_id)
    assert state["state"] == "done", state
    assert state["of"] >= 1, "the stage count must be filled in once known"
    assert state["stage"] == state["of"]
    assert state["phase"] == "done"


def test_a_reupload_reports_the_authored_sidecar_that_will_keep_winning(
    tmp_path, monkeypatch
):
    """A sidecar survives a re-upload and keeps overriding the new cut.

    _invalidate_studio_cache drops bundle-*.json and staging-*.json, so a
    re-upload does force a re-cut, but the re-cut still reads the sidecar
    authored for the PREVIOUS geometry and quietly wins with it. Deleting
    the author's file here would be wrong; going silent about it is what
    was wrong. The route names it.
    """
    client, _ = make_client(tmp_path, monkeypatch)
    import bundle

    plain = client.put(
        "/api/uploads/exports/Tiny/contract",
        content=json.dumps(tiny_contract()).encode(),
    )
    assert plain.status_code == 200
    assert plain.json()["authored_tessellation"] is None

    bundle.tessellation_sidecar("Tiny").write_text(
        json.dumps({"schema": "bench.tessellation/1"}), encoding="utf-8"
    )
    again = client.put(
        "/api/uploads/exports/Tiny/contract",
        content=json.dumps(tiny_contract()).encode(),
    )
    assert again.status_code == 200
    assert again.json()["authored_tessellation"] == "Tiny-tessellation.json"


def test_hdri_list_upload_and_fetch(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    import app as app_module

    monkeypatch.setattr(app_module, "HDRI_DIR", tmp_path / "hdri")
    assert client.get("/api/hdri").json() == {"files": []}
    body = b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n\x00\x00\x00\x00"
    response = client.put("/api/uploads/hdri/studio.hdr", content=body)
    assert response.status_code == 200
    assert response.json() == {"stored": "studio.hdr"}
    assert client.get("/api/hdri").json() == {"files": ["studio.hdr"]}
    fetched = client.get("/api/hdri/studio.hdr")
    assert fetched.status_code == 200
    assert fetched.content == body


def test_hdri_upload_rejections(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    import app as app_module

    monkeypatch.setattr(app_module, "HDRI_DIR", tmp_path / "hdri")
    wrong_ext = client.put("/api/uploads/hdri/notes.txt", content=b"#?RADIANCE")
    assert wrong_ext.status_code == 400
    wrong_magic = client.put("/api/uploads/hdri/fake.hdr", content=b"not radiance")
    assert wrong_magic.status_code == 400
    assert client.get("/api/hdri/missing.hdr").status_code == 404
    traversal = client.get("/api/hdri/..%5Capp.py")
    assert traversal.status_code in (400, 404)
    traversal_put = client.put(
        "/api/uploads/hdri/..%5Cevil.hdr", content=b"#?RADIANCE")
    assert traversal_put.status_code in (400, 404)
    assert not (tmp_path / "hdri").exists() or not list((tmp_path / "hdri").glob("*evil*"))
    assert not (tmp_path / "hdri" / "notes.txt").exists()
    assert not (tmp_path / "hdri" / "fake.hdr").exists()


def test_windows_drive_relative_names_cannot_escape(tmp_path, monkeypatch):
    """Task 5, defect table report 6/7 hardening: a Windows drive-relative
    name like 'C:evil.hdr' is not caught by a plain '/'/'\\'/'..' character
    guard, and Path's own join can replace the base directory entirely for
    such names. _contained() closes this on the hdri GET, hdri PUT and
    columns PUT routes."""
    client, _ = make_client(tmp_path, monkeypatch)
    import app as app_module

    monkeypatch.setattr(app_module, "HDRI_DIR", tmp_path / "hdri")
    body = b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n\x00\x00\x00\x00"
    assert client.put("/api/uploads/hdri/C:evil.hdr", content=body).status_code == 400
    # _contained() rejects the drive-relative name before any lookup runs,
    # so this is a guard failure every time, not a "maybe it 404s instead"
    # depending on what happens to sit at the resolved path.
    assert client.get("/api/hdri/C:app.py").status_code == 400
    assert not list(tmp_path.rglob("*evil*")), (
        "no file named for the drive-relative payload may exist anywhere "
        "under tmp_path"
    )
    assert client.put(
        "/api/uploads/columns/C:evil.json", content=b"{}").status_code == 400


def test_hdri_same_name_reupload_overwrites(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    import app as app_module

    monkeypatch.setattr(app_module, "HDRI_DIR", tmp_path / "hdri")
    head = b"#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 1\n"
    assert client.put("/api/uploads/hdri/a.hdr", content=head + b"\x01\x01\x01\x01").status_code == 200
    assert client.put("/api/uploads/hdri/a.hdr", content=head + b"\x02\x02\x02\x02").status_code == 200
    assert (tmp_path / "hdri" / "a.hdr").read_bytes().endswith(b"\x02\x02\x02\x02")


def test_export_reupload_serves_new_geometry(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)

    first = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses",
                "size": 0.9, "thickness": 0.2},
    )
    assert first.status_code == 200
    tall = tiny_contract()
    # tiny_contract's vertices are a LIST of {"x", "y", "z"} dicts (see
    # conftest_data.tiny_contract), not a mapping keyed by id.
    for vertex in tall["equilibrium"]["vertices"]:
        vertex["z"] = vertex.get("z", 0.0) + 1.2
    put = client.put(
        "/api/uploads/exports/Tiny/contract", content=json.dumps(tall).encode())
    assert put.status_code == 200
    second = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses",
                "size": 0.9, "thickness": 0.2},
    )
    assert second.status_code == 200
    assert first.content != second.content, "a re-upload must serve the new geometry"


def test_a_slow_build_superseded_by_a_newer_different_key_request_409s(tmp_path, monkeypatch):
    """(b) Cut cancellation, task 2 acceptance bar, end to end through the
    route: a slow interactive build blocked mid-cut is superseded when a
    newer request for a DIFFERENT key registers for the same export. The
    slow build's own checkpoint raises bundle.CutSuperseded once released,
    the route answers 409 {"superseded": true}, nothing is memoised or
    written to disk for the slow build's own key, and the newer request
    completes normally.

    Deterministic via Event handshakes, not sleeps: the fake segment_
    pieces distinguishes "the first call" (the slow one, which blocks and
    then checks its own checkpoint) from every later call (which passes
    straight through to the real implementation) by a call counter, not
    by inspecting which key is being cut -- the newer request's own
    thread only starts once "started" proves the slow build has already
    registered itself, so no sleep is needed to avoid a race.
    """
    import threading

    client, studies = make_client(tmp_path, monkeypatch)
    import bundle
    import pieces

    started = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}
    count_lock = threading.Lock()
    real_segment_pieces = pieces.segment_pieces

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        with count_lock:
            call_count["n"] += 1
            mine = call_count["n"]
        if mine == 1:
            started.set()
            assert release.wait(timeout=5), "release was never set"
            if checkpoint is not None:
                checkpoint()
        return real_segment_pieces(tess, surface, support_points, checkpoint=checkpoint)

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    responses = {}

    def call_first():
        responses["first"] = client.get(
            "/api/studies/Tiny/bundle",
            params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9},
        )

    t1 = threading.Thread(target=call_first)
    t1.start()
    assert started.wait(timeout=5), "the slow build never started"

    # A newer interactive request for a DIFFERENT key (a different size)
    # on the same export.
    second = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 1.2},
    )
    assert second.status_code == 200, second.text

    release.set()
    t1.join(timeout=5)
    assert not t1.is_alive(), "the slow build's own request never finished"

    assert responses["first"].status_code == 409
    assert responses["first"].json() == {"superseded": True}
    assert call_count["n"] == 2, "exactly two cuts: the slow one and the newer one"

    key = ("Tiny", "bonded-courses", 0.9)
    assert key not in bundle._cut_memo, "a superseded build must not be memoised"
    assert not bundle.bundle_path(
        "tiny", "concrete", "bonded-courses", 0.9, 0.2
    ).is_file(), "a superseded build must write nothing to disk"


def test_a_cache_hit_for_a_different_key_still_supersedes_an_in_flight_build(
    tmp_path, monkeypatch
):
    """Review finding I5 (Important, fix round 2, 2026-08-19): the whole
    justification for register_interactive taking a KEY argument (a
    deviation from the task brief's own one-arg register_interactive(
    export) shorthand, see the task-2 report's own reasoning) is a single
    claim -- a request served STRAIGHT FROM THE ON-DISK CACHE, which never
    reaches _cut_for, never builds a checkpoint, and never calls
    segment_pieces at all, must still supersede an older in-flight build
    for a DIFFERENT key on the same export, because the cache hit is
    itself proof the caller has moved on. No committed test exercised
    this claim (the reviewer's own probe D confirmed it by hand and found
    the gap).

    Deterministic via Event handshakes, no sleeps: key B's bundle is
    pre-built into the scratch STUDIES_DIR with a plain, un-monkeypatched
    GET before the fake segment_pieces is installed, so the segment_
    pieces call count below (checked only from the point the monkeypatch
    lands) proves the LATER request for that same key never cuts again --
    it is genuinely served from the file load_or_build_bundle's own
    disk-first check already reads before build_bundle is ever reached.
    """
    import threading

    client, studies = make_client(tmp_path, monkeypatch)
    import bundle
    import pieces

    # Warm key B's bundle on disk before the fake is installed: a real,
    # un-monkeypatched cut.
    warm = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 1.2},
    )
    assert warm.status_code == 200, warm.text
    assert bundle.bundle_path(
        "tiny", "concrete", "bonded-courses", 1.2, 0.2
    ).is_file(), "key B's bundle must already sit on disk before the slow build starts"

    started = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def fake_segment_pieces(tess, surface, support_points, checkpoint=None):
        call_count["n"] += 1
        started.set()
        assert release.wait(timeout=5), "release was never set"
        if checkpoint is not None:
            checkpoint()
        raise AssertionError(
            "unreachable: the checkpoint above must raise CutSuperseded "
            "before segment_pieces ever computes anything for key A"
        )

    monkeypatch.setattr(pieces, "segment_pieces", fake_segment_pieces)

    responses = {}

    def call_key_a():
        responses["first"] = client.get(
            "/api/studies/Tiny/bundle",
            params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9},
        )

    t1 = threading.Thread(target=call_key_a)
    t1.start()
    assert started.wait(timeout=5), "key A's slow build never started"

    # Key B's request, now: served straight from the on-disk cache warmed
    # above -- no cut, no checkpoint, no segment_pieces call at all -- yet
    # it must still register as the export's freshest interactive request
    # and supersede key A's still-blocked build.
    second = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 1.2},
    )
    assert second.status_code == 200, second.text

    release.set()
    t1.join(timeout=5)
    assert not t1.is_alive(), "key A's own request never finished"

    assert responses["first"].status_code == 409
    assert responses["first"].json() == {"superseded": True}
    assert call_count["n"] == 1, (
        "the cache-hit request for key B must never call segment_pieces "
        "at all: {} call(s) after the fake was installed".format(call_count["n"])
    )


def _pyramid_mesh():
    document = _pyramid_compas_document()
    return document, json.loads(document["thrustMesh"])


def _pyramid_with_null_coordinate():
    document, mesh = _pyramid_mesh()
    mesh["data"]["vertex"]["0"]["x"] = None
    document["thrustMesh"] = json.dumps(mesh)
    return document


def _pyramid_with_non_finite_coordinates():
    document, mesh = _pyramid_mesh()
    mesh["data"]["vertex"]["0"]["x"] = float("nan")
    mesh["data"]["vertex"]["1"]["y"] = float("inf")
    document["thrustMesh"] = json.dumps(mesh)
    return document


def test_compas_upload_with_a_null_coordinate_is_a_400_with_no_partial_state(
    tmp_path, monkeypatch
):
    """Fix 1: derive_contract used to let a null coordinate's TypeError
    escape past app.py's own `except ValueError`, answering an opaque 500
    while the compas file had already been written and cache invalidation
    never got to run. The malformed-geometry check now runs BEFORE
    anything is persisted, so a null coordinate refuses the whole upload
    honestly and leaves nothing on disk -- no stored compas without its
    invalidation having run, because nothing is stored at all."""

    client, _ = make_client(tmp_path, monkeypatch)
    response = client.put(
        "/api/uploads/exports/Null/compas",
        content=json.dumps(_pyramid_with_null_coordinate()).encode(),
    )
    assert response.status_code == 400
    assert "vertex" in response.json()["detail"]
    assert not (tmp_path / "upload" / "Null-compas.json").is_file()
    assert not (tmp_path / "upload" / "Null-contract.json").is_file()
    exports = [s["export"] for s in client.get("/api/studies").json()["studies"]]
    assert "Null" not in exports


def test_compas_reupload_for_a_paired_study_with_a_null_coordinate_is_a_400(
    tmp_path, monkeypatch
):
    """Fix round 1, CRITICAL: the null/non-finite check lived ONLY inside
    the `if not contract_path.is_file()` branch, so re-uploading corrupt
    compas geometry for an export that ALREADY has a contract -- the
    ordinary case for any already-paired study, most real usage -- skipped
    validation entirely and stored the corrupt file with a plain 200. That
    stored geometry_path flows straight into staging.run_staging. The
    check must run on every compas upload, paired or not; the no-partial-
    state rule applies here exactly as it does for a brand new export."""

    client, _ = make_client(tmp_path, monkeypatch)
    upload_dir = tmp_path / "upload"
    before_contract = (upload_dir / "Tiny-contract.json").read_text(encoding="utf-8")
    before_compas = (upload_dir / "Tiny-compas.json").read_text(encoding="utf-8")

    response = client.put(
        "/api/uploads/exports/Tiny/compas",
        content=json.dumps(_pyramid_with_null_coordinate()).encode(),
    )
    assert response.status_code == 400
    assert "vertex" in response.json()["detail"]

    assert (upload_dir / "Tiny-contract.json").read_text(encoding="utf-8") == before_contract
    assert (upload_dir / "Tiny-compas.json").read_text(encoding="utf-8") == before_compas, (
        "the corrupt document must not overwrite the existing compas file "
        "either -- no partial state on the paired-study path"
    )


def test_compas_upload_with_non_finite_coordinates_is_a_400_counting_them(
    tmp_path, monkeypatch
):
    """Fix 4: a bare NaN/Infinity in the thrustMesh used to survive
    json.loads and only 500 later, at bundle serialisation time
    (Starlette's JSONResponse sets allow_nan=False). Rejected here, at
    derive time, named and counted, before anything is written."""

    client, _ = make_client(tmp_path, monkeypatch)
    response = client.put(
        "/api/uploads/exports/Nonfinite/compas",
        content=json.dumps(_pyramid_with_non_finite_coordinates()).encode(),
    )
    assert response.status_code == 400
    assert "2 non-finite" in response.json()["detail"]
    assert not (tmp_path / "upload" / "Nonfinite-compas.json").is_file()


def test_export_name_drive_relative_and_dotdot_cannot_escape_upload_dir(
    tmp_path, monkeypatch
):
    """Fix 2 (route level, strengthened in fix round 1): the export upload
    name check omitted ':' entirely and never ran _contained, so a Windows
    drive-relative name could slip the naive '/'/'\\'/'..' guard. This
    proves the REJECTION CONTRACT holds for every input an attacker would
    actually try -- 'C:evil', 'D:evil', and a backslash '..' traversal
    alike -- rather than leaning on a filesystem accident: 'C:evil'
    happens to fold harmlessly back inside UPLOAD_DIR when UPLOAD_DIR is
    itself on the C: drive (a same-drive pathlib quirk, not a property of
    the check), so a red proof built only on that one string would be
    demonstrating the wrong thing. See
    test_contained_itself_refuses_the_genuine_cross_drive_escape below for
    the specific vector that actually would escape ('D:evil' against a
    C:-drive UPLOAD_DIR) and _contained's own, independent refusal of it."""

    client, _ = make_client(tmp_path, monkeypatch)
    for bad_name in ("C:evil", "D:evil", "..%5Cevil"):
        response = client.put(
            "/api/uploads/exports/{}/compas".format(bad_name),
            content=b'{"thrustMesh": "{}"}',
        )
        assert response.status_code == 400, "{!r} was not rejected: {} {!r}".format(
            bad_name, response.status_code, response.text[:200])
    assert not list(tmp_path.rglob("*evil*")), (
        "no file named for any of the rejected names may exist anywhere "
        "under tmp_path"
    )


def test_contained_itself_refuses_the_genuine_cross_drive_escape(tmp_path, monkeypatch):
    """The route-level 400s above hold regardless of which guard actually
    fires -- the ':' character check alone already rejects every case
    tried there, so that test does not by itself prove _contained is
    doing anything. This proves _contained specifically: 'D:evil-
    compas.json' joined onto a C:-drive UPLOAD_DIR resolves to a path with
    no relation to UPLOAD_DIR at all (pathlib treats the segment as
    drive-relative to D:, discarding the base entirely -- confirmed
    directly, not assumed), and _contained's own containment check must,
    and does, refuse it -- refusing suspicious names outright by contract,
    not merely relying on where they happen to resolve on this machine."""

    client, _ = make_client(tmp_path, monkeypatch)
    import app as app_module

    candidate = app_module.bundle.UPLOAD_DIR / "D:evil-compas.json"
    assert str(candidate).startswith("D:"), (
        "D:evil-compas.json must actually be drive-relative once joined "
        "onto a C:-drive UPLOAD_DIR, or this test is not proving what it "
        "claims -- got {!r}".format(candidate)
    )
    assert not app_module._contained(app_module.bundle.UPLOAD_DIR, "D:evil-compas.json")


def test_frames_study_slug_drive_relative_cannot_escape(tmp_path, monkeypatch):
    """Fix round 1, Important: frames_dir's 'study-' branch (the only
    other route in app.py that builds a filesystem path from a caller-
    supplied path segment) still checked only '/'/'\\'/'..' and never ran
    _contained -- the same character class and the same guard this task
    closed everywhere else. Pre-fix, a drive-relative slug slipped past
    the naive check and reached the STUDIES_DIR existence lookup, so
    whether it 400'd depended on what, if anything, happened to sit at
    the resolved path (usually nothing, so it read as a plain 404 -- a
    validation gap disguised as an ordinary miss, not a guard failure
    every time, the same doctrine test_windows_drive_relative_names_
    cannot_escape already established for hdri/columns)."""

    client, _ = make_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/frames/study-D:evil", params={"frame": 1}, content=b"png-bytes"
    )
    assert response.status_code == 400, "{} {!r}".format(
        response.status_code, response.text[:200])
    stitch = client.post("/api/frames/study-D:evil/stitch")
    assert stitch.status_code == 400
    assert not list(tmp_path.rglob("*evil*"))


def test_index_names_the_missing_studio_js_instead_of_500ing(tmp_path, monkeypatch):
    """Fix 3: GET '/' called studio.js's own .stat() before ever checking
    it existed, so a missing static asset answered an opaque 500 with no
    indication of what was missing. A tmp static dir carrying only
    index.html (never the real bench/studio/static) reproduces the gap
    honestly, without touching the shipped file."""

    client, _ = make_client(tmp_path, monkeypatch)
    import app as app_module

    static_dir = tmp_path / "static_missing_js"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        '<html><script src="/static/studio.js?v=dev"></script></html>',
        encoding="utf-8",
    )
    monkeypatch.setattr(app_module, "STATIC_DIR", static_dir)

    response = client.get("/")
    assert response.status_code in (404, 500)
    assert "studio.js" in response.json()["detail"]


def test_reupload_deletes_stale_fea_verification(tmp_path, monkeypatch):
    """Fix 5: _invalidate_studio_cache dropped bundle-*.json and
    staging-*.json but never fea-verification.json, so a re-import under
    the same name with CHANGED GEOMETRY kept serving SILENTLY WRONG old
    verification numbers in the next bundle -- the design spec's own
    acceptance line. fea-verification.json is the only per-slug
    verification artifact anything under bench/studio writes (STUDIES_DIR/
    slug directly, not the nested studio/ cache dir; confirmed against
    bundle.py's own _read_optional call site and bench/demo/
    09_structural_verification.py's own write) -- there is no sibling to
    also cover.

    Fix round 1, Important: the re-upload below genuinely moves a vertex
    (mirrors test_reupload_with_changed_geometry_invalidates_bundle_and_
    staging_caches's own pattern) and the final bundle's own geometry is
    asserted to have actually changed -- re-uploading byte-identical
    content would only prove the fix runs on ANY successful upload, not
    that it earns the spec's "re-upload changes geometry" claim."""

    client, _ = make_client(tmp_path, monkeypatch)
    study_dir = tmp_path / "studies" / "tiny"
    study_dir.mkdir(parents=True, exist_ok=True)
    (study_dir / "fea-verification.json").write_text(
        json.dumps({"stale": True}), encoding="utf-8"
    )

    before = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9},
    )
    assert before.status_code == 200
    assert before.json()["verification"] == {"stale": True}

    changed = tiny_contract()
    changed["equilibrium"]["vertices"][0]["z"] = 9.0
    reupload = client.put(
        "/api/uploads/exports/Tiny/contract",
        content=json.dumps(changed).encode(),
    )
    assert reupload.status_code == 200
    assert not (study_dir / "fea-verification.json").is_file()

    after = client.get(
        "/api/studies/Tiny/bundle",
        params={"material": "concrete", "pattern": "bonded-courses", "size": 0.9},
    )
    assert after.status_code == 200
    assert after.json()["verification"] is None
    assert after.json()["analysis_mesh"]["vertices"][0][2] == 9.0, (
        "the re-upload must actually have changed the geometry the next "
        "bundle serves, not merely re-stored the same bytes"
    )


def test_slug_collision_between_different_export_names_is_a_400(tmp_path, monkeypatch):
    """Fix 6: slugify("Foo Bar") == slugify("foo-bar") == "foo-bar", so two
    DIFFERENT export names would share one bundle/staging/verification
    path -- data mixing, not merely a naming quirk. slugify itself must
    not change (existing study dirs keep their identity); the upload
    route refuses the second, colliding name instead, naming both. A
    same-name re-upload (the ordinary case) must stay allowed."""

    client, _ = make_client(tmp_path, monkeypatch)
    first = client.put(
        "/api/uploads/exports/Foo Bar/contract",
        content=json.dumps(tiny_contract()).encode(),
    )
    assert first.status_code == 200
    second = client.put(
        "/api/uploads/exports/Foo Bar/compas",
        content=b'{"thrustMesh": "{}"}',
    )
    assert second.status_code == 200

    collision = client.put(
        "/api/uploads/exports/foo-bar/contract",
        content=json.dumps(tiny_contract()).encode(),
    )
    assert collision.status_code == 400
    detail = collision.json()["detail"]
    assert "Foo Bar" in detail
    assert "foo-bar" in detail
    assert not (tmp_path / "upload" / "foo-bar-contract.json").is_file()

    reupload = client.put(
        "/api/uploads/exports/Foo Bar/contract",
        content=json.dumps(tiny_contract()).encode(),
    )
    assert reupload.status_code == 200


def _piece_solids_module():
    """Same sys.path dance test_piece_solids.py's own studio() helper
    does: make_client above already inserts bench/studio, but a test that
    only calls make_client and never imports app directly still needs
    this to reach piece_solids for its own spot-check."""

    import sys

    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    import piece_solids

    return piece_solids


def test_pieces_export_writes_bench_pieces_matching_the_bundle_order(
    tmp_path, monkeypatch
):
    """Task 2 (pieces export): the 200 path, end to end against the same
    Tiny fixture every other test_app.py test already uses.

    Pins the whole schema at once against a live bundle fetched first, so
    the piece order/count/vertex-length checks are proven against the
    SAME cut this route itself built (bundle.load_or_build_bundle's own
    cache makes the second call, inside the route, a cache hit against
    the first)."""

    client, studies = make_client(tmp_path, monkeypatch)
    params = {"material": "concrete", "pattern": "bonded-courses", "size": 0.9,
              "thickness": 0.2}
    bundle_response = client.get("/api/studies/Tiny/bundle", params=params)
    assert bundle_response.status_code == 200
    bundle_pieces = bundle_response.json()["pieces"]
    assert bundle_pieces, "the Tiny fixture must actually cut pieces for this test to prove anything"

    response = client.post("/api/studies/Tiny/pieces-export", params=params)
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"path", "piece_count", "courses"}

    path = Path(body["path"])
    assert path.is_absolute()
    assert path.is_file()
    assert path == studies / "tiny" / "studio" / "Tiny-pieces.json"

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema"] == "bench.pieces/1"
    assert document["units"] == "m"
    assert document["export"] == "Tiny"
    assert document["material"] == "concrete"
    assert document["pattern"] == "bonded-courses"
    assert document["size"] == 0.9
    assert document["thickness"] == 0.2
    assert document["joint_gap"] == 0.0
    assert document["taper"] == 0.0
    assert isinstance(document["generated"], str) and document["generated"]
    assert document["piece_count"] == len(document["pieces"]) == body["piece_count"]
    assert document["courses"] == body["courses"]
    assert isinstance(document["degenerate_dropped"], list)

    # Order contract: bundle order, untouched (keys compared).
    assert [p["key"] for p in document["pieces"]] == [p["key"] for p in bundle_pieces]

    for exported, source in zip(document["pieces"], bundle_pieces):
        assert exported["course"] == source["course"]
        assert exported["is_support"] == source["is_support"]
        assert len(exported["vertices"]) == 2 * len(source["mid"])
        assert exported["seat_plane"] == source.get("seat_plane")
        assert exported["seat_gap"] == source.get("seat_gap")

    # Spot check one piece, closed and positive volume, through Task 1's
    # own verifier -- not re-implemented here.
    piece_solids = _piece_solids_module()
    first = document["pieces"][0]
    check = piece_solids.verify_solid(first["vertices"], first["faces"])
    assert check["closed"] is True
    assert check["volume"] > 0


def test_pieces_export_writes_the_base_mesh_verbatim_from_the_bundle(
    tmp_path, monkeypatch
):
    """Addendum, 2026-08-20 (Param's live feedback, item 1): the document
    gains an OPTIONAL top-level base_mesh -- the study's analysis mesh
    (the thrust wireframe), copied verbatim from the bundle's own
    analysis_mesh. The route writes it ALWAYS; only vertices and faces
    travel (edges is bundle-only bookkeeping, not part of base_mesh's
    documented shape)."""

    client, studies = make_client(tmp_path, monkeypatch)
    params = {"material": "concrete", "pattern": "bonded-courses", "size": 0.9,
              "thickness": 0.2}
    bundle_response = client.get("/api/studies/Tiny/bundle", params=params)
    assert bundle_response.status_code == 200
    analysis_mesh = bundle_response.json()["analysis_mesh"]
    assert analysis_mesh["vertices"], "the Tiny fixture must have an analysis mesh for this test to prove anything"

    response = client.post("/api/studies/Tiny/pieces-export", params=params)
    assert response.status_code == 200
    path = Path(response.json()["path"])
    document = json.loads(path.read_text(encoding="utf-8"))

    assert "base_mesh" in document
    base_mesh = document["base_mesh"]
    assert set(base_mesh) == {"vertices", "faces"}
    assert len(base_mesh["vertices"]) == len(analysis_mesh["vertices"])
    assert len(base_mesh["faces"]) == len(analysis_mesh["faces"])
    assert base_mesh["vertices"] == analysis_mesh["vertices"]
    assert base_mesh["faces"] == analysis_mesh["faces"]


def test_pieces_export_raises_on_a_piece_that_fails_verification(
    tmp_path, monkeypatch
):
    """Task 2 review follow-up: the raise-not-skip contract, proven. A
    piece failing verify_solid is a genuine bug by the design doc's own
    ruling, so the route must RAISE -- never quietly drop the piece or
    write a partial document."""

    client, studies = make_client(tmp_path, monkeypatch)
    params = {"material": "concrete", "pattern": "bonded-courses", "size": 0.9,
              "thickness": 0.2}
    piece_solids = _piece_solids_module()
    monkeypatch.setattr(
        piece_solids, "verify_solid",
        lambda vertices, faces: {"closed": False, "volume": 0.0},
    )
    with pytest.raises(RuntimeError, match="failed verify_solid"):
        client.post("/api/studies/Tiny/pieces-export", params=params)
    assert not (studies / "tiny" / "studio" / "Tiny-pieces.json").exists()


def test_pieces_export_two_thicknesses_differ_only_in_the_offset(tmp_path, monkeypatch):
    """thickness is the route parameter; the SAME cut extrudes at any
    thickness. bonded-courses ships a seat_plane (pieces.py's own K2), so
    every bottom vertex is offset 0 regardless of thickness (identical
    between the two exports) and every top vertex moves by exactly
    (thickness_b - thickness_a) along the piece's OWN seat plane normal
    -- the exact arithmetic piece_solids.solidify's seat-plane branch
    implements, proven here against a real export rather than the unit
    fixture in test_piece_solids.py."""

    client, studies = make_client(tmp_path, monkeypatch)
    thin = {"material": "concrete", "pattern": "bonded-courses", "size": 0.9,
            "thickness": 0.15}
    thick = {"material": "concrete", "pattern": "bonded-courses", "size": 0.9,
             "thickness": 0.30}
    # Both requests write to the SAME path (overwrite is the point,
    # regeneration -- see the route's own docstring), so each document has
    # to be read off disk immediately after its own POST, before the
    # second POST overwrites it in place.
    response_thin = client.post("/api/studies/Tiny/pieces-export", params=thin)
    assert response_thin.status_code == 200
    doc_thin = json.loads(Path(response_thin.json()["path"]).read_text(encoding="utf-8"))

    response_thick = client.post("/api/studies/Tiny/pieces-export", params=thick)
    assert response_thick.status_code == 200
    doc_thick = json.loads(Path(response_thick.json()["path"]).read_text(encoding="utf-8"))
    assert response_thin.json()["path"] == response_thick.json()["path"], (
        "both exports target the same export name, so they must overwrite "
        "the same file, not accumulate one per thickness"
    )
    assert doc_thin["thickness"] == 0.15
    assert doc_thick["thickness"] == 0.30
    assert [p["key"] for p in doc_thin["pieces"]] == [p["key"] for p in doc_thick["pieces"]]

    piece_thin, piece_thick = doc_thin["pieces"][0], doc_thick["pieces"][0]
    assert piece_thin["seat_plane"] is not None, (
        "bonded-courses must ship a seat_plane for this delta to be well defined"
    )
    count = len(piece_thin["vertices"]) // 2
    # Bottom half (offset 0) never depends on thickness.
    assert piece_thin["vertices"][count:] == piece_thick["vertices"][count:]
    nx, ny, nz = piece_thin["seat_plane"]["normal"]
    dt = doc_thick["thickness"] - doc_thin["thickness"]
    for i in range(count):
        top_thin = piece_thin["vertices"][i]
        top_thick = piece_thick["vertices"][i]
        delta = [top_thick[k] - top_thin[k] for k in range(3)]
        assert delta == pytest.approx([nx * dt, ny * dt, nz * dt], abs=1e-9)


def test_pieces_export_on_an_uncut_study_is_409_with_the_verbatim_reason(
    tmp_path, monkeypatch
):
    """No blocks, and the engine's own refusal says why -- the same
    bay_contract() fixture test_a_plan_the_engine_refuses_ships_a_200_
    with_uncut_reason above proves refuses through get_bundle's 200 path;
    this route has nothing to write for an uncut study, so it 409s
    instead, carrying the identical, verbatim message."""

    client, studies = make_client(tmp_path, monkeypatch)
    upload = tmp_path / "upload"
    (upload / "Bay-contract.json").write_text(
        json.dumps(bay_contract()), encoding="utf-8"
    )
    (upload / "Bay-compas.json").write_text("{}", encoding="utf-8")
    params = {"material": "concrete", "pattern": "bonded-courses", "size": 0.9,
              "thickness": 0.2}
    bundle_response = client.get("/api/studies/Bay/bundle", params=params)
    reason = bundle_response.json()["uncut_reason"]
    assert reason

    export_response = client.post("/api/studies/Bay/pieces-export", params=params)
    assert export_response.status_code == 409
    assert export_response.json() == {"uncut_reason": reason}
    assert not (studies / "bay" / "studio" / "Bay-pieces.json").exists()


def test_pieces_export_rejects_a_drive_relative_or_traversal_export_name(
    tmp_path, monkeypatch
):
    """The same ':'/_contained guard every other route that builds a
    filename from a caller-supplied path segment already carries (the
    upload route's own name check, frames_dir's "study-" branch) -- see
    test_export_name_drive_relative_and_dotdot_cannot_escape_upload_dir
    above for the identical proof on that route. Valid material/pattern/
    size are supplied so the request clears FastAPI's own Query(...)
    validation and actually reaches the route body's guard."""

    client, studies = make_client(tmp_path, monkeypatch)
    params = {"material": "concrete", "pattern": "bonded-courses", "size": 0.9,
              "thickness": 0.2}
    for bad_name in ("C:evil", "D:evil", "..%5Cevil"):
        response = client.post(
            "/api/studies/{}/pieces-export".format(bad_name), params=params
        )
        assert response.status_code == 400, "{!r} was not rejected: {} {!r}".format(
            bad_name, response.status_code, response.text[:200])
    assert not list(tmp_path.rglob("*evil*"))
