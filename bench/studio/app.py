"""The studio server: JSON out, subprocesses down, no solver imports.

create_app(runner=...) is the test seam: the runner forwards to
staging.run_staging, so the API tests exercise the whole lifecycle with a
stub while the real server shells to .venv-fea.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import urllib.parse
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import bundle
import derive_contract
import generators
import geometry
import staging

STATIC_DIR = Path(__file__).resolve().parent / "static"
COLUMNS_DIR = Path(__file__).resolve().parent / "columns"
HDRI_DIR = Path(__file__).resolve().parent / "hdri"


def _contained(directory: Path, name: str) -> bool:
    """True when directory/name resolves inside directory. Catches ..,
    separators, and Windows drive-relative names like C:foo that
    Path joins by replacing the base entirely."""
    try:
        return (directory / name).resolve().parent == directory.resolve()
    except (OSError, ValueError):
        return False


def _known_export_names(directory: Path) -> set:
    """Every export name with at least one uploaded half sitting in
    directory, read live off the filenames themselves -- the same,
    single record of "what exports exist" geometry.available_exports
    already treats as authoritative (fix 6, 2026-08-19 fix batch)."""
    names = set()
    for suffix in ("-contract.json", "-compas.json", "-tessellation.json"):
        for path in directory.glob("*" + suffix):
            names.add(path.name[: -len(suffix)])
    return names


RUNS: dict = {}
RUNS_LOCK = threading.Lock()

MATERIALS = sorted(staging.DENSITIES)
# 0.15 floor (Param, 2026-08-18): coarse cuts read as weird spiky shapes,
# real block work wants sub-300 mm targets; the smaller cut takes longer
# and that is accepted.
SIZE_MIN = 0.15
SIZE_MAX = 3.0
PATTERNS = sorted(generators.GENERATORS)


def _ffmpeg_present() -> bool:
    return shutil.which("ffmpeg") is not None


def _invalidate_studio_cache(slug: str) -> None:
    """Drop every cached bundle/staging file, and any stale verification,
    for a study after re-import.

    A changed export must never keep serving a stale bundle built from the
    old geometry, or old fea-verification.json numbers measured against
    that old geometry -- SILENTLY WRONG, not merely stale (fix 5, 2026-08-19
    fix batch). Frames and recording.mp4 are untouched: they belong to a
    recording, not to a geometry snapshot.

    fea-verification.json is the only per-slug verification artifact
    anything under bench/studio writes today (bundle.py's own
    _read_optional call site, mirrored by bench/demo/
    09_structural_verification.py's write) -- there is no sibling to also
    cover; if one is ever added, it belongs in this same pass.
    """

    bundle.clear_cut_memo()
    studio_dir = bundle.STUDIES_DIR / slug / "studio"
    if studio_dir.is_dir():
        for pattern in ("bundle-*.json", "staging-*.json"):
            for stale in studio_dir.glob(pattern):
                stale.unlink()
    verification = bundle.STUDIES_DIR / slug / "fea-verification.json"
    if verification.is_file():
        verification.unlink()


def _validate(export: str, material: str, pattern: str, size: float,
              thickness: float) -> None:
    pairs = geometry.available_exports(bundle.UPLOAD_DIR)
    if export not in pairs:
        raise HTTPException(404, "no export named {!r}. Available: {}".format(
            export, ", ".join(sorted(pairs))))
    if material not in staging.DENSITIES:
        raise HTTPException(400, "unknown material {!r}: use one of {}".format(
            material, ", ".join(MATERIALS)))
    if pattern not in generators.GENERATORS:
        planned = generators.PLANNED.get(pattern)
        detail = ("the {} pattern arrives in {}".format(pattern, planned)
                  if planned else "unknown pattern {!r}".format(pattern))
        raise HTTPException(400, "{}: use one of {}".format(
            detail, ", ".join(PATTERNS)))
    if not SIZE_MIN <= size <= SIZE_MAX:
        raise HTTPException(400, "target piece size must be between {} and {} "
                                 "metres".format(SIZE_MIN, SIZE_MAX))
    if not 0.05 <= thickness <= 0.5:
        raise HTTPException(400, "thickness must be between 0.05 and 0.5 metres")


def create_app(runner=None, cra_runner=None) -> FastAPI:
    app = FastAPI(title="Bench Studio")

    @app.get("/api/studies")
    def studies():
        pairs = geometry.available_exports(bundle.UPLOAD_DIR)
        rows = []
        for export in sorted(pairs):
            slug = geometry.slugify(export)
            studio_dir = bundle.STUDIES_DIR / slug / "studio"
            rows.append({
                "export": export,
                "slug": slug,
                "has_verification": (
                    bundle.STUDIES_DIR / slug / "fea-verification.json"
                ).is_file(),
                "cached_bundles": sorted(
                    p.name for p in studio_dir.glob("bundle-*.json")
                ) if studio_dir.is_dir() else [],
            })
        columns = sorted(
            p.name for p in COLUMNS_DIR.glob("*.json")
        ) if COLUMNS_DIR.is_dir() else []
        return {
            "studies": rows, "columns": columns, "ffmpeg": _ffmpeg_present(),
            "patterns": PATTERNS,
            "pattern_defaults": generators.DEFAULT_PATTERN,
            "patterns_planned": generators.PLANNED,
            "pattern_notes": generators.MATERIAL_NOTES,
            "size_range": [SIZE_MIN, SIZE_MAX],
        }

    @app.get("/api/studies/{export}/bundle")
    def get_bundle(
        export: str, material: str = Query(...), pattern: str = Query(...),
        size: float = Query(...), thickness: float = Query(0.2),
    ):
        _validate(export, material, pattern, size, thickness)
        # Cut cancellation (2026-08-19): every interactive bundle GET
        # registers a token for its export BEFORE calling
        # load_or_build_bundle, even one that turns out to be served
        # straight from the on-disk cache and never reaches a cut at all
        # -- that cache hit is itself evidence this caller wants a
        # DIFFERENT key than whatever an older, still-running interactive
        # build for this export wants, and the older build has to be told
        # (see bundle.register_interactive's own comment). The staging/
        # runs path (start_run's work(), below) never registers and never
        # passes a token, so it can never be superseded by this at all.
        token = bundle.register_interactive(export, (export, pattern, size))
        try:
            return bundle.load_or_build_bundle(
                export, material, pattern, size, thickness, interactive_token=token)
        except bundle.CutSuperseded:
            # A strictly newer, different-key interactive request for
            # this export registered while this one's own cut was still
            # running (see bundle.CutSuperseded's own docstring). Not a
            # server fault: the client's own sequence guard, or its
            # AbortController, means nobody was left waiting to render
            # this answer anyway. One log line, not a stack trace.
            print(
                "bundle: {} superseded by a newer request; cut cancelled "
                "mid-build".format(export)
            )
            return JSONResponse({"superseded": True}, status_code=409)
        except ValueError as error:
            # tessellation.from_document raises ValueError with a message
            # naming the offending cell -- a bad authored tessellation lands
            # here, and so does an unknown export name. The message is the
            # whole point (it says where to look), so it is carried through
            # unchanged rather than paraphrased or swallowed into a 500.
            #
            # P5 (presentation batch, 2026-08-18): domain.plan_domain and
            # generators.generate no longer reach this handler at all. Their
            # ValueError -- a re-entrant OUTER rim the engine's star-shaped
            # constraint refuses -- is valid geometry, not a malformed
            # request, so build_bundle catches it itself (see
            # bundle.CutRefused) and ships a 200 with uncut_reason set
            # rather than raising through to here.
            #
            # Multi-loop (2026-08-19): an oculus or a hole is NOT one of
            # these cases any more -- openings.py classifies it apart from
            # the outer rim and the cut clips around it natively. See
            # bundle.CutRefused's own docstring for the current, complete
            # list of what still refuses.
            raise HTTPException(400, str(error))

    @app.post("/api/runs", status_code=202)
    def start_run(body: dict):
        export = body.get("export", "")
        material = body.get("material", "")
        pattern = body.get("pattern", "")
        # Coerced BEFORE _validate, so a value float() cannot read raised
        # out of the coercion itself and answered 500: size "abc" and a
        # null thickness both did, while a MISSING size correctly gave 400
        # through the range check. A body the caller can fix is a 400, and
        # the message says which field it is.
        for field, default in (("size", 0.0), ("thickness", 0.2)):
            try:
                float(body.get(field, default))
            except (TypeError, ValueError):
                raise HTTPException(
                    400, "{} must be a number, not {!r}".format(
                        field, body.get(field)))
        size = float(body.get("size", 0.0))
        thickness = float(body.get("thickness", 0.2))
        _validate(export, material, pattern, size, thickness)
        slug = geometry.slugify(export)
        with RUNS_LOCK:
            for run in RUNS.values():
                if run["slug"] == slug and run["state"] in ("queued", "running"):
                    return JSONResponse({"run": run["id"]}, status_code=409)
            run_id = uuid.uuid4().hex[:12]
            RUNS[run_id] = {
                "id": run_id, "export": export, "slug": slug,
                "material": material, "pattern": pattern, "size": size,
                "thickness": thickness,
                # "of" stays 0 until the cut is known: the number of stages
                # is the number of courses the cut produced, so nothing can
                # state it up front the way the old "rings" request
                # parameter could. Cutting a real export is the slow part,
                # and a reader left with a bare "stage 0/0" for all of it
                # cannot tell work from a hang. "phase" is the honest
                # answer while the count is still unknown; the viewer half
                # of this belongs to another dispatch.
                "state": "queued", "stage": 0, "of": 0, "phase": "queued",
                "message": "",
            }

        def work():
            run = RUNS[run_id]
            try:
                run["state"] = "running"
                run["phase"] = "cutting"
                run["message"] = "cutting the tessellation"
                pairs = geometry.available_exports(bundle.UPLOAD_DIR)

                def on_stage(stage, of):
                    run["stage"], run["of"] = stage, of
                    run["phase"] = "staging"
                    run["message"] = "fea + cra per stage"

                staging.run_staging(
                    pairs[export], material, pattern, size,
                    bundle.staging_path(slug, material, pattern, size, thickness),
                    runner=runner, cra_runner=cra_runner, on_stage=on_stage, thickness=thickness,
                )
                run["phase"] = "bundling"
                run["message"] = "assembling the bundle"
                bundle.build_bundle(export, material, pattern, size, thickness)
                run["state"] = "done"
                run["phase"] = "done"
                run["message"] = ""
            except Exception as error:
                run["state"] = "failed"
                run["phase"] = "failed"
                run["message"] = "{}: {}".format(type(error).__name__, error)

        threading.Thread(target=work, daemon=True).start()
        return {"run": run_id}

    @app.get("/api/runs/{run_id}")
    def run_state(run_id: str):
        run = RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "no run {}".format(run_id))
        return {
            "state": run["state"], "stage": run["stage"], "of": run["of"],
            # phase says what is happening while "of" is still 0, which is
            # the whole duration of the cut.
            "phase": run.get("phase", ""),
            "message": run["message"],
            "bundle_url": "/api/studies/{}/bundle?material={}&pattern={}&size={}&thickness={}".format(
                urllib.parse.quote(run["export"]), run["material"],
                urllib.parse.quote(run["pattern"]), run["size"],
                run["thickness"]),
        }

    @app.get("/api/columns/{name}")
    def column(name: str):
        if "/" in name or "\\" in name or ".." in name or ":" in name:
            raise HTTPException(400, "bad column name")
        if not _contained(COLUMNS_DIR, name):
            raise HTTPException(400, "bad column name")
        path = COLUMNS_DIR / name
        if not path.is_file():
            raise HTTPException(404, "no column file {}".format(name))
        return FileResponse(path)

    @app.get("/api/hdri")
    def hdri_list():
        if not HDRI_DIR.is_dir():
            return {"files": []}
        return {"files": sorted(
            p.name for p in HDRI_DIR.glob("*.hdr") if p.is_file())}

    @app.get("/api/hdri/{name}")
    def hdri_file(name: str):
        if "/" in name or "\\" in name or ".." in name or ":" in name:
            raise HTTPException(400, "bad hdri name")
        if not _contained(HDRI_DIR, name):
            raise HTTPException(400, "bad hdri name")
        path = HDRI_DIR / name
        if not path.is_file():
            raise HTTPException(404, "no hdri file {}".format(name))
        return FileResponse(path)

    @app.put("/api/uploads/hdri/{filename}")
    async def upload_hdri(filename: str, request: Request):
        if "/" in filename or "\\" in filename or ".." in filename or ":" in filename:
            raise HTTPException(400, "bad hdri filename")
        if not _contained(HDRI_DIR, filename):
            raise HTTPException(400, "bad hdri filename")
        if not filename.endswith(".hdr"):
            raise HTTPException(400, "hdri filename must end in .hdr")
        body = await request.body()
        if not (body.startswith(b"#?RADIANCE") or body.startswith(b"#?RGBE")):
            raise HTTPException(400, "not a Radiance .hdr file")
        HDRI_DIR.mkdir(parents=True, exist_ok=True)
        (HDRI_DIR / filename).write_bytes(body)
        return {"stored": filename}

    @app.put("/api/uploads/exports/{name}/{kind}")
    async def upload_export(name: str, kind: str, request: Request):
        if "/" in name or "\\" in name or ".." in name or ":" in name:
            raise HTTPException(400, "bad export name")
        if kind not in ("contract", "compas", "tessellation"):
            raise HTTPException(
                400, "kind must be 'contract', 'compas' or 'tessellation'")
        # Fix 2 (2026-08-19 fix batch): the character guard above never
        # caught a Windows drive-relative name (":" was missing from it
        # until this task), and this route never ran _contained at all --
        # the same gap _contained's own docstring names, already closed on
        # the hdri and columns upload routes. Checked against the actual
        # filename this upload will write.
        if not _contained(bundle.UPLOAD_DIR, "{}-{}.json".format(name, kind)):
            raise HTTPException(400, "bad export name")
        slug = geometry.slugify(name)
        # Fix 6: slugify("Foo Bar") == slugify("foo-bar") -- two DIFFERENT
        # export names sharing a slug would share one bundle/staging/
        # verification path, silently mixing data. slugify itself is
        # untouched (existing study dirs keep their identity); a NEW name
        # colliding with a DIFFERENT existing one is refused, naming both.
        # bundle.UPLOAD_DIR's own filenames are the honest source for who
        # currently owns a slug: the same place geometry.available_exports
        # and this route's own write already treat as the one record of
        # "what exports exist", live and never stale.
        for other_name in _known_export_names(bundle.UPLOAD_DIR):
            if other_name != name and geometry.slugify(other_name) == slug:
                raise HTTPException(
                    400,
                    "export {!r} and {!r} both slugify to {!r}; they "
                    "would share one study -- rename one of them".format(
                        name, other_name, slug))
        with RUNS_LOCK:
            for run in RUNS.values():
                if run["slug"] == slug and run["state"] in ("queued", "running"):
                    return JSONResponse({"run": run["id"]}, status_code=409)
        body = await request.body()
        try:
            document = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, "not valid JSON")
        derived_contract = None
        derivation_error = None
        if kind == "contract":
            try:
                geometry.mesh_arrays(document)
                geometry.support_ids(document)
                geometry.member_forces_newtons(document)
            except Exception as error:
                raise HTTPException(400, str(error))
        elif kind == "compas":
            if not isinstance(document, dict) or "thrustMesh" not in document:
                raise HTTPException(
                    400, "a compas export must contain a thrustMesh key")
            # Fix 1 / Fix 4: a null or non-finite coordinate is corrupt
            # data, not merely "no analysis yet" -- this check runs BEFORE
            # anything is written below, so the whole upload is refused and
            # nothing is left on disk (no stored compas without its
            # invalidation having run, because nothing is stored at all).
            # Every OTHER derive_contract failure (missing thrustMesh.data,
            # a non-JSON string, a non-contiguous vertex range, a missing
            # x/y/z key, ...) keeps P4's own soft-continue contract in the
            # write step below: the compas file is still stored, only the
            # derivation is skipped, named in the response
            # (test_compas_upload_with_unreadable_thrust_mesh_stores_but_
            # does_not_derive pins exactly this).
            contract_path = bundle.UPLOAD_DIR / "{}-contract.json".format(name)
            if not contract_path.is_file():
                try:
                    derived_contract = derive_contract.derive_contract(document)
                except derive_contract.MalformedGeometryError as error:
                    raise HTTPException(400, str(error))
                except ValueError as error:
                    derivation_error = str(error)
        else:
            # An authored cutting sidecar (the plugin Export component's
            # Tessellation format). Shape-checked here; the deep per-cell
            # validation stays where it always was, tessellation.
            # from_document at cut time, where a malformed cell is a 400
            # naming the cell (see bundle.CutRefused's docstring).
            if (not isinstance(document, dict)
                    or not isinstance(document.get("cells"), list)
                    or not document["cells"]):
                raise HTTPException(
                    400,
                    "a tessellation export must carry a non-empty cells "
                    "list")
            if not str(document.get("schema", "")).startswith(
                    "bench.tessellation"):
                raise HTTPException(
                    400,
                    "a tessellation export must declare a "
                    "bench.tessellation schema")
            has_partner = any(
                (bundle.UPLOAD_DIR / "{}-{}.json".format(name, half)).is_file()
                for half in ("contract", "compas"))
            if not has_partner:
                raise HTTPException(
                    400,
                    "no export named {} exists yet; upload its form "
                    "export first, then the tessellation".format(name))

        # bundle.UPLOAD_DIR, not a module-level copy, so make_client's
        # monkeypatch of bundle.UPLOAD_DIR lands here too.
        directory = bundle.UPLOAD_DIR
        directory.mkdir(parents=True, exist_ok=True)
        filename = "{}-{}.json".format(name, kind)
        (directory / filename).write_text(json.dumps(document), encoding="utf-8")

        # P4 (presentation batch, 2026-08-18): a compas-only upload becomes
        # a usable, geometry-only study on its own -- Param's ask was
        # literally "i just need to upload the one import only". Only when
        # NO contract exists yet for this name: a derived file must never
        # shadow a real one, and this is the whole guarantee -- the write
        # below never runs while contract_path already exists, whether
        # that file is a real, authored contract OR an earlier derivation,
        # and the "contract" branch above is the only other writer of that
        # path and always overwrites unconditionally, so a real contract
        # uploaded later for the same name always wins outright, no
        # marker check needed on that side.
        #
        # derived_contract/derivation_error were computed above, BEFORE
        # this write, by the same call this comment used to describe here
        # (fix 1 / fix 4 moved it earlier; see that block's own comment).
        if kind == "compas" and derived_contract is not None:
            (directory / "{}-contract.json".format(name)).write_text(
                json.dumps(derived_contract), encoding="utf-8")

        _invalidate_studio_cache(slug)
        other_kind = "compas" if kind == "contract" else "contract"
        other = directory / "{}-{}.json".format(name, other_kind)
        # An authored tessellation sidecar survives a re-upload and keeps
        # winning over the generated cut, so a pattern authored against the
        # PREVIOUS geometry silently stays in force against the new one. It
        # is not deleted here (it is the author's file, and re-uploading a
        # contract is not a request to throw their pattern away) but it is
        # named in the response, so a re-upload that quietly keeps using an
        # old cut is at least visible from the route that caused it.
        sidecar = bundle.tessellation_sidecar(name)
        return {
            "stored": filename,
            "pair_complete": other.is_file(),
            "authored_tessellation": sidecar.name if sidecar.is_file() else None,
            "derived_contract": derived_contract is not None,
            "derived_support_count": (
                derived_contract["provenance"]["support_count"]
                if derived_contract else None
            ),
            "derivation_error": derivation_error,
        }

    @app.put("/api/uploads/columns/{filename}")
    async def upload_columns(filename: str, request: Request):
        if "/" in filename or "\\" in filename or ".." in filename or ":" in filename:
            raise HTTPException(400, "bad column filename")
        if not _contained(COLUMNS_DIR, filename):
            raise HTTPException(400, "bad column filename")
        if not filename.endswith(".json"):
            raise HTTPException(400, "column filename must end in .json")
        body = await request.body()
        try:
            document = json.loads(body)
        except json.JSONDecodeError:
            raise HTTPException(400, "not valid JSON")
        mesh_shape = (
            isinstance(document, dict) and "vertices" in document and "faces" in document
        )
        contract_shape = (
            isinstance(document, dict)
            and "equilibrium" in document and "formGraph" in document
        )
        if not (mesh_shape or contract_shape):
            raise HTTPException(
                400,
                "columns file must have 'vertices'+'faces' or "
                "'equilibrium'+'formGraph' keys",
            )
        COLUMNS_DIR.mkdir(parents=True, exist_ok=True)
        (COLUMNS_DIR / filename).write_text(json.dumps(document), encoding="utf-8")
        return {"stored": filename}

    def frames_dir(run_id: str) -> Path:
        # Validation stays against STUDIES_DIR (the slug must be a real
        # study), but the frames themselves land under RECORDINGS_DIR:
        # machine-local state, outside the repo and outside OneDrive's
        # sync scope, whose churn throttled a live recording to a crawl
        # (2026-08-18).
        if run_id.startswith("study-"):
            slug = run_id[len("study-"):]
            if "/" in slug or "\\" in slug or ".." in slug:
                raise HTTPException(400, "bad study slug")
            if not (bundle.STUDIES_DIR / slug).is_dir():
                raise HTTPException(404, "no study {}".format(slug))
            return bundle.RECORDINGS_DIR / slug / "frames"
        run = RUNS.get(run_id)
        if run is None:
            raise HTTPException(404, "no run {}".format(run_id))
        return bundle.RECORDINGS_DIR / run["slug"] / "frames"

    @app.post("/api/frames/{run_id}")
    async def post_frame(run_id: str, request: Request, frame: int = Query(...)):
        directory = frames_dir(run_id)
        directory.mkdir(parents=True, exist_ok=True)
        if frame == 1:
            # A shorter re-recording must not inherit the previous take's
            # tail: ffmpeg globs frame-*.png in numeric order and stitches
            # whatever is on disk, so a stale frame-000047.png from a longer
            # first take would silently survive into the new video.
            for stale in directory.glob("frame-*.png"):
                stale.unlink()
        body = await request.body()
        (directory / "frame-{:06d}.png".format(frame)).write_bytes(body)
        return {"frame": frame}

    @app.post("/api/frames/{run_id}/stitch")
    def stitch(run_id: str, fps: int = Query(60)):
        directory = frames_dir(run_id)
        if not directory.is_dir() or not any(directory.glob("frame-*.png")):
            raise HTTPException(404, "no frames recorded for run {}".format(run_id))
        if not _ffmpeg_present():
            raise HTTPException(
                503, "ffmpeg is not on PATH; frames are in {}".format(directory))
        video = directory.parent / "recording.mp4"
        completed = subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps),
             "-i", str(directory / "frame-%06d.png"),
             "-pix_fmt", "yuv420p", str(video)],
            capture_output=True, text=True,
        )
        if completed.returncode != 0:
            raise HTTPException(500, "ffmpeg failed: {}".format(
                completed.stderr[-2000:]))
        return {"video": str(video)}

    @app.get("/")
    def index():
        # The script URL carries studio.js's own mtime, so a fresh page
        # always names a URL the browser has never cached: Cache-Control
        # revalidation (below) turned out not to be enough on its own --
        # Chromium's heuristic cache served a stale module script across
        # plain refreshes even after the HTML itself came back fresh
        # (2026-08-18, live: the import banner spoke a message the new
        # client no longer contains, twice).
        # Guard before stat (fix 3, 2026-08-19 fix batch): stat() used to run
        # on studio.js before anything checked it existed, so a missing
        # static asset answered an opaque 500 naming nothing. Both files are
        # named explicitly here, honestly, before either is touched.
        index_path = STATIC_DIR / "index.html"
        script_path = STATIC_DIR / "studio.js"
        if not index_path.is_file():
            raise HTTPException(
                500, "the studio's index.html is missing from {}".format(STATIC_DIR))
        if not script_path.is_file():
            raise HTTPException(
                500, "the studio's studio.js is missing from {}".format(STATIC_DIR))
        html = index_path.read_text(encoding="utf-8")
        stamp = str(int(script_path.stat().st_mtime))
        html = html.replace(
            "/static/studio.js?v=dev", "/static/studio.js?v=" + stamp)
        return HTMLResponse(html)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # The studio ships fixes faster than browsers expire their heuristic
    # cache: a plain refresh after a server update served the NEW
    # index.html with the OLD studio.js (2026-08-18, live: the import
    # banner spoke a message the new client no longer contains).
    # no-cache does not mean no caching, it means revalidate: StaticFiles
    # answers If-Modified-Since with a cheap 304 while the file is
    # unchanged, and a plain refresh is always enough after a deploy.
    @app.middleware("http")
    async def static_revalidates(request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    return app
