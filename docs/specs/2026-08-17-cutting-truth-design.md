# Cutting truth wave: thickness up, prismatic blocks, the rim

Date: 2026-08-17, agreed with Param (his priority call for the catch-up
meeting: this wave first, then cut cancellation, then the 6b pattern
library). Runs in THIS repo (COMPAS_UI-integration-tool), the cutting
engine's home since the split. Suites: tests/studio from the repo root.

## The three defects, as agreed

1. Thickness direction: pieces currently extend below the form surface
   (screenshot: blocks hanging under the net). Material must build UP:
   the thrust/analysis surface is the INTRADOS, the face that touches
   the formwork; blocks sit on it.
2. Curved bellies: pieces are moulded to the mesh on their undersides.
   In practice they are cut with straight tools; the underside cannot
   carry the surface curvature.
3. The rim: 137 outline points clamped by radius_at's
   outermost-crossing rule (median 24.6 mm, max 52.3 mm on the real
   export at 0.9 m), producing crescent notches; plus course 0
   following all 240 analysis-mesh boundary vertices. Density measurably
   cannot fix this; the fix is rim-specific geometry (approved).

## Decisions

### K1. The form surface becomes the intrados

- Server-side piece construction changes from mid-surface plus/minus
  half thickness to: bottom face ON the lifted surface, material
  extruded UPWARD (outward along the local normal) by the full
  thickness. The analysis mesh stays the analysis mesh; only the piece
  solid's relationship to it changes, and provenance records the
  convention ("surface=intrados") so the viewer can adapt.
- Viewer consequences swept in the same wave: the formwork ghost sits
  directly under the surface (no half-thickness offset), the net
  display clearance in Both/timeline modes becomes thickness plus
  radius (the net's mid-surface home is now the bottom of the shell:
  re-derive and probe-verify), load arrows lift by the full thickness
  to reach the extrados, HUD/data text stays truthful. Every changed
  offset gets its pin updated with the K1 convention named.
- Sprayed (monolithic) material: the whole story of sprayed concrete is
  that it IS moulded on the formwork, so sprayed keeps the curved
  moulded solid, built upward from the same intrados. Flat bellies
  never apply to sprayed.

### K2. Prismatic blocks for jointed materials

- Param's choice: flat belly, flat top, stepped courses. Each jointed
  piece becomes a true prismatic block: the seat plane is the
  least-squares plane through the piece's lifted outline points
  (oriented with the outward normal); the belly is the outline
  projected onto that plane; the top is the same plane offset by the
  full thickness along its normal; side faces are ruled straight
  between belly and top (straight-tool cuts). Global curvature lives in
  the stepping between blocks, the honest cut-voussoir reading.
- Seating honesty: the gap between each seat plane and the true surface
  (the packing/mortar bed the flat cut implies) is measured per piece
  and disclosed: per-piece max gap in the tessellation report, worst
  and median in the Data panel beside the existing corner-residual
  stats. Nothing hides that a flat belly on a curved form leaves a
  wedge.
- Placement: each block's resting pose sits its seat plane on the
  form (the drop animation lands it there); neighbouring blocks may
  step above or below each other exactly as real voussoirs do.
- The joint gap and taper controls keep their meaning (inset within the
  seat plane; taper thins toward the crown by scaling thickness).

### K3. The rim, by geometry not density

- The outline-clamp mechanism is replaced for rim-adjacent points:
  instead of radius_at's outermost-crossing clamp (which yanks points
  up to 52 mm), outline points that fall outside the surface's support
  project to the NEAREST point of the analysis-mesh boundary polyline
  in plan, so the cut outline follows the real silhouette without
  crescent bites. Course 0's outline simplifies against the boundary
  with a chord tolerance equal to the cut's existing edge tolerance,
  ending the one-piece-per-boundary-vertex fragmentation.
- Measured before/after on the real export at 0.9 m: clamped-point
  count and max displacement must drop to zero or near it, and the
  probe captures the rim close-up for the eye check. The 2x-time /
  3x-payload budget gate applies: this fix must not blow it.

## Out of scope

- Cut cancellation (next, per the priority call), 6b patterns, Wave B
  visuals, ROS.
- Any change to the analysis itself: the thrust surface, forces and FEA
  read exactly as before; only the SOLID built around the surface
  changes.

## Testing

- Server geometry tests: belly and top planarity within 1e-9 per
  jointed piece; constant thickness between the planes; seat-gap stats
  present in the report and monotone with piece size on a doubly-curved
  fixture; sprayed pieces remain curved (regression pin); rim
  clamped-point count zero-or-near on the fixture and the real-export
  measurement recorded in the wave workspace.
- Studio pins: the K1 offset sweep (formwork ghost, net clearance,
  arrow lift) each updated with the convention named; Data panel shows
  the seat-gap stats; purity and offline rules unchanged.
- Probe captures: the placement screenshot's viewpoint re-shot (blocks
  above the net), a stepped-course close-up, the rim before/after.
- No em dashes, no attribution, commit per task, nothing pushed
  (pushing is Param's).

## Retrospective corrections

Added by the wave's final fix review, 2026-08-17, after the plan above
had already shipped and been measured against the real export.

(a) K3's "so the cut outline follows the real silhouette without
crescent bites" clause (above) reads as if the outline POINT itself
moves onto the rim. What shipped is narrower: `cutting.Surface.lift`
returns no x or y at all, only z, normal and field weights, so what it
projects onto the boundary polyline is the SAMPLE location those values
are read from, not the cap point's own plan position. A point placed
outside the true rim by `domain.radius_at`'s outermost-crossing rule
still sits exactly there in plan after this fix, up to 52.3 mm outside
the true rim, the same worst case the old clamp reached. What changed is
that its height, normal and weights are now honestly sampled from the
nearest point of the real boundary instead of blended in from whichever
render face's centroid happened to be nearest, up to 52 mm away. See
`docs/BENCH.md`'s K3 section for the corrected wording and the measured
figures.

(b) "ending the one-piece-per-boundary-vertex fragmentation" (K3, above)
names the wrong quantity. Course 0's piece COUNT is circumference-driven
(the same target-size division every course uses) and was 62 both before
and after this fix; it never tracked the boundary vertex count (240) at
any point. What the fix actually reduced is OUTLINE POINTS per piece:
course 0's 62 pieces carried 538 outline points between them before this
fix and 358 after, on the real Trial 2 export at 0.9 m. "Fragmentation"
was real, but it was the outline, not the piece count.

(c) Added 2026-08-19, by the rim-remainder wave. Correction (a) above,
and the "Out of scope" list further up ("Any change to the analysis
itself: the thrust surface, forces and FEA read exactly as before; only
the SOLID built around the surface changes"), both stand on
`domain.radius_at`'s outermost-crossing rule staying fixed: (a) names
"the same worst case the old clamp reached... up to 52.3 mm outside the
true rim" as still true after K3, precisely because the crossing choice
itself was left untouched. That premise is superseded: the 2026-08-19
rim-remainder wave replaces the outermost-crossing rule with a FIRST
EXIT rule (`domain.radius_at`, `bench/studio/domain.py`) -- a deliberate
change to which crossing the rim itself resolves to, not merely to what
happens to a point once it is placed. The case (a) describes is resolved
at its source by that change. See
`docs/superpowers/specs/2026-08-19-rim-remainder-design.md` for the
binding rule and measured numbers, and `docs/BENCH.md`'s rim section for
the corrected figures.
