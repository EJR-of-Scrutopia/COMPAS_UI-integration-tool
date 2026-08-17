# Cutting Truth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Blocks sit ON the formwork (surface = intrados, thickness up), jointed pieces become straight-tool prismatic blocks with disclosed seat gaps, and the rim's crescent notches die by nearest-boundary projection.

**Architecture:** Survey-first: Task 1 maps the piece pipeline (server outline/lift code, bundle schema, client extrusion in buildPieceMeshes) and freezes baselines, because the engine moved repos and offsets span server and client. Tasks 2-4 implement K1/K2/K3 against that map with contracts below; Task 5 re-shoots the evidence and documents.

**Tech Stack:** Python (FastAPI server, pieces/cutting modules), three.js client, pytest, node for fields tests, the probe rig (puppeteer-core + Brave).

**Spec:** docs/specs/2026-08-17-cutting-truth-design.md

## Global Constraints

- Repo: this repo (COMPAS_UI-integration-tool), branch feature/cutting-truth. Suites from the repo root with the launcher venv or the old worktree venv: `python -m pytest tests/studio -q`.
- Commit per task; never push. No em dashes (U+2014; ASCII "--" fine in comments); no attribution; studio.js functions at column 0; double quotes in JS.
- The analysis is untouched: thrust surface, forces, FEA identical; only the solid around the surface changes.
- Purity/offline rules as pinned. Fix tasks cite Task 1's map or the spec; contract-driven steps name what they found (diagnosis-first precedent).
- The 2x-time / 3x-payload budget gate binds K3 (and K2 payload if prism data grows the bundle: measure and state).

---

### Task 1: Survey and baselines

**Files:** none shipped except a fixture if needed; outputs to the wave workspace (.superpowers/sdd/2026-08-17-cutting-truth/).

- [ ] Map, with file:line evidence, into `<workspace>/engine-map.md`: (a) where piece outlines are lifted (Surface.lift / radius_at in the cutting module) and where corner residuals/clamp stats are computed; (b) exactly what the bundle ships per piece (mid points? normals? outline? course) and where the SOLID is built (client buildPieceMeshes extrusion vs server); (c) every client offset that assumes the mid-surface convention: falsework ghost, net display clearance (applyShowMode/applySceneAtTime), arrowField lift, anything else grepping provenance.thickness finds; (d) how sprayed differs (weld, zero gap, scale-about-centroid).
- [ ] Baselines: run the server, fetch the real export's bundle at 0.9 m (the Algebraic TNA study if present in bench/studies, else the Tiny fixture plus SAY SO), record clamped_points/median/max and bundle payload bytes and cut wall time into the map. Probe screenshots: the belly/underside from Param's viewpoint, the rim close-up.
- [ ] If no doubly-curved compact fixture exists for geometry tests, add one under tests/fixtures (a small saddle contract) with a note. Commit only that.

### Task 2: K1, the surface becomes the intrados

Contract (implement per the map; name every deviation):
- [ ] Server: provenance gains `"surface": "intrados"`; any server-side solid/stat that assumed mid-surface updates.
- [ ] Client: buildPieceMeshes extrudes UP: bottom face on the lifted surface, top at +thickness along the local normal (taper scales thickness as today). Sprayed builds upward too, keeping its curved moulded geometry.
- [ ] Offset sweep with pins updated and the K1 convention named in each: formwork ghost directly under the surface (drop the half-thickness), net clearance in Both/pre-strike timeline re-derived (the net now lives at the shell's BOTTOM: likely no lift needed above the belly, but the extrados is a full thickness up; derive, probe-verify at the crown, state the final rule), load arrows lift by full thickness to reach the extrados.
- [ ] Server tests: a piece's minimum offset from the surface is >= 0 (nothing below the intrados) on the fixture; studio pins for the swept offsets; suite green; probe re-shot of Param's screenshot viewpoint showing blocks ABOVE the net. Commit.

### Task 3: K2, prismatic blocks for jointed materials

Contract:
- [ ] Seat plane per jointed piece: least-squares plane through the piece's lifted outline points, oriented outward. Where the plane math lives follows the map (server preferred so the report can disclose; if client, the fit goes into fields.js as a pure node-tested function and the STATS still come from the server).
- [ ] Geometry: belly = outline projected to the seat plane; top = seat plane + thickness (taper-scaled); sides ruled straight. Joint gap insets within the seat plane as today.
- [ ] Sprayed: UNCHANGED curved solid (regression pin: sprayed pieces keep nonplanar bellies).
- [ ] Disclosure: per-piece seat gap (max distance surface-to-plane over the piece) in the tessellation report; worst/median in the Data panel beside corner residuals; BENCH-style honesty sentence.
- [ ] Tests: belly/top planarity <= 1e-9 and constant thickness on the fixture; seat-gap monotone with piece size on the saddle fixture; payload delta measured against Task 1's baseline and inside the 3x gate (state the number). Probe: stepped-course close-up. Commit.

### Task 4: K3, the rim by geometry

Contract:
- [ ] Outline points outside the surface's support project to the NEAREST point of the analysis-mesh boundary polyline in plan (replacing the outermost-crossing clamp for those points); course 0's outline simplifies against the boundary with the cut's existing edge tolerance.
- [ ] Measured on the fixture AND the real export at 0.9 m: clamped-point count to zero-or-near (record before/after numbers), cut time within 2x of Task 1's baseline, payload within 3x. If any number blows the gate, STOP the task and surface the measurement (spec's gate).
- [ ] Probe: rim close-up before/after. Existing rim disclosures (BENCH known-limits) updated to the new truth. Commit.

### Task 5: Evidence and documentation

- [ ] Full probe pass: Param's viewpoint, stepped courses, rim, sprayed regression shot; suite full-green; BENCH.md (in this repo) updated for K1/K2/K3 with the honesty sentences; README touched only if the workflow text mentions piece geometry. Commit.

## Final verification (controller)

Suites green; every K-decision's measurement recorded in the ledger; manual checklist for Param: blocks on top of the formwork from his screenshot's angle, prismatic stepping legible up close, seat-gap stats visible in Data, rim clean at 0.9 m, sprayed still smooth.
