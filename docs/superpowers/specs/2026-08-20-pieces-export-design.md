# Pieces export: the cut blocks travel to Grasshopper

Date: 2026-08-20, Param's own design ("export json, which exports the
cut blocks, object as they are... which we then turn with grasshopper
into readable geometry... drop the entire end cut objects, exactly
same size etc, to grasshopper as a list the same way we provided a
list 0 height and up order"). Purpose: cataloguing and digital
fabrication live in Grasshopper; this is the bridge, and the
prerequisite for the ROS2 placement phase after it. Two repos:
UI (branch feature/pieces-export off main e0f7f31) and plugin
(branch feature/import-pieces off main ea1e851).

## The design in one paragraph

The studio gains a pieces export: a route that takes the same
study/material/pattern/size/thickness parameters as the bundle,
extrudes every piece to its FINAL solid server-side with exactly the
client viewer's own algorithm, and writes a versioned
"bench.pieces/1" JSON beside the study, returning the absolute path
(the recordings precedent: a local tool tells you where the file is).
A new plugin component, Import Pieces, reads that file and outputs
aligned lists -- one Rhino mesh per block plus its course, key, and
support flag -- in the export's own order, which IS the studio's drop
order (course ascending from the rim, anticlockwise within a course).
Grasshopper receives finished geometry; it never re-derives any of it.

## The geometry truth (binding formulas)

The server piece record is intrados-only; the final solid is built
today by the CLIENT (studio.js buildPieceMeshes, ~3709-3905). The
export ports that algorithm to a new stdlib module
bench/studio/piece_solids.py, verbatim in both branches:

- Jointed piece WITH seat_plane (origin o, unit normal n), thickness
  t: for each of the count cap points m[i], d = (m[i]-o).n and
  belly[i] = m[i] - d*n (the cap flattened onto the plane); the
  vertex array is [belly[i] + n*t for i in 0..count-1] (top) followed
  by [belly[i] for i] (bottom) -- both caps flat and parallel, offset
  along the PLANE normal.
- Piece WITHOUT seat_plane: vertex array is [m[i] + normals[i]*t]
  (top) then [m[i]] (bottom) -- per-vertex normal offset, curvature
  kept.
- faces: the piece's own topology REUSED VERBATIM (it already indexes
  the doubled 2*count space: top cap triangles, bottom cap triangles
  reversed, wall quads for every chain incl. holes). No topology is
  rebuilt anywhere.

DELIBERATE CONTRACT DECISIONS (rulings, recorded):
- joint gap = 0 and taper = 0 ALWAYS. The viewer's default render
  shrinks every piece by a cosmetic 0.5 mm joint gap and can taper
  thickness per course; neither ever reaches the server today and
  neither belongs on fabrication solids -- "exactly same size" means
  the true touching blocks. The document states "joint_gap": 0.0 and
  "taper": 0.0 explicitly so the contract is visible; a taper query
  parameter is a recorded deferral if Param ever wants tapered
  exports.
- Thickness is the route parameter (same bounds as the bundle route,
  default 0.2), stamped into the document; the same cut extrudes at
  any thickness.
- Vertices ship exactly as materialized: 2*count points per piece,
  caps NOT welded to each other (thickness >= 0.05 m keeps them
  disjoint), within-cap sharing preserved by the index space. The
  Grasshopper side builds meshes verbatim and performs NO weld pass.

## The document ("bench.pieces/1")

{
  "schema": "bench.pieces/1", "units": "m",
  "export": <name>, "material": ..., "pattern": ..., "size": <m>,
  "thickness": <m>, "joint_gap": 0.0, "taper": 0.0,
  "generated": <iso timestamp>,
  "courses": <int>, "piece_count": <int>,
  "degenerate_dropped": [keys...],
  "pieces": [
    {"key": "c3p14", "course": 3, "is_support": false,
     "vertices": [[x,y,z] x 2*count],
     "faces": [[i,j,k] | [i,j,k,l] ...],
     "seat_plane": {"origin": [x,y,z], "normal": [x,y,z]} or null,
     "seat_gap": <m> or null},
    ...]
}

Order contract: pieces appear in BUNDLE ORDER, untouched -- the
studio's own drop order, cells sorted (course ascending from the rim,
angle anticlockwise about the cut centroid). The plugin outputs
preserve this order verbatim in every aligned list. courses are 0-up
from the rim: the "0 height and up" convention Param named.

Integrity requirements, tested server-side per piece: the mesh is
CLOSED (every undirected edge used exactly twice, with opposite
orientations) and has POSITIVE signed volume (divergence theorem) --
the winding-convention proof the assessment called for, made a
permanent test rather than an assumption.

## The route and UI (UI repo)

- POST /api/studies/{export}/pieces-export with the bundle route's
  query parameters (material, pattern, size, thickness; same
  validation via _validate). Behaviour: load_or_build_bundle (shared
  cache), then piece_solids over bundle["pieces"], then write the
  document to STUDIES_DIR/<slug>/studio/<export>-pieces.json
  (overwrite allowed -- regeneration is the point), return 200
  {"path": <absolute path>, "piece_count": n, "courses": c}.
- An UNCUT study (uncut_reason set, pieces empty) answers 409 with
  {"uncut_reason": <verbatim>} -- there are no blocks to export and
  the reason says why.
- Export-name safety: the same ":"/_contained guard as every route.
- UI: an "Export pieces (JSON)" button beside the existing data/record
  controls; on success the status line shows the returned absolute
  path (the recordings pattern); on 409 the uncut reason shows.
  Static pins in the house grep style.

## The component (plugin repo)

"Import Pieces", nickname "Pieces", category Delivery (07), fresh
GUID, never reused. Inputs: P (File Path, item -- a bench.pieces/1
file; folder resolution mirroring ResolveWritePath's file-or-folder
handling in reverse is NOT needed: a file path only, wave 1).
Outputs: M (mesh, list), C (course, list int), K (key, list string),
S (support, list bool), D (diagnostics, item text: schema, units,
counts, thickness, degenerate_dropped, and a mismatch warning if any
piece failed to build).

Behaviour: JSON parsing runs off the solve thread in the house
NativeTaskComponentBase pattern, producing plain-number arrays;
Rhino.Geometry.Mesh construction happens in the post phase ON the
solve thread (the house threading rule), following the
TnaResultGeometry.ThrustMesh pattern (AddFace for 3/4-corner faces,
ComputeNormals, Compact). Schema/units validated (schema must be
bench.pieces/1, units "m"; a mismatch is a component Error naming
what was found). The active Rhino document's unit system is NOT
assumed to be metres: the component scales points by the document's
metres-to-model-units factor (RhinoDoc units), and D discloses the
factor applied. Errors surface via the sync-sibling try/catch shape
(the parity fixed in the sweep-minors wave).

Harness coverage (native_smoke, its reflection pattern): the new
component's params contract; a static parse helper driven with a
small fixture document asserting counts, order preservation, and the
schema/units refusals. Live mesh building is verified by Param on
canvas (the harness never launches Rhino).

## Acceptance

- UI: unit tests for both extrusion branches with hand-computable
  fixtures (a flat square piece with/without seat plane: exact
  expected vertices); closed+positive-volume for every piece on the
  tiny fixture AND the real Armadillo (840 pieces, skip-guarded);
  route tests (200 + file + schema shape + order = bundle order;
  409 uncut; name guard); static pins for the button.
- Plugin: dotnet build 0 warnings; pytest suite untouched green;
  native_smoke extended and passing; .gha REBUILT, install pending
  with the controller (Rhino state unknown at build time).
- Cross-repo: a fixture bench.pieces/1 document generated by the UI
  side's real code is committed to the PLUGIN repo's test assets and
  parsed by the harness check (the same cross-repo pattern 6c used).
- Both suites green; no em dashes; explicit-path commits; NEVER push.

## Out of scope (recorded)

- Taper/gap as export parameters (deferral above).
- A GH component fetching from the running server over HTTP (file
  path only, wave 1).
- The progress bar (the agreed next wave, separate).
- ROS2 placement (the phase after this bridge exists).
- DXF/SVG flattened templates (superseded by Param's design).
