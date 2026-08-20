# Pieces Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The studio exports the final cut blocks as bench.pieces/1 JSON (server-extruded, true touching solids); a new Grasshopper component imports them as aligned mesh/course/key/support lists in drop order.

**Architecture:** A stdlib extrusion module (piece_solids.py) porting the client's two-branch algorithm verbatim; a POST route writing the document beside the study; a UI button showing the path; plugin-side an Import Pieces component (off-thread parse, solve-thread mesh build) plus harness contract checks on a cross-repo fixture.

**Tech Stack:** Python stdlib (UI repo), C# net8.0-windows GH component (plugin repo), pytest + native_smoke.

**Spec:** docs/superpowers/specs/2026-08-20-pieces-export-design.md (binding: the extrusion formulas, the contract decisions incl. gap/taper zero, the document schema, the order contract, the integrity tests)

## Global Constraints

- UI repo: "C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-UI-integration-tool", branch feature/pieces-export off main e0f7f31. Plugin repo: "C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS Workflow", branch feature/import-pieces off main ea1e851. Paths contain spaces: always quote.
- UI suite: `"C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-Workflow-bench\.venv\Scripts\python.exe" -m pytest tests/studio -q` from the UI repo root. Plugin: `dotnet build plugin/native_v02/Ananke.COMPAS.Native.csproj -c Release` (0 warnings), `".venv\Scripts\python.exe" -m pytest tests -q` from the plugin root, native_smoke run per its own usage.
- The extrusion formulas are BINDING as spec'd (ported from studio.js buildPieceMeshes ~3730-3779; the reviewer verifies the transcription against the JS source line by line).
- Pure stdlib in bench/studio; red-first tests; no em dashes (U+2014) -- python byte-scans; no AI attribution; explicit-path commits (both repos carry unrelated working-tree noise); NEVER push.

---

### Task 1 (UI repo): piece_solids.py -- the extrusion, proven closed and positive

**Files:**
- Create: `bench/studio/piece_solids.py`
- Test: `tests/studio/test_piece_solids.py`

**Interfaces:**
- Produces: `solidify(piece: Dict, thickness: float) -> Dict` returning {"vertices": [[x,y,z] * 2*count], "faces": <piece["faces"] verbatim>} per the spec's two branches (seat_plane present -> flatten-onto-plane + plane-normal offset; absent -> per-vertex normal offset; top block first, bottom second, matching the client's [full, 0] order); `verify_solid(vertices, faces) -> Dict` returning {"closed": bool, "volume": float} (every undirected edge used exactly twice with opposite orientations across triangles AND quads' implied edges; signed volume by the divergence theorem over fan-triangulated faces).

- [ ] Red-first unit tests: (a) a hand-built flat unit-square piece WITHOUT seat_plane (4 outline verts + known normals): exact expected 8 vertices asserted literally; (b) the same piece WITH a tilted seat_plane: belly = projections onto the plane, top = belly + n*t, exact values; (c) verify_solid on the built solids: closed True, volume == area*thickness within 1e-9; (d) a deliberately holed topology (drop one wall quad): closed False.
- [ ] Implement to green; full suite; commit `feat(pieces): the client's extrusion, server-side and proven watertight`.

### Task 2 (UI repo): the route, the document, the button

**Files:**
- Create: none beyond Task 1
- Modify: `bench/studio/app.py` (the POST route), `bench/studio/bundle.py` ONLY if a helper for the studies-dir path is needed (prefer reusing bundle_path's conventions), `bench/studio/static/studio.js` + `bench/studio/static/index.html` (the button + status)
- Test: `tests/studio/test_app.py`, `tests/studio/test_static.py`

**Interfaces:**
- Consumes: Task 1's solidify/verify_solid; load_or_build_bundle; the existing _validate and name guards.
- Produces: POST /api/studies/{export}/pieces-export (bundle query params) -> 200 {"path", "piece_count", "courses"} with the document written to STUDIES_DIR/<slug>/studio/<export>-pieces.json; 409 {"uncut_reason"} for uncut studies; the document exactly per the spec's schema incl. joint_gap/taper 0.0, degenerate_dropped, pieces in bundle order with seat_plane/seat_gap carried (null when absent). Every exported piece passes verify_solid (closed + volume > 0) -- a failing piece is a 500-class genuine bug, not silently skipped.
- The "generated" timestamp: tests must not pin it; use the house time source.

- [ ] Red-first route tests: 200 + file exists + schema fields + piece order equals the bundle's pieces order (compare keys) + vertices count == 2x the bundle piece's mid count + closed/volume spot-check via Task 1's verifier; 409 on an uncut study carrying the verbatim reason; the ":"/_contained name guard; thickness parameter respected (two exports at different thickness differ only in the offset). Static pins: button id, the path-display marker, the 409-reason display marker.
- [ ] Armadillo acceptance extension (skip-guarded like the existing one): run the export for the real study, assert 840 pieces, all closed, all positive volume, order matches, file written. Quote the numbers.
- [ ] Implement to green; full suite; commit `feat(app): the cut blocks export as bench.pieces/1`.

### Task 3 (plugin repo): the Import Pieces component

**Files:**
- Create: `plugin/native_v02/Components/PiecesComponents.cs` (ImportPiecesComponent), a fixture document under tests/native_smoke's asset conventions (generated by the UI side's REAL code -- Task 2's test writes a small fixture; copy it into the plugin repo and note its provenance in a comment)
- Modify: `tests/native_smoke/Program.cs` (params contract + parse-helper checks)

**Interfaces:**
- Consumes: bench.pieces/1 files.
- Produces: the component per the spec (P in; M/C/K/S/D out; off-thread parse to plain arrays, solve-thread mesh build via the ThrustMesh pattern; schema/units validation errors; RhinoDoc unit scaling disclosed in D; sync-sibling try/catch shape; fresh GUID; category 07 Delivery).

- [ ] Implement; `dotnet build` 0 warnings; native_smoke extended (params contract; the static parse helper on the committed fixture: piece count, order preservation, schema/units refusal messages) and passing; plugin pytest suite untouched green.
- [ ] Em-dash scans both repos' touched files; commit `feat(plugin): Import Pieces -- the cut blocks land on canvas`.
- [ ] REBUILD the .gha (build only; the controller handles install with Param).

## Final verification (controller)

Both suites green; the Armadillo export numbers in the ledger; the cross-repo fixture provenance clean; final whole-branch review (strong model) covering BOTH repos' branches together; ONE fix wave; branches left merge-ready for Param (or merged on his standing word if he has given one by then -- the controller checks the conversation, not assumptions).
