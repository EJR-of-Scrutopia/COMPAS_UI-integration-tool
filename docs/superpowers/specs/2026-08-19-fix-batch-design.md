# Fix batch: the parked register, triaged and closed

Date: 2026-08-19. Param's word: "keep going on the next fixes." The
register assembles from the 2026-08-18 review sweep's parked findings
(.superpowers/sdd/2026-08-18-review-sweep/parked.md), this session's
wave riders, and the parked minors. Branch feature/fix-batch STACKED on
feature/cut-cancellation c71ba18 (the stack merges oldest-first or as
one fast-forward; this wave touches bundle.py, which activates the
recorded rider below).

## Triage (controller ruling, recorded)

TAKEN -- silently-wrong-numbers, opaque-error, path-safety, and honesty
items, all small and testable (the twelve fixes below). SKIPPED with
reasons: reframe-vs-turntable (Wave B scoped, Param's queue); derived
contracts written into the demo folder, sidecar-partner semantics, and
the demo-deletion working tree (Param's own design/data decisions);
middleware FileResponse wrapping, uncut-recompute-per-GET (by design,
noted in the sweep); ?v=dev placeholder (test-pinned, cosmetic); T2 M8
traceback cosmetics (ruled not worth churn); two-tab 409 banner
(spec-scoped out of cut cancellation); the notch-lobe remainder piece
(a feature, queued). The plugin repo's sweep minors (Courses bounds,
try/catch parity, serializer options) are a SEPARATE small wave in the
plugin repo, after this one -- they carry a .gha rebuild+install cycle.

## The twelve fixes

### Upload and derivation hardening (app.py, derive_contract.py)

1. derive_contract lets TypeError escape on a null coordinate (app.py
   ~369): an opaque 500, with the compas file already stored and cache
   invalidation skipped. FIX: catch the malformed-geometry failure at
   the derive step and return a named 400 ("the thrustMesh has a null
   coordinate at vertex {id}" or the closest honest message the code
   can produce); the upload must NOT leave partial state (no stored
   compas without its invalidation having run -- order the operations
   or clean up on failure; state which in the report).
2. The export-name safety check omits ":" and skips _contained (app.py
   ~291): a drive-relative name like "C:foo" escapes UPLOAD_DIR. FIX:
   reject ":" in export names alongside the existing rejects AND run
   the _contained check the sibling routes use. Test with "C:evil" and
   a ".." variant.
3. GET "/" 500s when studio.js is missing (app.py ~497: stat before
   the existence guard). FIX: guard first, honest 500-with-message or
   404 naming the missing asset. Small.
4. A bare NaN survives json.loads into the derived contract
   (derive_contract.py ~106) and 500s later at bundle serialisation.
   FIX: reject non-finite coordinates at derive time with a named 400
   counting the offending values.
5. Re-import under the same name keeps stale fea-verification.json
   (app.py ~59, _invalidate_studio_cache): SILENTLY WRONG NUMBERS
   after a geometry change. FIX: the invalidation deletes
   fea-verification.json for the slug (and any sibling verification
   artifacts the studies dir carries for it -- enumerate what exists
   in the code and cover it). Test: re-upload changes geometry, old
   verification is gone from the next bundle.
6. slugify collision (geometry.py ~26): "Foo Bar" and "foo-bar" share
   one slug, so two exports share bundle/staging paths -- data mixing.
   FIX: do NOT change slugify (existing study dirs must keep their
   identity); instead the upload route refuses a NEW export whose slug
   collides with a DIFFERENT existing export name, with a named 400
   listing both names. Track the owning export name per slug (the
   studies dir already stores per-slug state; record the export name
   in it or derive from what is stored -- read the code and pick the
   honest source). Same-name re-upload stays allowed.

### Bundle honesty (bundle.py, domain.py, generators.py, openings.py)

7. CutRefused wraps ANY ValueError from plan_domain/generate (bundle.py
   ~283 in the pre-wave numbering): a genuine math bug reads as a
   polite engine refusal. FIX: a shared exception type -- new module
   bench/studio/refusals.py with `class PlanRefused(ValueError)` and a
   one-paragraph docstring; every CURATED refusal site in domain.py,
   generators.py, openings.py raises PlanRefused (the messages are
   pinned by tests and MUST NOT change -- PlanRefused is a ValueError
   subclass so every existing message pin stays green); bundle's
   generated-path catch narrows to PlanRefused -> CutRefused; any
   other exception propagates as the genuine bug it is. Test: a
   monkeypatched generate raising a plain ValueError("boom") is NOT
   converted to an uncut bundle.
8. _render_mesh silently drops subdivision for the whole mesh when any
   single face is non-quad (bundle.py ~347 pre-wave): FIX by
   disclosure, not behaviour: a provenance/report note
   ("render_subdivision": "skipped -- {n} non-quad faces" vs
   "applied") riding the bundle the way other notes do.
9. build_bundle's disk write is not generation-guarded (the
   cut-cancellation final review's rider; pre-wave defect): a build
   that survived a mid-build re-upload can write its stale document to
   disk AFTER the invalidation ran. FIX: capture the generation before
   the build, re-check under _cut_memo_lock immediately before the
   write, skip the write (serve the result to the caller, uncached) on
   mismatch. Test with the Event-handshake pattern the cut-canc tests
   established.
10. tests/studio/conftest clears the cut memo between tests but not
    the new in-flight/interactive registries: FIX the conftest to
    clear them too (a tiny reset helper in bundle.py if none exists),
    so cross-test leakage cannot produce order-dependent flakes.

### Client honesty (studio.js, test_static.py)

11. derivation_error is returned by the server but never shown
    (studio.js ~2934 pre-wave): a malformed thrustMesh reads as "pair
    incomplete". FIX: surface derivation_error in the import panel's
    banner path verbatim; static-pin it.
12. The SELECT_SETTLE_MS block comment is unpinned (cut-canc Minor):
    add the missing static pin. One line.

## Acceptance

Every fix lands with a test that fails on the pre-fix code (state the
red proof per fix in the report); the full suite green; the Armadillo
acceptance unchanged; no em dashes; explicit-path commits; NEVER push.
The stack invariant holds: this branch merges after cut-cancellation.

## Out of scope

Everything in the SKIPPED list above, each with its recorded reason;
the plugin-repo minors (next, separately); BENCH.md's stale
cutting_measurements row (needs that script re-run against the retired
export path -- goes with the plugin wave or a docs pass, controller's
discretion).
