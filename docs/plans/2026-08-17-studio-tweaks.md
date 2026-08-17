# Studio Tweaks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Param's six tweaks: ghost/staircase diagnosed and fixed, appearance simplified (skins die, Gloss to matt), 16K HDRIs load via half-float, Studio darkness at low brightness, a flat centred turntable, and ground tint/scale.

**Architecture:** Diagnose-first for W1 (probe captures name the causes); the rest are contract-driven edits over known code with pins. All client-side except nothing: no server changes expected (the HDRI fix is decode-side).

**Tech Stack:** three.js 0.185 vendored, the probe rig (puppeteer-core + Brave), pytest + node.

**Spec:** docs/specs/2026-08-17-studio-tweaks-design.md

## Global Constraints

- Repo: this repo, branch feature/studio-tweaks. Suite: `python -m pytest tests/studio -q` from the repo root with the worktree venv ("C:\Users\Param\OneDrive - Ananke-eidos\Documents\Ananke Eidos Studio\VS code\COMPAS-Workflow-bench\.venv\Scripts\python.exe") or the launcher venv.
- Commit per task; never push. No em dashes (U+2014; ASCII "--" fine); no attribution; studio.js functions at column 0; double quotes.
- Purity: applyGrade/applyEnvironment/applyDayCycle/applyTimeline/applySceneAtTime clock-free; frame() the only advancer. Offline rule unchanged; fields.js three/DOM-free.
- W1 fixes cite the probe capture naming the cause (diagnosis-first precedent).
- The probe rig: bench/scripts/studio_probe.mjs pattern, puppeteer-core in bench/scripts/probe-env, Brave at "C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe", window.__studio = { state, scene, camera, controls, applyDayCycle }. Server: serve.py with ANANKE_DEMO_BOOTSTRAPPED=1, BENCH_STUDIO_PORT as needed; kill what you start.

---

### Task 1: W1 diagnosis and fixes (ghost + staircase)

- [ ] Probe-reproduce Param's screenshot state: load a real export (Algebraic TNA method or Trial 2), timber material, play the timeline to roughly two-thirds, capture from his viewpoint. Identify with scene readings via __studio: (a) WHAT the dark under-shell surface is (read state.formworkMode, state.objects.falsework visibility/opacity/z, state.showMode, and each candidate's material) and (b) WHERE the zigzag ribbon blocks belong (pick 3 ribbon blocks by raycast or by scanning segment positions for z above the crown; read their userData.key, course, drop window start = position * placementStep(), and compare against their rest geometry). Write both diagnoses with numbers into the workspace diagnosis file BEFORE fixing.
- [ ] Fix each by cause, minimally, with a pin where pinnable. Plausible causes to check (not conclusions): the ghost may be animation-mode falsework (then the fix honours Param's standing "rather not see it": default already Hidden, so find WHY it shows: a state restore? a mode write missed?); the ribbon may be the placement ORDER vs the drop stagger (blocks whose order index puts their drop start late spawn at DROP_HEIGHT above their rest pose: if rest poses are right but flight paths wrong, look at the drop's z interpolation for prisms; if a whole course hangs diagonally, look at placementStep vs course ordering after K3's outline changes).
- [ ] Before/after captures; suite green; commit `fix(studio): <the two diagnosed causes>`.

### Task 2: W2 appearance simplification

- [ ] Pins first: skin select gone from index.html; `SKINS` and `appearanceMaterialBase` reduced (base = the material registry entry always); the label "Gloss to matt" present; stored-appearance migration: a persisted entry with a skin key loads as tint/finish only (write the migration in restoreAppearance; pin the tolerant parse).
- [ ] Implement: remove the select + wiring; delete SKINS and the cache; pieceMaterial clones the registry entry and applies tint (color.set) + finish (roughness) as today; rename the label text (id stays material-finish); Reset clears both. Update every touched pin minimally, name each.
- [ ] Suite green; commit `feat(studio): appearance is the material plus tint, gloss to matt named honestly`.

### Task 3: W3 big HDRIs

- [ ] fields.js gains `export function halfToFloat(h)` (IEEE 754 half decode, pure; node test with hand values: 0x3C00=1, 0xC000=-2, 0x7BFF=65504, subnormal, zero) and estimateSunFromEquirect accepts a `halfFloat` flag (or detects Uint16Array) decoding sampled pixels through halfToFloat. Node tests first, failing, then green.
- [ ] loadHdri: compute pixel count from the loader result is too late for type choice; instead try FloatType and CATCH the allocation failure (RangeError) to retry with HalfFloatType, OR pre-choose by a HEAD/size heuristic; simplest robust: attempt FloatType, on failure retry HalfFloatType, on second failure banner "image too large: <n> MP, the practical ceiling is around <m> MP" (derive m from the successful path). The estimator call passes the type flag. PMREM/backdrop verified with a half-float texture (probe: load a big fixture; generating a synthetic large .hdr fixture locally is acceptable: a 12000x6000 uncompressed one is ~275 MB on disk, too big; instead verify the half-float PATH with a small file forced through HalfFloatType, and the RETRY path by monkeypatching/temporarily lowering the threshold in the probe run; state what you proved).
- [ ] Pins: the retry shape in loadHdri; the estimator flag; suite green; commit `fix(studio): 16K HDRIs decode as half float, the estimator follows`.

### Task 4: W4 studio darkness + W5 turntable

- [ ] Darkness: in the studio branch (applyEnvironment or applyGrade, wherever exposure/ambient meet: implement in applyGrade reading state.environmentMode, or in applyEnvironment: choose the site that keeps purity pins and single-writer discipline; state the choice): ambientScale = min(1, (brightness / 1.0)) ** 2 for brightness < 1 else 1; environmentIntensity = 0.6 * ambientScale; hemi.intensity = 0.5 * ambientScale; sun.intensity keeps its existing brightness relationship (exposure multiplier). At brightness 0.3 the ambient is ~0.09x: near black, sun projecting. Pins: the expressions + purity + sky/hdri branches untouched by the fade.
- [ ] Turntable: find the orbit animation (orbit-speed/orbit-distance handling in frame() or applyTimeline's camera path). Replace the camera path with: theta advances by orbitSpeed * delta; camera.position = centre + [r*cos(theta), r*sin(theta), h] where h = the camera's height at orbit start (captured once when the orbit begins) and r = orbit-distance; controls.target = centre. Centre: recompute in rebuildTimeline (or buildScene end) as the shell bounding-box centre; pin the recompute site. No z modulation anywhere in the orbit path (pin: the orbit block contains no vertical easing/modulation term).
- [ ] Probe: darkness triplet (brightness 2.0 / 1.0 / 0.3 in studio mode) and two turntable frames a half-revolution apart proving equal camera z and centred target; suite green; commit `feat(studio): studio darkness at low brightness, a flat centred turntable`.

### Task 5: W6 ground tint and scale + docs

- [ ] Ground controls in Scene under the ground select: ground-tint (color), ground-scale (range 0.25-4 step 0.05 value 1), ground-reset button; visible per preset (scale hidden for dark-studio); handlers apply to the ACTIVE preset's cached material in place (color.set; texture.repeat scaled from the preset's base repeat, both maps), persist per preset under "bench-studio-ground:" + preset, restore on preset change and boot. Pins: ids, the persistence key, the dark-studio hide rule, repeat-scaling touches both map and roughnessMap (and bumpMap where present).
- [ ] docs/BENCH.md: the appearance paragraph updated (skins gone, Gloss to matt), the HDRI size ceiling sentence, studio darkness, turntable, ground controls. Em dash check. Suite green; commit `feat(studio): ground tint and scale, the tweaks documented`.

## Final verification (controller)

Full suite green on the tip; the W1 captures and diagnosis in the workspace; manual checklist for Param: no ghost mid-build, no staircase, timber looks like timber with tint only, a 16K HDRI loads, brightness bottom = the dark single-light look, the run is a level centred turntable, ground tint/scale respond.
