# Studio tweaks wave

Date: 2026-08-17, agreed with Param from his session with the merged
cutting truth wave (four screenshots: the ghost shell showing through a
timber vault mid-build with a zigzag ribbon of blocks climbing off the
crown; the render-skin dropdown; the 16K HDRI allocation failure; the
near-black single-light look he wants on purpose). Six decisions, then
the queue resumes: cut cancellation, 6b patterns, Wave B, ROS.

## The asks, as received

1. "That ghost shell is back again." Plus, visible in the same
   screenshot and added by us: a diagonal ribbon of blocks flying off
   the crown mid-animation.
2. The render skin is wrong: the material should keep its own texture
   and base colour; tint recolours it; the finish slider is gloss to
   matt and should say so.
3. Some HDRIs will not import: "Array buffer allocation failed" on a
   16K file; one failed load left a black dome he liked.
4. In Studio mode, low brightness should reach that darkness: near
   black with one projecting light source.
5. The run animation is jarring: make it a flat turntable, no vertical
   movement, always centred on the pavilion.
6. Ground presets want Tint and Scale controls.

## Decisions

### W1. Ghost and staircase: diagnose first, fix by cause

- The probe reproduces the screenshot's state (Trial 2 or the Algebraic
  export, timber, mid-timeline) and identifies BOTH artefacts with
  captures: which surface the dark ghost is (falsework in animation
  mode, the formwork always-plane, or something else), and what places
  the zigzag block ribbon above the crown (suspects: the drop
  animation's stagger or DROP_HEIGHT interaction with prism placement,
  a course ordering fault, or the K2 rest pose of late courses).
- Fixes land only with the capture naming the cause, before/after
  shots, and a pin where the fix is pinnable. If the ghost turns out to
  be correct-but-unwanted behaviour (animation-mode formwork), the fix
  is the default or the visual weight, decided against Param's "rather
  not see it" standing preference.

### W2. Appearance simplified

- The render-skin select is REMOVED (UI, state, SKINS table, persisted
  keys migrate: stored appearance entries with a skin fall back to
  tint/finish only). The material always keeps its own texture and
  base colour.
- Tint recolours the material (as today, colour only, maps stay).
- The finish slider is renamed "Gloss to matt" (label text; the id may
  stay material-finish so pins update minimally). Same range and
  behaviour.
- Reset clears tint and finish. The render-only honesty note stays.

### W3. Big HDRIs load

- Radiance decode switches to half-float above a pixel-count threshold
  (a 16K equirect at Float32 RGBA is 2 GB, past the browser's
  allocation limit; half-float quarters it): try FloatType below the
  threshold as today, HalfFloatType above it, and on an allocation
  failure at half-float, banner a clear message naming the image size
  and the practical ceiling.
- The sun estimator gains half-float support: the sampled pixels
  decode half to float in the estimator's own loop (fields.js stays
  pure array maths; a small halfToFloat helper is node-tested).
- PMREM and backdrop paths accept either texture type (three handles
  both; verify).

### W4. Studio darkness

- In Studio mode only, the Brightness slider's lower half also scales
  the ambient sources: environmentIntensity and the hemisphere light
  fade quadratically to zero as brightness approaches its minimum,
  while the sun fades linearly. At the bottom of the slider the scene
  is near black with the sun as the single projecting source, the look
  from Param's screenshots. Above the midpoint, today's behaviour
  exactly.
- Sky and HDRI modes are untouched by the ambient fade (their light IS
  the environment).
- Purity unchanged: applyGrade/applyEnvironment stay clock-free.

### W5. Turntable orbit

- The run/orbit animation becomes a flat turntable: the camera orbits
  at constant height and constant distance about the study centroid,
  pure azimuthal rotation. No vertical bobbing.
- The centroid is recomputed on every study load (and after a cut
  swap) from the built shell's bounding box centre, so the pavilion is
  always centred regardless of export origin offsets.
- Orbit speed and distance sliders keep their meaning (distance sets
  the radius; height derives from the current camera elevation at
  orbit start so the user frames the shot, the turntable holds it).

### W6. Ground tint and scale

- Each ground preset gains Tint (colour input) and Scale (texture
  repeat multiplier, 0.25x to 4x) controls in Scene, applying to the
  active preset's material in place and persisted per preset in
  localStorage ("bench-studio-ground:" + preset).
- Reset ground appearance button restores the preset's defaults.
- Dark studio (no texture) accepts tint only; scale hides for it.

## Out of scope

- Cut cancellation, 6b, Wave B (sky renderer, clouds, props, grass),
  ROS: next, in that order.
- Any cutting-engine or analysis change.

## Testing

- Static pins: skin select absent and SKINS gone; the Gloss to matt
  label; tint/finish pins updated; the half-float threshold and
  fallback in loadHdri; halfToFloat node-tested in fields.js; the
  studio ambient fade expressions in applyGrade or applyEnvironment
  (wherever landed) with purity pins; the turntable's flat-path maths
  (no z modulation) and centroid recompute site; ground control ids,
  persistence keys, and the dark-studio scale-hides rule.
- Probe: the W1 captures before/after; a darkness triplet (brightness
  max, mid, min in studio mode); a turntable frame pair proving
  constant height; ground tint/scale applied.
- Suites from the repo root; no em dashes; no attribution; nothing
  pushed (pushing is Param's).

## Retrospective corrections

Added by the wave's final fix review, 2026-08-17, after the plan above
had already shipped and been reviewed against what actually landed.

(a) W3 (above) reads as "switches to half-float above a pixel-count
threshold": a pre-choice to decide the data type from the image's own
pixel count before attempting a decode. What shipped, by controller
ruling, is a different shape: `loadHdri` always attempts FloatType
first and falls back to HalfFloatType only when that attempt throws a
RangeError, the browser's own ArrayBuffer allocation ceiling, then
falls through to the failure banner if the half-float retry also
throws a RangeError. No pixel count is ever consulted to choose which
type to try first; `HDRI_HALF_FLOAT_PIXEL_CEILING` is read only inside
that final banner, to name the practical ceiling in the message, not to
gate an upfront choice.

(b) W4's "the Brightness slider's lower half" and "above the midpoint"
wording (above) describes the fade threshold as the arithmetic midpoint
of the slider's own range. The slider spans 0.3 to 2.0, whose
arithmetic midpoint is 1.15. The threshold the plan actually pinned,
and the code follows, is brightness 1.0: the slider's neutral default
value, not the midpoint of its span.
