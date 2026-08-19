"""Assemble the one JSON the page loads: mesh, fields, sequence, provenance.

A bundle is keyed by (export, material, pattern, size, thickness) and cached
on disk; an existing file is served without recomputation. It is buildable
with no staging run and no verification file: those embed when they exist
and are null when they do not, so the studio has something to show on day
one.
"""

from __future__ import annotations

import collections
import datetime
import json
import math
import os
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cutting
import domain
import generators
import geometry
import openings
import pieces
import subdivision
import tessellation

REPO = Path(__file__).resolve().parents[2]
UPLOAD_DIR = REPO / "bench" / "demo" / "upload from grasshopper"
STUDIES_DIR = REPO / "bench" / "studies"

# Recording frames and stitched videos are big transient binaries (a 1080p
# take runs to gigabytes of PNG). Under the repo they land inside OneDrive's
# sync scope, whose per-file hashing and upload churn throttled a live
# recording to a crawl (2026-08-18, 935 frames / 1.5 GB before the user gave
# up). They live under the machine-local state dir instead: %LOCALAPPDATA%
# on Windows (never synced), the temp dir elsewhere.
RECORDINGS_DIR = Path(
    os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
) / "BenchStudio" / "recordings"

# The bundle document shape: if a cached document lacks any of these keys,
# it is stale and must be rebuilt. This is how the cache invalidates itself
# as new document fields are added, without requiring manual version numbers.
#
# Dotted paths, because a field added inside the tessellation summary makes
# a cached bundle exactly as stale as a missing top level key does, and the
# top level pair alone could not see it. Every entry below the first two
# landed during the 2026-08-12 cutting wave and is read by the viewer's
# Data panel, so any machine that ran this branch mid-wave holds a cache
# the panel cannot render. The panel degrades honestly on a missing
# sub-field now as well; this is the half that stops the stale document
# being served in the first place.
REQUIRED_BUNDLE_KEYS = (
    "pieces",
    "tessellation",
    "tessellation.corner_residual_stats",
    "tessellation.facets_per_piece",
    "tessellation.boundary_points_per_piece",
    "tessellation.clamped_max_m",
    "tessellation.clamped_median_m",
    "tessellation.report.folded",
    # K2 (cutting truth, 2026-08-17): landed after every entry above and
    # read by the Data panel's own seat-gap disclosure (studio.js), so a
    # bundle cut before this task is exactly as stale as one missing any
    # other field this list already guards.
    "tessellation.seat_gap_stats",
    # K3 (cutting truth, 2026-08-17): landed after seat_gap_stats. A bundle
    # cached before this task clamped rim points instead of projecting
    # them, so its clamped_* figures mean something different from what
    # this field's presence implies about the rest of the report; treating
    # it as stale forces a re-cut rather than a mismatched read.
    "tessellation.projected_points",
    # Rim-rectangular fix (2026-08-18): landed after projected_points. A
    # bundle cut before this task shipped every off-mesh cap point at its
    # own unprojected plan position (only the sample moved, see
    # cutting.Surface.lift and pieces._lift); its piece outlines are
    # exactly the shape this fix corrects, so a bundle missing this field
    # is stale in the same way one missing clamped_max_m or seat_gap_stats
    # already is.
    "tessellation.degenerate_dropped",
    # Final fix wave (2026-08-19): landed after degenerate_dropped. The
    # multi-loop task rerouted build_tessellation_for's boundary attachment
    # to walk every closed loop of the mesh boundary (the outer rim AND
    # every opening's own rim) instead of just the outer one, but shipped
    # with no staleness entry for it, so a bundle cut before this task kept
    # its outer-only attachment (or none at all, on a multi-loop mesh the
    # old domain.boundary_ring simply refused) and was served forever: its
    # off-mesh cap points near an opening are clamped into the nearest
    # face where a fresh cut now projects them onto that opening's true
    # rim. boundary_loops is the honest, always-present count of how many
    # loops the attachment found (openings or not), so a bundle missing it
    # is stale in the same way one missing any field above already is.
    "tessellation.boundary_loops",
    # Cut cancellation rider (2026-08-19): domain.CROSSING_RULE names the
    # geometric rule radius_at currently implements (see the comment on
    # that constant for when to bump it). Every entry above this line is
    # presence-only: it can tell a cached bundle apart from one missing a
    # field, but not a bundle built under a DIFFERENT geometry rule that
    # already has every field a newer rule also produces -- a bundle cut
    # under the outermost crossing rule the rim-remainder wave replaced
    # passed every gate above unchanged while still carrying that rule's
    # geometry. tessellation.crossing_rule makes the rule itself part of
    # the freshness check for the ONE transition this entry was written
    # for (missing entirely, on anything cut before this task); its VALUE
    # is checked against domain.CROSSING_RULE separately, by
    # REQUIRED_BUNDLE_VALUES below, so a FUTURE bump of the constant also
    # invalidates a cache carrying an earlier value (review finding I4,
    # fix round 1, 2026-08-19: presence alone cannot tell an earlier value
    # apart from the current one).
    "tessellation.crossing_rule",
)

# A field can be present and still say the wrong thing: REQUIRED_BUNDLE_
# KEYS above only proves a key EXISTS, so a bundle cut under an EARLIER
# value of a field that value-carrying entries above claim to guard would
# still pass every one of those entries once that value first ships. Fix
# round 1 (review finding I4, 2026-08-19): domain.CROSSING_RULE's own
# comment instructs a future maintainer to bump the constant whenever
# radius_at's answer changes, and the presence-only gate alone cannot
# make good on that a second time, since a bundle cut under ANY earlier
# rule already has the crossing_rule field, just carrying an earlier
# value. REQUIRED_BUNDLE_VALUES closes the gap: each dotted path here
# (read with the same dotted-path convention REQUIRED_BUNDLE_KEYS uses)
# must EQUAL the paired expected value -- read fresh from the same module
# attribute the field's own comment already names -- not merely exist,
# for a cached bundle to be considered fresh (see load_or_build_bundle's
# own gate below, which checks this only for paths REQUIRED_BUNDLE_KEYS
# has already confirmed present, so _key_path_value below never has to
# handle a missing path).
REQUIRED_BUNDLE_VALUES = {
    "tessellation.crossing_rule": domain.CROSSING_RULE,
}


def _has_key_path(document: Dict, path: str) -> bool:
    node = document
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _key_path_value(document: Dict, path: str):
    """The value at a dotted path REQUIRED_BUNDLE_KEYS has already
    confirmed present (see REQUIRED_BUNDLE_VALUES' own comment); used
    only by load_or_build_bundle's freshness gate, after that check has
    already run, so this never has to handle a missing path itself.
    """

    node = document
    for part in path.split("."):
        node = node[part]
    return node


def bundle_path(slug: str, material: str, pattern: str, size: float, thickness: float) -> Path:
    return STUDIES_DIR / slug / "studio" / "bundle-{}-{}-s{}-t{}.json".format(
        material, pattern, round(size * 1000), round(thickness * 1000))


def staging_path(slug: str, material: str, pattern: str, size: float, thickness: float) -> Path:
    return STUDIES_DIR / slug / "studio" / "staging-{}-{}-s{}-t{}.json".format(
        material, pattern, round(size * 1000), round(thickness * 1000))


def tessellation_sidecar(export_name: str) -> Path:
    return UPLOAD_DIR / "{}-tessellation.json".format(export_name)


def _read_optional(path: Path) -> Optional[dict]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _staging_matches(
    staged: Optional[dict], made: List[dict], degenerate_dropped: Sequence[str] = ()
) -> bool:
    """Does this stage plan name the cells these pieces actually carry?

    The bundle guards its own pieces twice, with REQUIRED_BUNDLE_KEYS and
    _pieces_are_uniquely_keyed, and both force a re-cut. The embedded
    staging document had no gate at all: build_bundle read whatever
    staging_path found and shipped it verbatim. app.py writes the two
    together once, and that was the whole guarantee, so anything that
    rebuilds the bundle without rebuilding staging breaks it. An authored
    tessellation sidecar appearing, changing or disappearing does it,
    since the sidecar is in neither the cache key nor
    app._invalidate_studio_cache; so does the natural workaround for that,
    which is to delete bundle-*.json to force a re-cut and leave
    staging-*.json behind. Deleting the file alone is not enough while the
    process is alive, since build_bundle goes through the in-process cut
    memo (see _cut_for): that memo also has to be cleared, which in
    practice means a re-upload (clear_cut_memo runs as part of
    app._invalidate_studio_cache) or a restart.

    Nothing crashes when the two disagree, which is what makes it worth a
    gate. The viewer derives the stage from the pieces' own courses and
    clamps, so a mismatched plan reads as a working animation: a formwork
    curve summed over a different cut's faces, and a struck-now verdict
    solved for a different placed-faces list. Wrong numbers, wrong
    verdict, no warning. Dropping the plan is preferred over attaching it
    with a marker, because a marker is only as good as the reader that
    honours it and this document is read by code in another tree.

    A stage segment is a cell key: staging.stage_plan labels segments from
    binding["keys"], and pieces.segment_pieces emits one piece per cell
    under that same key, so a matching pair has equal sets. Subset, not
    equality, is the test, because a plan naming fewer cells than are
    drawn is still a plan about this cut.

    Review fix (2026-08-18): a stage plan is solved against binding["keys"],
    every cell the CUT itself names, before pieces.segment_pieces's own
    guard-degeneracy pass (see pieces.py) can drop a handful of them as
    untriangulatable or collapsed below 3 corners. Those keys are real cells
    of this cut, correctly named by the plan, that simply never became a
    drawn piece -- not a mismatch with a DIFFERENT cut's plan, which is the
    only thing this gate exists to catch (see the docstring above). Treating
    them as a fatal mismatch silently dropped the whole staging plan (and
    with it the formwork animation and the CRA verdict) on any export/size
    combination that drops even one cell, with no message anywhere: at
    0.30 m on the real Trial 2 export, exactly this happened. named is
    therefore compared against made's own keys UNION the cells this cut's
    own report already discloses as dropped, not against made alone.
    """

    if staged is None:
        return False
    stages = staged.get("stages")
    if not isinstance(stages, list):
        return False
    named = set()
    for stage in stages:
        if not isinstance(stage, dict):
            return False
        segments = stage.get("segments") or []
        if not isinstance(segments, list):
            return False
        named.update(segments)
    named -= set(degenerate_dropped)
    return named <= {piece["key"] for piece in made}


# The cut is the expensive step of a bundle build, and its inputs are the
# export geometry, the pattern and the size: material and thickness never
# reach it, so switching material at an already-cut size reuses the cut
# instead of re-running it. In-process only and LRU-capped, because a
# single small-size cut runs to tens of megabytes. Cleared by
# clear_cut_memo() wherever the studio JSON cache is invalidated (an
# export re-upload), so a stale cut cannot outlive its export -- and that
# claim now holds under concurrency, not just in sequence: a generation
# counter, bumped under the same lock the dict is guarded by, is what a
# clear actually advances, so a cut that was already being built when the
# clear landed is still handed back to its own caller but is never written
# into the memo afterwards. The authored-tessellation sidecar shares the
# staleness gap the JSON cache already documents above: it is in neither
# key.
#
# get_bundle's threadpool (FastAPI runs a sync route on a worker thread),
# the run worker thread (start_run's work(), which cuts through
# staging.run_staging and build_bundle alike) and the async upload handler
# (_invalidate_studio_cache, on every re-upload) are the concurrent readers
# and writers _cut_memo_lock protects.
#
# The memoised tuple is shared by reference with every caller that reads
# the same key, sometimes across different documents' requests at once:
# nothing may mutate a returned cut in place.
CUT_MEMO_LIMIT = 4
_cut_memo_lock = threading.Lock()
_cut_memo_generation = 0
_cut_memo: "collections.OrderedDict" = collections.OrderedDict()


def clear_cut_memo() -> None:
    global _cut_memo_generation
    with _cut_memo_lock:
        _cut_memo_generation += 1
        _cut_memo.clear()


class _CutHolder:
    """One in-flight cut build for a single key (cut cancellation,
    2026-08-19): a threading.Event plus a result slot, an error slot, and
    (fix round 1, review finding C2) the memo generation this build
    started under. The builder thread -- the first caller to find its key
    absent from both _cut_memo and _cut_inflight -- fills exactly one of
    the two slots and then sets event; every other caller for the SAME
    key in the meantime (a joiner) waits on event and reads whichever
    slot the builder filled, instead of each running its own, fully
    redundant compute of the same expensive cut (see _cut_for). The slots
    are written exactly once, strictly before event is set, so a joiner
    reading them after event.wait() returns needs no lock of its own:
    Event's own internal lock is the happens-before edge.

    generation (fix round 1, review finding C2): the SAME value _cut_for
    already reads into its own local "generation" variable, captured in
    the identical critical section that creates this holder. A joiner
    reads it back once its own wait ends and compares it against the
    CURRENT _cut_memo_generation at that moment: if a clear_cut_memo ran
    at any point during the wait, the joiner's own caller loaded its
    contract/arrays/render AFTER that clear (see _cut_for's own join
    branch), so a result computed before it is a cut for geometry that no
    longer matches what this caller is about to assemble into a document.
    This mirrors the memo's own generation rule (bundle.py's module
    comment on _cut_memo, "a stale cut cannot outlive its export") for
    joiners too, not just for the memo write.
    """

    __slots__ = ("event", "result", "error", "generation")

    def __init__(self, generation: int) -> None:
        self.event = threading.Event()
        self.result = None
        self.error: Optional[BaseException] = None
        self.generation = generation


# Builds currently under way, one holder per cut key, so a second request
# for a key already building JOINS the first instead of paying for its
# own, fully redundant compute (single-flight; the /api/runs 409/attach-
# to-existing pattern, applied here at the layer where the cut memo above
# already lives). Guarded by the SAME _cut_memo_lock the memo itself uses:
# a holder is created and installed, and later removed and (on success)
# promoted into _cut_memo, in the same critical sections that already
# read and write the memo, so a caller taking the lock always sees one
# consistent picture -- a key is either memoised, in flight, or neither,
# never something in between.
_cut_inflight: "Dict[tuple, _CutHolder]" = {}


class CutSuperseded(Exception):
    """Raised out of an in-flight interactive cut when a strictly newer,
    different-key interactive request has arrived for the same export
    (cut cancellation, 2026-08-19; see superseded() below).

    Cooperative, not preemptive -- nothing interrupts the building thread.
    _cut_for builds a zero-argument checkpoint closure only when it is
    given an interactive_token, and threads it through build_tessellation_
    for (which threads it on into generators.generate, called once per
    course) and pieces.segment_pieces (called once per cell), exactly
    like Task 1's own checkpoint hooks. The closure raises this the next
    time either loop reaches its own checkpoint call after a newer,
    different-key request has registered.

    build_bundle does not catch it: only CutRefused, its own expected,
    valid-geometry refusal, is caught there. This propagates unmodified
    through load_or_build_bundle to app.get_bundle, the only place that
    knows what to do with it -- answer 409 {"superseded": true} rather
    than 500, since the client's own sequence guard (or its
    AbortController) means nobody was left waiting to render this build
    anyway.

    Always raised before build_bundle's single write-at-the-end can run
    (the generation-guarded _cut_memo write inside _cut_for, and the
    bundle JSON write at the tail of build_bundle, both sit strictly after
    every checkpoint call in the cut they depend on), so a superseded
    build writes NOTHING: no memo entry, no file on disk.

    Fix round 1 (review finding C1, 2026-08-19): a caller that JOINS a
    build which ends this way does not necessarily inherit it. An
    interactive joiner (its own interactive_token) genuinely is
    superseded too whenever the build it joined is (see superseded's own
    docstring: the joiner shares the builder's key, and the same newer,
    different-key registration that supersedes the builder also
    supersedes any live registration sharing its key), so it re-raises
    this exception, unchanged from before this fix. A token-less joiner
    (staging, or any other caller with no interactive_token at all)
    cannot be legitimately cancelled by interactive supersession at
    all -- that is the whole isolation promise this module makes -- so
    _cut_for catches this specific case on the join path and retries
    instead of raising: the token-less caller becomes the new builder (or
    joins a fresh one, if another retrying caller got there first) and
    completes with a real result.
    """


# Cooperative supersession's own bookkeeping (cut cancellation,
# 2026-08-19): a per-export record of the freshest interactive bundle GET,
# so an in-flight cut for a key nobody wants any more can be told to stop
# instead of running to completion for an answer the client has already
# abandoned (the design doc's measured problem: two full 13.7 s cuts run
# to completion under GIL contention for an answer only the second
# caller's request was still waiting on).
#
# register_interactive is called once per interactive GET, in app.py's
# get_bundle, before load_or_build_bundle -- even on a request that ends
# up served straight from the on-disk cache and never reaches _cut_for at
# all, because that cache hit is itself evidence the caller has moved on
# to a DIFFERENT key, and an older, still-running build for the OLD key
# must still be told so. That is why the key is recorded here, at
# registration, rather than resolved later inside _cut_for: a cache-hit
# request never reaches _cut_for, so by then it would be too late to have
# said anything at all.
#
# Guarded by the existing _cut_memo_lock rather than a lock of its own:
# both pieces of state are small, cheap to touch, and already read
# together on the same request path, so a second lock would only add
# ordering risk for no real concurrency gain.
#
# Level-triggered, not latched (review finding M6, fix round 2,
# 2026-08-19): _interactive_live holds exactly ONE entry per export, the
# newest registration only, so superseded() always answers against
# whatever is live RIGHT NOW, not against a permanent verdict recorded
# the first time a build happened to be superseded. A build's checkpoint
# can therefore see True on one call and False on a LATER one: a
# different-key registration supersedes it, and if a still later
# registration for the build's own original key arrives afterward
# (re-becoming the export's newest), that later registration overwrites
# the entry above, and the build is no longer superseded, because the
# live entry once again shares its key. Deliberate, not an oversight: a
# latch that remembered "superseded, once, forever" would hand
# CutSuperseded to a joiner whose own key has since become the live one
# again, the wrong answer (see _cut_for's own join-branch comments: an
# interactive joiner's cancellation is re-raised only because it is
# genuinely current at the moment it is read, not merely historical).
_interactive_token_counter = 0
_interactive_live: "Dict[str, Tuple[int, tuple]]" = {}


def register_interactive(export: str, key: tuple) -> int:
    """A new, strictly increasing token for export's next interactive
    build, recorded immediately as export's freshest live request, wanting
    key. See the module comment above for why key is threaded in here
    rather than resolved later, inside _cut_for.
    """

    global _interactive_token_counter
    with _cut_memo_lock:
        _interactive_token_counter += 1
        token = _interactive_token_counter
        _interactive_live[export] = (token, key)
    return token


def superseded(export: str, token: int, key: tuple) -> bool:
    """True iff a strictly newer interactive token has registered for
    export wanting a DIFFERENT key than key.

    An identical key never supersedes: the newer request finds the same
    key already building in _cut_inflight and joins it instead of
    starting a build of its own (see _cut_for), so the two are never in
    conflict over what the answer should be, only over who computes it
    once.

    Level-triggered against the CURRENT live entry, not latched against
    whatever it was on some earlier call: see the module comment above
    _interactive_live for what that means for a build checked more than
    once.
    """

    with _cut_memo_lock:
        current = _interactive_live.get(export)
    if current is None:
        return False
    latest_token, latest_key = current
    return latest_token > token and latest_key != key


class CutRefused(ValueError):
    """The cutting engine's own refusal on otherwise valid geometry.

    P5 (presentation batch, 2026-08-18): domain.plan_domain (the rim is not
    a single loop -- boundary_ring's own "more than one loop" message, an
    oculus or a hole) and generators.generate (the plan is not star shaped
    about its axis) both raise a plain ValueError, and build_tessellation_
    for re-raises it as this subclass instead, ONLY on the branch with no
    authored tessellation to fall back on. build_bundle catches CutRefused
    and ships the bundle anyway (pieces empty, uncut_reason carrying this
    message verbatim): the plan is real, valid geometry, and the engine's
    documented single-star-shaped-loop constraint (see domain.py's own
    module docstring) is not being relaxed, only reported honestly instead
    of surfacing as a 400 for an upload that parsed and validated fine.
    A plain ValueError -- a malformed AUTHORED tessellation, from
    tessellation.from_document -- is deliberately left alone: that is bad
    input, not a valid plan the engine declines to cover, and stays a 400
    (see get_bundle in app.py and test_a_malformed_authored_tessellation_
    is_a_400_naming_the_cell in test_app.py).

    Multi-loop (2026-08-19): an oculus or a hole is no longer, on its own,
    a CutRefused case. openings.py classifies it apart from the outer rim
    and generate's clip pass trims cells around its true boundary, so a
    plan with one or more interior openings cuts natively as long as its
    OUTER rim is still star shaped (see domain.py's own module docstring,
    updated the same task). What still lands here: the outer rim itself
    not star shaped, or a re-entrant/branching rim (generators.generate,
    domain.boundary_ring); no loop containing the others, loops
    overlapping in plan, or an opening self-crossing in plan
    (domain.plan_domain, via openings.classify); the axis falling inside
    an opening, so the polar pattern has no crown to close on
    (domain.plan_domain); and monolithic-bands asked to cross an opening
    its ring cells cannot yet clip (generators.generate). Each is a named,
    tested refusal (see docs/superpowers/specs/2026-08-19-multiloop-
    cutting-design.md, "What still refuses, verbatim").
    """


def build_tessellation_for(
    export_name, contract, arrays, render, pattern, size, checkpoint=None
):
    """The one cut, built once, for the drawing and for the analysis alike.

    staging.py calls this too. Two builders would be two cuts, and a
    stage plan that names cells the pieces do not have is the kind of
    mismatch that only shows up as a crash mid animation.

    checkpoint (cut cancellation, 2026-08-19): threaded straight through
    to generators.generate on the generated-cut branch below, unused on
    the authored-tessellation branch (tessellation.from_document has no
    per-course or per-cell loop of its own to check from). None (the
    default, and the only value staging.py's own direct call ever passes)
    means this behaves exactly as before this parameter existed.
    """

    surface = cutting.Surface(render["vertices"], render["faces"])
    # K3 (cutting truth, 2026-08-17): the analysis mesh's own boundary
    # ring, in plan, cached on the surface so cutting.Surface.lift can
    # project a cap point that lands off the render mesh onto the real
    # rim instead of clamping it into the nearest face. Built here,
    # unconditionally, ahead of the authored/generated branch below: an
    # authored tessellation never calls domain.plan_domain at all (it has
    # no domain of its own), so this is the only place the boundary is
    # available to it too. Guarded rather than left to raise: a handful of
    # exports carry an authored tessellation over an analysis mesh whose
    # boundary was never required to be a single clean loop before this
    # (domain.boundary_ring demands exactly that), and a surface with no
    # boundary attached simply keeps the old nearest-face clamp as its
    # only fallback, which is no worse than every export had before K3.
    #
    # Multi-loop (2026-08-19): every closed boundary loop is attached, not
    # just the outer rim -- openings.extract_loops walks the mesh's whole
    # boundary (every connected component), so a surface with openings
    # attaches the outer rim AND every opening's own rim. cutting.Surface's
    # multi-polyline projection then picks whichever loop is actually
    # nearest, so a drawn point pushed just off the mesh near an opening
    # projects onto THAT opening's boundary instead of the outer one. The
    # same try/except ValueError guard as before: a branch-vertex mesh
    # (openings.extract_loops' own refusal, verbatim the same message
    # domain.boundary_ring raised) still just skips attachment.
    try:
        loops = openings.extract_loops(arrays["faces"])
        surface.boundary = [
            [[arrays["vertices"][i][0], arrays["vertices"][i][1]] for i in loop]
            for loop in loops
        ]
        boundary_loop_count = len(loops)
    except ValueError:
        boundary_loop_count = 0
    authored = tessellation.read_tessellation(
        contract, tessellation_sidecar(export_name))
    if authored is not None:
        tess = tessellation.from_document(authored, surface.height)
    else:
        try:
            plan = domain.plan_domain(
                arrays["vertices"], arrays["faces"],
                geometry.face_centroids(arrays["vertices"], arrays["faces"]),
            )
            tess = generators.generate(pattern, plan, size, checkpoint=checkpoint)
        except ValueError as error:
            # See CutRefused's own docstring: this is the one place the
            # distinction between "the engine refuses valid geometry" and
            # "the input is malformed" can actually be drawn, because it is
            # the one place that knows which of the two branches raised.
            raise CutRefused(str(error)) from error
    # Final fix wave (2026-08-19): the count of loops the attachment above
    # actually found, honest and always computable regardless of which
    # branch built tess (authored or generated) or whether the mesh has
    # any openings at all -- unlike the openings block in build_bundle
    # below, this is not a fact that only exists when a clip pass ran.
    # See REQUIRED_BUNDLE_KEYS' own comment on tessellation.boundary_loops
    # for why a cached document needs this to invalidate correctly.
    tess["boundary_loops"] = boundary_loop_count
    centroids = geometry.face_centroids(arrays["vertices"], arrays["faces"])
    binding = tessellation.analysis_binding(tess, centroids)
    return tess, surface, binding


def _cut_for(export_name, contract, arrays, render, pattern, size, interactive_token=None):
    """The memoised, single-flighted, optionally cancellable cut.

    interactive_token (cut cancellation, 2026-08-19): None (the default --
    every caller except an interactive bundle GET: staging, tests, and any
    other _cut_for caller) means no checkpoint is built at all, so this
    call can never be superseded, whatever else registers for export in
    the meantime (see superseded's own docstring and CutSuperseded's). A
    real token builds a zero-argument closure that raises CutSuperseded
    the moment generators.generate or pieces.segment_pieces calls it after
    a newer, different-key request has registered -- threaded through
    build_tessellation_for and pieces.segment_pieces exactly like Task 1's
    own checkpoint parameters.

    Single-flight: a second call for a key already building here (its own
    interactive_token irrelevant to this part -- joining is keyed on the
    cut key alone) waits on the first build's own _CutHolder rather than
    running its own, fully redundant compute, and shares its result --
    subject to the two checks below, both of which retry (loop back to
    the top, exactly as if this call were arriving fresh) rather than
    trusting a joined outcome that is no longer this caller's own to
    trust. Several callers retrying at once still coalesce into one fresh
    build, the same join this function already gives any other cold key.

    Fix round 1 (review findings C1 and C2, 2026-08-19): a joiner retries
    instead of adopting the holder's own outcome in exactly two cases --
    (1) the holder's generation (the memo generation its OWN build
    started under, see _CutHolder's own docstring) no longer matches the
    CURRENT one: a clear_cut_memo ran during the wait, so the joiner's
    own caller already loaded a possibly different export than the one
    this holder was cut from, and adopting its result (success OR error
    alike) would answer for the wrong geometry; (2) the holder's error is
    CutSuperseded and THIS caller has no interactive_token of its own: a
    token-less caller cannot be legitimately cancelled by interactive
    supersession (see CutSuperseded's own docstring), so a cancellation
    that belonged to whichever interactive request was building is not
    this caller's to inherit. An interactive joiner's own CutSuperseded
    is not retried: it is, at that same moment, genuinely superseded too
    (see superseded's own docstring), so it re-raises exactly as before
    this fix.
    """

    key = (export_name, pattern, size)
    checkpoint = None
    if interactive_token is not None:
        def checkpoint():
            if superseded(export_name, interactive_token, key):
                raise CutSuperseded(
                    "the cut for {!r} was superseded by a newer request "
                    "before it finished".format(export_name)
                )

    while True:
        with _cut_memo_lock:
            generation = _cut_memo_generation
            if key in _cut_memo:
                _cut_memo.move_to_end(key)
                return _cut_memo[key]
            holder = _cut_inflight.get(key)
            if holder is not None:
                joining = True
            else:
                holder = _CutHolder(generation)
                _cut_inflight[key] = holder
                joining = False

        if joining:
            # A build for this exact key is already running, under
            # another caller's own interactive_token (or none at all --
            # the joiner's own token plays no part in whether ITS wait is
            # honoured, only in whether the BUILDER it is waiting on
            # later gets superseded). Waited on outside the lock: the
            # wait can be the whole several-second cost of a real cut,
            # and nothing else keyed on _cut_memo_lock may sit blocked
            # behind it.
            holder.event.wait()
            with _cut_memo_lock:
                stale = holder.generation != _cut_memo_generation
            if stale:
                # Fix round 1, C2: a clear_cut_memo happened somewhere
                # across this holder's own lifetime, before or during
                # this wait. Whatever it produced (success or error
                # alike) was cut under geometry this caller's own
                # contract/arrays/render may no longer match -- see
                # _CutHolder's own docstring. Retry from the top: by now
                # the holder is guaranteed removed from _cut_inflight
                # (the builder's finally block below always removes it
                # before setting the event), so this becomes a fresh
                # build, or joins one just started by another retrying
                # caller.
                continue
            if holder.error is not None:
                if interactive_token is None and isinstance(holder.error, CutSuperseded):
                    # Fix round 1, C1: this caller carries no interactive
                    # token, so it cannot be legitimately cancelled by
                    # interactive supersession at all (see CutSuperseded's
                    # own docstring). The build it joined was cancelled on
                    # behalf of whichever interactive request registered
                    # it, not on this caller's behalf. Retry: same
                    # coalescing as the generation case above.
                    continue
                raise holder.error
            return holder.result

        try:
            tess, surface, binding = build_tessellation_for(
                export_name, contract, arrays, render, pattern, size,
                checkpoint=checkpoint)
            supports = geometry.support_ids(contract)
            support_points = [
                [arrays["vertices"][i][0], arrays["vertices"][i][1]] for i in supports
            ]
            made, report = pieces.segment_pieces(
                tess, surface, support_points, checkpoint=checkpoint)
            result = (tess, binding, supports, made, report)
        except BaseException as error:
            # Fix round 1, I3: BaseException, not Exception -- the holder
            # promises its error slot is Optional[BaseException], and a
            # joiner's wait below has no timeout, so any exception this
            # catch clause missed (KeyboardInterrupt, SystemExit, any
            # other non-Exception) would leave the holder in
            # _cut_inflight forever, hanging every later caller for this
            # key. The finally block below still runs the SAME cleanup
            # (remove from _cut_inflight, set the event) regardless of
            # which branch of this try ran, so this except exists only to
            # capture the error object itself before the bare raise
            # propagates it out through the finally.
            holder.error = error
            raise
        else:
            holder.result = result
        finally:
            with _cut_memo_lock:
                del _cut_inflight[key]
                # A clear that ran while this cut was being built means
                # the export may have changed under it: the result is
                # still returned to its own caller (built from the
                # inputs that caller loaded) but never memoised, so a
                # stale cut cannot outlive its export. holder.error is
                # None on the success path only, so this never memoises
                # an error result.
                if holder.error is None and generation == _cut_memo_generation:
                    _cut_memo[key] = holder.result
                    while len(_cut_memo) > CUT_MEMO_LIMIT:
                        _cut_memo.popitem(last=False)
                holder.event.set()
        return holder.result


def _render_mesh(vertices: List[list], faces: List[list]) -> Dict[str, list]:
    """The render mesh: subdivision.subdivide_quads when the geometry is
    quads (every real GH TNA export shipped so far), otherwise the analysis
    mesh itself, unsubdivided.

    P4 (presentation batch, 2026-08-18): a compas-only import's mesh can be
    triangulated (subdivide_quads raises ValueError on anything but a
    4-vertex face -- see its own docstring: "this pass subdivides quads
    only"), and that check is deliberately not loosened here: it is shared,
    tested code a real quad export still depends on, and a Catmull-Clark
    pass has no honest triangle analogue to fall back to instead of just
    skipping it.

    Skipping it costs only render/heatmap resolution, never correctness:
    the cut itself (cutting.Surface, domain.plan_domain, pieces.segment_
    pieces) fan-triangulates internally and is already face-count agnostic
    (verified against a real 2521-vertex, 2400-quad export run through
    this exact fallback path in P4's own report), and render_mesh's other
    consumer -- studio.js's fieldPerRenderVertex, which smooths a staged
    per-node field onto render_mesh.vertex_sources -- only ever runs when
    a staged analysis exists to smooth, which a geometry-only import never
    has. The identity parent_face/vertex_sources below (each render entry
    maps onto its own analysis entry, 1:1) keep both dict shapes exactly
    what subdivide_quads' own callers already expect.
    """

    try:
        return subdivision.subdivide_quads(vertices, faces)
    except ValueError:
        return {
            "vertices": [list(v) for v in vertices],
            "faces": [list(f) for f in faces],
            "parent_face": list(range(len(faces))),
            "vertex_sources": [[i] for i in range(len(vertices))],
        }


def build_bundle(
    export_name: str, material: str, pattern: str, size: float, thickness: float = 0.2,
    interactive_token: Optional[int] = None,
) -> Dict:
    pairs = geometry.available_exports(UPLOAD_DIR)
    if export_name not in pairs:
        raise ValueError(
            "no export named {!r}. Available: {}".format(
                export_name, ", ".join(sorted(pairs))
            )
        )
    slug = geometry.slugify(export_name)
    contract = geometry.load_contract(pairs[export_name]["contract"])
    arrays = geometry.mesh_arrays(contract)
    render = _render_mesh(arrays["vertices"], arrays["faces"])

    uncut_reason = None
    try:
        # interactive_token: None on every caller except an interactive
        # bundle GET (app.get_bundle) -- staging's own start_run() work()
        # and every test in this repo call build_bundle with no token at
        # all, so their cut builds no checkpoint and can never be told to
        # stop by a later, unrelated interactive request (see _cut_for's
        # and CutSuperseded's own docstrings). CutSuperseded is
        # deliberately NOT caught here alongside CutRefused: it is not
        # this function's own, expected outcome the way a refused plan
        # is, and propagates unmodified to whichever caller knows what to
        # do with it (app.get_bundle, 409).
        tess, binding, supports, made, report = _cut_for(
            export_name, contract, arrays, render, pattern, size,
            interactive_token=interactive_token)
    except CutRefused as error:
        # P5 (presentation batch, 2026-08-18): the engine's own refusal on
        # otherwise valid geometry (see CutRefused's own docstring) used to
        # propagate all the way to get_bundle as a plain ValueError, which
        # turned an upload that parsed fine, appeared in the study list and
        # auto-selected into a 400 with nothing to look at. The bundle
        # ships anyway: the analysis mesh, the provenance, and whatever
        # fields/forces the contract carries (zero for a derived,
        # geometry-only one -- see derive_contract.py) are exactly as real
        # as they are for a cut study. Only the cut itself, and everything
        # downstream of it (pieces, staging, the tessellation summary), is
        # missing; uncut_reason carries the engine's own message verbatim
        # so the client can say why.
        uncut_reason = str(error)
        tess = binding = report = None
        made = []
        supports = geometry.support_ids(contract)

    if uncut_reason is None:
        # backward_turn/backward_steps only exist on a generated cut (the
        # domain they are measured from is never built for an imported one),
        # so None here means "not applicable", not "zero wobble".
        backward_turn = tess.get("backward_turn")
        tessellation_summary = {
            "pattern": tess["pattern"],
            "source": tess["source"],
            "target_size": tess["target_size"],
            "courses": tess["courses"],
            "cells": len(tess["cells"]),
            "boundary_loops": tess["boundary_loops"],
            # Cut cancellation rider (2026-08-19): the geometric rule
            # radius_at implements right now, stamped on every fresh cut
            # so a cache built under an earlier rule can be told apart
            # from one built under this one -- see domain.CROSSING_RULE's
            # own comment and REQUIRED_BUNDLE_KEYS' tessellation.
            # crossing_rule entry above.
            "crossing_rule": domain.CROSSING_RULE,
            "provenance": tess.get("provenance"),
            "z_offset_max": tess.get("z_offset_max"),
            "courses_inferred": tess.get("courses_inferred", False),
            "backward_turn_degrees": (
                math.degrees(backward_turn) if backward_turn is not None else None
            ),
            "backward_steps": tess.get("backward_steps"),
            "report": binding["report"],
        }
        # Multi-loop (2026-08-19): the openings block, same ride-along
        # mechanism as backward_turn/backward_steps above, but absent
        # rather than None when the cut has none -- these five only exist
        # on tess at all when generators.generate actually ran the clip
        # pass (see generate's own "only when openings were actually
        # clipped" comment), so a plan with no openings must not gain five
        # new null fields it never had before this task.
        for key in (
            "openings", "cells_in_openings", "cells_clipped",
            "opening_slivers", "opening_clip_failures",
        ):
            if key in tess:
                tessellation_summary[key] = tess[key]
        overlap = set(tessellation_summary) & set(report)
        if overlap:
            # A raise, not an assert: python -O strips an assert, and the
            # contract this guards (the two dicts spread into one below) fails
            # silently when it goes, with one dict quietly clobbering the
            # other's field. A contract worth stating is worth enforcing in
            # every interpreter mode.
            raise ValueError(
                "pieces.segment_pieces's report shares key(s) {} with the "
                "tessellation summary; spreading it in would let one silently "
                "overwrite the other".format(sorted(overlap))
            )
        tessellation_document = {**tessellation_summary, **report}
        binding_document = {
            "assignment": binding["assignment"], "order": binding["order"],
            "keys": binding["keys"],
        }
        # The stage plan is embedded only if it was solved against THIS cut.
        # A stale plan is worse than no plan: see _staging_matches.
        staged = _read_optional(
            staging_path(slug, material, pattern, size, thickness))
        if not _staging_matches(staged, made, report.get("degenerate_dropped") or ()):
            staged = None
        cut_pattern = tess["pattern"]
    else:
        # Minimal/no tessellation summary, per the P5 contract: a fabricated
        # "0 courses, 0 cells" summary would invite the Data panel's whole
        # "Cut" section (studio.js's renderDataPanel) to render as though a
        # cut ran and found nothing, rather than never having run at all.
        # None is the honest value, and it is also what studio.js's own
        # `if (tess)` guard on that section already treats as "skip it".
        tessellation_document = None
        binding_document = None
        staged = None
        # No cut means no cut pattern; the document falls back to what was
        # requested, the same value an authored cut's absence of a domain
        # would otherwise leave unstated.
        cut_pattern = pattern

    document = {
        "export": export_name,
        "slug": slug,
        "material": material,
        # tess["pattern"], not the requested pattern: an authored (imported)
        # tessellation ignores it, and the document states what the cut
        # actually is, not what was asked for. For a generated cut this is
        # identical to what was requested.
        #
        # size, the REQUESTED size, not tess["target_size"]: this field is
        # the round trip parameter (get_bundle's own query argument) and
        # part of the cache key (bundle_path/staging_path), so it has to be
        # a value the API will accept back. An authored cut's target_size is
        # None (see tessellation.build_tessellation): it ignores size
        # entirely and has no size of its own to report, and echoing that
        # None through here poisoned the client's state.size and then 400'd
        # on the very next reload. The tessellation summary below is the
        # honest record of what the cut actually used.
        "pattern": cut_pattern,
        "size": size,
        "generated": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds"),
        "analysis_mesh": arrays,
        "render_mesh": render,
        "supports": supports,
        "loads": {
            str(k): v for k, v in geometry.node_loads_newtons(contract).items()
        },
        "reactions": {
            str(k): v
            for k, v in geometry.support_reactions_newtons(contract).items()
        },
        "member_forces": geometry.member_forces_newtons(contract),
        "binding": binding_document,
        "tessellation": tessellation_document,
        "pieces": made,
        "staging": staged,
        "verification": _read_optional(
            STUDIES_DIR / slug / "fea-verification.json"
        ),
        # None on a normal, cut bundle. On an engine refusal, the engine's
        # own message verbatim (see CutRefused's docstring) -- the one
        # field the client checks to tell an uncut bundle from a cut one at
        # all (studio.js's own `if (tess)` guard on the tessellation summary
        # cannot, since a bundle cached before this task also had a null-ish
        # absence there for other reasons).
        "uncut_reason": uncut_reason,
        "provenance": {
            "contract_file": pairs[export_name]["contract"].name,
            "thickness": thickness,
            # K1 (cutting truth, 2026-08-17): the piece "mid" points this
            # bundle ships are the surface the formwork touches, and the
            # viewer (buildPieceMeshes, studio.js) builds the drawn solid
            # upward from there by the full thickness. Named explicitly so
            # a viewer can tell which convention a bundle was built under.
            "surface": "intrados",
            "combination": "ULS",
            "combination_factor": 1.35,
            # P4: derive_contract.derive_contract stamps its own output
            # with a top level provenance.derived marker (never inside
            # equilibrium/formGraph, which geometry.py's parsers own); a
            # real, human- or GH-authored contract has no such key, so
            # this is None for every export except a geometry-only one.
            # Threaded through here, not read fresh by the client, so the
            # Data panel's "no analysis in this export" note (studio.js)
            # has one source of truth: this bundle document.
            "derived_geometry_only": (
                contract.get("provenance", {}).get("derived")
                if isinstance(contract.get("provenance"), dict) else None
            ),
            "note": "staging and verification are null until their runs "
                    "exist; staging is also dropped, not embedded, when its "
                    "stage plan names cells this cut does not draw",
        },
    }
    # Cache decision (P5): an uncut bundle is NOT written to disk. Every
    # REQUIRED_BUNDLE_KEYS entry lives under "tessellation", which is None
    # here, so a cached copy would need its own staleness carve-out to
    # avoid load_or_build_bundle treating it as stale forever and rebuilding
    # it on every read anyway -- at which point the cache buys nothing. An
    # uncut build is also cheap: no cut ran, only the plan/domain check that
    # refused it, far below a real cut's own cost. Simplest honest choice:
    # never cache it, always recompute it fresh.
    if uncut_reason is None:
        target = bundle_path(slug, material, pattern, size, thickness)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(document), encoding="utf-8")
    return document


def _pieces_are_uniquely_keyed(document: Dict) -> bool:
    """One key per drawn casting, which an older cache cannot promise.

    A piece key is the casting's identity in the viewer: its tint, its
    texture offset and its entry in the placement index all hang off it.
    Bundles written before pieces.py distinguished the separate patches of
    a split cell carry two castings under one key, which makes them stale
    in the same way a bundle missing a field is stale.
    """

    keys = [piece.get("key") for piece in document.get("pieces") or []]
    return len(set(keys)) == len(keys)


def load_or_build_bundle(
    export_name: str, material: str, pattern: str, size: float, thickness: float = 0.2,
    interactive_token: Optional[int] = None,
) -> Dict:
    """interactive_token: threaded through to build_bundle on a cache miss.

    A cache HIT never reaches build_bundle (and so never reaches _cut_for
    or a checkpoint at all), but the token still has to be passed IN here
    -- app.get_bundle calls register_interactive before this function ever
    runs, precisely so a request that turns out to be a cache hit still
    counts as evidence the caller has moved on to a new key, for whatever
    OTHER, still-building interactive request this one's registration may
    supersede (see register_interactive's own comment).
    """

    cached = _read_optional(
        bundle_path(geometry.slugify(export_name), material, pattern, size, thickness)
    )
    if (
        cached is not None
        and all(_has_key_path(cached, key) for key in REQUIRED_BUNDLE_KEYS)
        # Fix round 1 (review finding I4): presence alone is not enough
        # for a field whose VALUE, not merely its existence, can go
        # stale -- see REQUIRED_BUNDLE_VALUES' own comment. Runs only
        # after the presence check above has already confirmed every one
        # of these paths exists (short-circuited by the "and" chain), so
        # _key_path_value never has to handle a missing path.
        and all(
            _key_path_value(cached, path) == expected
            for path, expected in REQUIRED_BUNDLE_VALUES.items()
        )
        and _pieces_are_uniquely_keyed(cached)
    ):
        return cached
    return build_bundle(
        export_name, material, pattern, size, thickness,
        interactive_token=interactive_token)
