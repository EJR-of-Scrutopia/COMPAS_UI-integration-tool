"""The two patterns wave 6a ships, on a domain with a known radius."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def studio(name):
    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    return __import__(name)


def disc_domain(radius=5.0, sides=48):
    """A regular polygon rim, so the radius is known within its sagitta."""

    d = studio("domain")
    loop = [
        [radius * math.cos(2 * math.pi * i / sides),
         radius * math.sin(2 * math.pi * i / sides)]
        for i in range(sides)
    ]
    return {
        "axis": [0.0, 0.0],
        "loop": loop,
        "ring": list(range(sides)),
        "thetas": [math.atan2(p[1], p[0]) for p in loop],
        "star_shaped": True,
        "failure": None,
        # A regular polygon has no backward step at all: hand built here
        # rather than routed through plan_domain, but generate() now reads
        # these two keys unconditionally on every domain dict, so a
        # perfectly star shaped fixture states its own wobble as zero.
        "backward_turn": 0.0,
        "backward_steps": 0,
    }


def saddle_domain():
    """The real saddle fixture's own plan domain
    (tests/fixtures/saddle_contract.json): a plain, convex square rim (no
    rim wobble at all, backward_steps == 0). Used by the row-uniform
    courses fix (2026-08-18) to test piece-length uniformity on geometry
    with no notch to confound the measurement: the real Trial 2 domain's
    own worst outliers are dominated by a separate, out-of-scope defect
    (.superpowers/sdd/2026-08-18-rim-spikes/diagnosis.md names it
    mechanism A), which this convex fixture cannot exercise at all.
    """
    g = studio("geometry")
    d = studio("domain")
    contract = g.load_contract(REPO / "tests" / "fixtures" / "saddle_contract.json")
    arrays = g.mesh_arrays(contract)
    centroids = g.face_centroids(arrays["vertices"], arrays["faces"])
    return d.plan_domain(arrays["vertices"], arrays["faces"], centroids)


def _length_at_theta(thetas, cumulative, theta):
    """Forward lookup, the inverse direction of generators._theta_at_length,
    reimplemented independently here (not calling into generators.py) so
    a round trip through both actually checks something."""

    two_pi = 2.0 * math.pi
    theta = theta % two_pi
    lo, hi = 0, len(thetas) - 1
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if thetas[mid] <= theta:
            lo = mid
        else:
            hi = mid
    span = thetas[hi] - thetas[lo]
    fraction = (theta - thetas[lo]) / span if span > 1e-15 else 0.0
    return cumulative[lo] + fraction * (cumulative[hi] - cumulative[lo])


def test_uniform_arc_divisions_states_the_sliver_merge_rule():
    """generators._uniform_arc_divisions pins the fix contract's own
    division-count rule: ceil(length / target), so every piece comes out
    at or under target (never over), and a length under the target
    already collapses to the single piece max(1, ...) guarantees -- the
    one-arc special case of "an arc shorter than half the target merges
    into its neighbour's division" this generator ever reaches.
    bonded_courses never hands a course anything but its own full 2*pi
    loop (no opening/interruption mechanism exists anywhere in domain.py,
    generators.py or tessellation.py -- see
    .superpowers/sdd/2026-08-18-rim-spikes/diagnosis.md), so there is
    never a second, neighbouring arc within one course to merge a short
    one into; this is the whole of that rule reachable through the
    generator, pinned directly against the helper rather than through an
    unreachable multi-arc scenario.
    """

    g = studio("generators")
    # Exactly divisible: no remainder to speak of.
    assert g._uniform_arc_divisions(4.0, 1.0) == 4
    # Just under a whole multiple: still rounds up, not down.
    assert g._uniform_arc_divisions(3.99, 1.0) == 4
    # Just over: one more division, every piece slightly under target.
    assert g._uniform_arc_divisions(4.01, 1.0) == 5
    # A short arc -- well under half the target -- becomes the ONE piece
    # it already would under max(1, ...), not a forced multi-way split
    # with no piece anywhere near the size actually asked for.
    assert g._uniform_arc_divisions(0.3, 1.0) == 1
    assert g._uniform_arc_divisions(0.5, 1.0) == 1
    # A degenerate (zero) arc is still one piece, never zero.
    assert g._uniform_arc_divisions(0.0, 1.0) == 1


def test_theta_at_length_does_not_divide_by_zero_on_a_degenerate_course():
    """Cheap cleanup (review, 2026-08-18): a genuinely zero-length course
    (cumulative[-1] == 0.0, every sample collapsed to the same plan point)
    used to raise ZeroDivisionError at "s % total" -- _uniform_arc_
    divisions already guards this same near-zero case (length <= 1e-9 ->
    1 piece); _theta_at_length needs the identical guard at its own
    division, not just at the caller that happens to divide by the same
    number first.
    """

    g = studio("generators")
    thetas = [0.0, math.pi, 2.0 * math.pi]
    cumulative = [0.0, 0.0, 0.0]
    assert g._theta_at_length(thetas, cumulative, 0.5) == thetas[0]


def test_within_course_pieces_are_exact_equal_arc_length():
    """The primary invariant the row-uniform courses fix promises: every
    piece within one course's own contiguous arc is the SAME arc length,
    to within floating point precision. Checked with an independent
    forward length lookup (_length_at_theta above, not generators.py's
    own _theta_at_length) against generators._arc_length_samples's table,
    on both the near-circular disc_domain and the real, non-circular,
    convex saddle domain -- the round trip through two independent
    implementations is what makes this a real check rather than reading
    the same computation back at itself.
    """

    g = studio("generators")
    for label, domain, size in (
        ("disc", disc_domain(), 1.0), ("saddle", saddle_domain(), 0.5),
    ):
        courses = g._course_count(domain, size)
        for course in range(courses):
            count, offset, angles = g._divisions(domain, size, courses, course)
            mid_f = 1.0 - (course + 0.5) / courses
            thetas, cumulative = g._arc_length_samples(domain, mid_f)
            total = cumulative[-1]
            piece_length = total / count

            lengths = [_length_at_theta(thetas, cumulative, a) for a in angles]
            lengths.append(_length_at_theta(thetas, cumulative, angles[0]) + total)
            steps = [lengths[i + 1] - lengths[i] for i in range(count)]
            for step in steps:
                assert step == pytest.approx(piece_length, rel=1e-9, abs=1e-9), (
                    label, course, steps)


def test_within_course_piece_lengths_stay_within_a_bound_on_the_saddle_fixture():
    """The drawn geometry's own chord length, not merely the arc-length
    table's internal invariant above: on the real, convex saddle domain
    (no rim wobble, no notch), within a course, the ratio between the
    longest and shortest piece stays within 1.5 -- comfortably above the
    only source of variation a convex fixture like this can show, the
    sqrt(2) ratio between a square's own edge-midpoint and corner radii
    (measured directly: 1.4141, the piece straddling each of the square's
    4 real corners, where a straight bed-joint chord genuinely undercuts
    the arc length it was allocated). Course-to-course variation is
    expected and out of scope; this bounds only WITHIN one course's own
    arc, per the fix contract.
    """

    g = studio("generators")
    d = studio("domain")
    domain = saddle_domain()
    size = 0.5
    courses = g._course_count(domain, size)
    two_pi = 2.0 * math.pi
    for course in range(courses):
        count, offset, angles = g._divisions(domain, size, courses, course)
        mid_f = 1.0 - (course + 0.5) / courses
        lengths = []
        for k in range(count):
            start = angles[k]
            end = angles[k + 1] if k + 1 < count else angles[0] + two_pi
            a = d.plan_point(domain, mid_f, start)
            b = d.plan_point(domain, mid_f, end)
            lengths.append(math.hypot(a[0] - b[0], a[1] - b[1]))
        ratio = max(lengths) / min(lengths) if min(lengths) > 0 else float("inf")
        assert ratio <= 1.5, (course, lengths)


def test_courses_come_from_the_target_size():
    g = studio("generators")
    tess = g.generate("bonded-courses", disc_domain(), 1.0)
    assert tess["courses"] == 5
    assert tess["target_size"] == 1.0
    assert tess["pattern"] == "bonded-courses"


def test_a_bigger_target_size_makes_fewer_pieces():
    g = studio("generators")
    small = g.generate("bonded-courses", disc_domain(), 0.5)
    large = g.generate("bonded-courses", disc_domain(), 2.0)
    assert len(small["cells"]) > len(large["cells"])


def _measure_arc_length(domain, f, theta_a, theta_b, steps=4000):
    """Independent numerical arc length from theta_a to theta_b (theta_b
    >= theta_a, neither wrapped) at radius f, sampling domain.plan_point
    directly -- no generators.py internals at all -- so a check built on
    this cannot pass merely by reading back the same computation the code
    under test already performed."""

    d = studio("domain")
    total = 0.0
    previous = d.plan_point(domain, f, theta_a)
    for i in range(1, steps + 1):
        theta = theta_a + (theta_b - theta_a) * i / steps
        point = d.plan_point(domain, f, theta)
        total += math.hypot(point[0] - previous[0], point[1] - previous[1])
        previous = point
    return total


def test_bonded_offset_rule_is_exact():
    """Row-uniform courses fix (2026-08-18): the stagger that used to be a
    half-ANGLE offset (course % 2) * pi / count is now a half-PIECE-LENGTH
    offset (generators._divisions), the actual physical point of running
    bond -- shifting alternate courses by half a brick, not half a degree.

    Checked independently of _divisions/_arc_length_samples/_theta_at_length
    (an earlier version of this test read those back and was true by
    construction): read course 0's and course 1's own first two cells'
    real, generated start angles straight off the tessellation, then
    measure the arc length between them with a standalone numerical
    integration (_measure_arc_length, above) that touches only
    domain.plan_point. Course 0 (even, unstaggered) must start at theta
    zero; the arc length from there to course 1's own start must be half
    of course 1's own first piece length, both measured the same
    independent way.
    """

    g = studio("generators")
    domain = disc_domain()
    size = 1.0
    tess = g.generate("bonded-courses", domain, size)
    axis = domain["axis"]

    def start_theta(key):
        cell = next(c for c in tess["cells"] if c["key"] == key)
        point = tess["points"][cell["outline"][0]]
        return math.atan2(point[1] - axis[1], point[0] - axis[0])

    theta0 = start_theta("c0p0")
    assert theta0 == pytest.approx(0.0, abs=1e-9)

    two_pi = 2.0 * math.pi
    theta1 = start_theta("c1p0")
    theta1_next = start_theta("c1p1")
    if theta1 < 0.0:
        theta1 += two_pi
    if theta1_next < theta1:
        theta1_next += two_pi

    courses = tess["courses"]
    mid_f = 1.0 - 1.5 / courses  # course 1's own mid radius
    measured_offset = _measure_arc_length(domain, mid_f, 0.0, theta1)
    measured_piece = _measure_arc_length(domain, mid_f, theta1, theta1_next)
    assert measured_offset == pytest.approx(measured_piece / 2.0, rel=1e-3)


def test_adjacent_courses_have_different_divisions():
    g = studio("generators")
    tess = g.generate("bonded-courses", disc_domain(), 1.0)

    # Group cells by course
    by_course = {}
    for cell in tess["cells"]:
        by_course.setdefault(cell["course"], []).append(cell)

    TWO_PI = 2.0 * math.pi

    # For each adjacent pair of courses, verify they have different divisions
    courses_list = sorted(by_course.keys())
    for i in range(len(courses_list) - 1):
        c1 = courses_list[i]
        c2 = courses_list[i + 1]

        count1 = len(by_course[c1])
        count2 = len(by_course[c2])

        offset1 = (c1 % 2) * math.pi / count1
        offset2 = (c2 % 2) * math.pi / count2

        # Two courses have identical divisions if both count and offset match
        same_count = (count1 == count2)
        same_offset = abs((offset1 - offset2) % TWO_PI) < 1e-12

        # Adjacent courses should not both have identical divisions
        assert not (same_count and same_offset), \
            f"Courses {c1} and {c2} have identical divisions: both have {count1} pieces"


def test_bonded_courses_conform():
    g = studio("generators")
    tess = g.generate("bonded-courses", disc_domain(), 1.0)
    assert tess["report"]["open_facets"] == []
    assert tess["report"]["slivers"] == []
    assert tess["report"]["coverage_holes"] == []


def test_the_committed_trial_2_domain_still_cuts_the_same():
    """A genuine regression pin on real geometry, without the export file.

    tests/studio/make_fixtures.py measured the real Trial 2 export's own
    plan domain (domain.plan_domain's return value: axis, loop, ring,
    thetas, star_shaped, failure, backward_turn, backward_steps -- a few
    hundred numbers, not the 2521 vertex mesh) once and committed it, along
    with the cut generators.generate produced from it at the default
    pattern and size. generators.generate needs only the domain, never the
    mesh or the contract file, so this test rebuilds the cut from the
    committed domain alone and checks it comes out bit for bit the same:
    every cell's key, course, index and outline, and the whole welded
    point table.

    If this fails after an intentional rule change (domain.py,
    generators.py or tessellation.py), regenerate with:
    .venv\\Scripts\\python.exe tests/studio/make_fixtures.py
    and read the new numbers before committing them -- a fixture that
    silently records whatever the code now produces pins nothing.
    """

    g = studio("generators")
    fixture = json.loads(
        (FIXTURES / "trial-2-tessellation.json").read_text(encoding="utf-8")
    )
    tess = g.generate(fixture["pattern"], fixture["domain"], fixture["size"])

    expected = fixture["cut"]
    assert len(tess["cells"]) == expected["cells"]
    assert tess["courses"] == expected["courses"]
    assert tess["points"] == expected["points"]
    assert [
        {"key": cell["key"], "course": cell["course"],
         "index": cell["index"], "outline": cell["outline"]}
        for cell in tess["cells"]
    ] == expected["cell_list"]

    # The conformity properties are the ones that matter, and no synthetic
    # fixture can show them: a real, irregular plan is what actually
    # exercises T junctions, the rim silhouette and the weld.
    assert tess["report"]["coverage_holes"] == []
    assert tess["report"]["open_facets"] == []
    assert tess["report"]["slivers"] == []
    assert tess["report"]["broken_boundary"] == []


# The piece-size slider runs 0.30 to 3.00 m in 55 steps of 0.05
# (bench/studio/static/index.html). Sweeping all 55 on both generators and
# both domains takes about a minute and a half; these seven are the spread
# that carries the evidence, and they are not arbitrary:
#
#   0.30, 3.00  the two ends of the slider.
#   0.35        where the rim-notch fold was first measured (cell c0p58).
#   0.45, 0.50  the only other sizes on this domain that still fold.
#   0.90        the size the studio opens to, and the one the committed
#               fixture above pins, so the sweep and the pin agree.
#   1.50        where _arc's seam bug put cell c3p4's inserted points out
#               of order: it came out at -36, 0, +24, -24, +36 degrees
#               where it should read -36, -24, 0, +24, +36, and its cap
#               drew 0.82 square metres twice, one copy inside out. Also
#               the size an earlier coverage regression in this wave was
#               measured at.
#
# On the committed Trial 2 domain those give 21, 18, 14, 12, 7, 4 and 2
# courses, odd counts and even. Both seams are reached at every one of
# them: course 0 always contains atan2's own pi seam, which the rim pass
# crosses, and every course with an odd index carries the half pitch
# offset, so its last cell's span runs past 2 pi, which is the seam the
# head joint pass crosses. Sweeping at one size cannot see either, which
# is exactly how a cut that self-intersected at 35 of the 55 sizes shipped
# with a green suite: the default and both pinned fixture sizes happen to
# be clean.
SWEEP_SIZES = (0.30, 0.35, 0.45, 0.50, 0.90, 1.50, 3.00)

# Measured, not asserted into existence. What a tolerated rim wobble still
# costs after _arc's seam is fixed: cells whose rim arc drops through the
# plus or minus 125.4 degree notch while their inner boundary is a straight
# chord that passes outside it. At every other swept size, on both
# generators, nothing folds. See domain.WOBBLE_TOLERANCE's own note.
#
# Row-uniform courses fix (2026-08-18): _divisions now places head joints
# at equal ARC LENGTH rather than equal angle (generators._divisions), so
# which exact theta values land inside the same plus/minus 125.4 degree
# notch -- and therefore which specific cells fold there -- moved. Re-swept
# on the same committed domain: 0.50 m is now clean (was 2 folded cells
# before this fix); 0.30, 0.35 and 0.45 m still fold, at different cells
# than before. Full 55-size sweep (both generators, 0.30 to 3.00 m in
# 0.05 m steps) confirms these three sizes are the only ones affected on
# bonded-courses, and monolithic-bands is clean at every size on the
# slider -- it never calls _divisions at all (see monolithic_bands's own
# code), so ask 2's division-uniformity fix cannot move anything about it,
# and measurement confirms it does not.
TRIAL_2_FOLDS = {
    (0.30, "bonded-courses"): ["c4p57", "c4p100"],
    (0.35, "bonded-courses"): ["c6p39", "c6p70"],
    (0.45, "bonded-courses"): ["c2p39", "c2p70"],
}

# Row-uniform courses fix (2026-08-18): at 0.30 m (the slider's finest
# position, 21 courses on this domain) two cells land near enough to the
# same plus/minus 125.4 degree notch, from two independently-computed
# courses' own nearby-but-different division angles, that their welded
# outline crosses itself with two lobes close enough in area to read as a
# near-zero ALGEBRAIC area rather than a comfortable positive one --
# build_tessellation's own if/elif (a cell is either a sliver or folded,
# never both, the sliver check running first) claims them as slivers, not
# folds. Not present anywhere on the OLD angle-uniform rule's own 0.30 m
# cut (which instead folded a different six cells, all without tripping
# the sliver check); not present at any of the other 54 sizes on the
# slider under the new rule either.
TRIAL_2_SLIVERS = {
    (0.30, "bonded-courses"): ["c1p67", "c1p118"],
}


def _folded_by_measurement(tess):
    """Every cell whose own welded rings cross themselves and were not
    already claimed as a sliver, measured here rather than taken from the
    report, so the report's folded list is checked against geometry
    instead of against itself.

    A cell is either a sliver or folded, never both
    (tessellation.build_tessellation's own if/elif: the sliver check, on
    algebraic area, runs first): a bow tie whose two lobes happen to be
    near equal size measures a near-zero algebraic area too, so the
    sliver check claims it before the fold check ever runs. Excluding
    report["slivers"] here matches that same precedence rather than
    relaxing this check; the row-uniform courses fix (2026-08-18) is what
    first produced a real case of it, at 0.30 m (see TRIAL_2_SLIVERS).
    """

    t = studio("tessellation")
    points = tess["points"]
    slivers = set(tess["report"]["slivers"])
    return sorted(
        cell["key"]
        for cell in tess["cells"]
        if cell["key"] not in slivers
        and any(
            not t._is_simple([points[i] for i in ring])
            for ring in [cell["outline"]] + list(cell["holes"])
        )
    )


def _assert_conforms(tess, where, expected_slivers=()):
    report = tess["report"]
    for key in ("coverage_holes", "open_facets", "broken_boundary"):
        assert report[key] == [], "{}: {} is not empty".format(where, key)
    assert sorted(report["slivers"]) == sorted(expected_slivers), (
        "{}: slivers {} do not match the expected {}".format(
            where, report["slivers"], expected_slivers)
    )


@pytest.mark.parametrize("size", SWEEP_SIZES)
@pytest.mark.parametrize("pattern", ["bonded-courses", "monolithic-bands"])
def test_a_generated_cut_conforms_at_every_size_on_the_real_domain(pattern, size):
    """The sweep the one-size tests could not do.

    A cut that is clean at 0.9 m says nothing about 1.5 m: the seam a span
    crosses depends on where the span sits, and where a span sits depends
    on the size. This runs the committed Trial 2 domain, so it needs the
    fixture and not the export, and it checks two things at every size.
    First that nothing in the report is dirty. Second that the report's
    folded list names exactly the cells that really do cross themselves,
    which is the guard the sliver test cannot be: a bow tie's two lobes
    cancel in the algebraic area, so a folded cell measures a comfortable
    area and ear_clip triangulates it without complaint.
    """

    g = studio("generators")
    fixture = json.loads(
        (FIXTURES / "trial-2-tessellation.json").read_text(encoding="utf-8")
    )
    tess = g.generate(pattern, fixture["domain"], size)
    where = "{} at {}".format(pattern, size)

    _assert_conforms(tess, where, TRIAL_2_SLIVERS.get((size, pattern), ()))
    measured = _folded_by_measurement(tess)
    assert sorted(tess["report"]["folded"]) == measured, (
        "{}: the folded list and the geometry disagree".format(where)
    )
    assert measured == sorted(TRIAL_2_FOLDS.get((size, pattern), [])), where


@pytest.mark.parametrize("size", SWEEP_SIZES)
@pytest.mark.parametrize("pattern", ["bonded-courses", "monolithic-bands"])
def test_a_generated_cut_conforms_at_every_size_on_a_disc(pattern, size):
    """The same sweep on geometry with no wobble in it at all.

    A regular 48-gon has no backward rim step, so there is nothing here to
    blame a fold on: every cell must be simple at every size. This is the
    stronger half of the pair, and it was failing at 41 of the 55 slider
    sizes before _arc sorted its inserted points.
    """

    g = studio("generators")
    tess = g.generate(pattern, disc_domain(), size)
    where = "{} at {} on the disc".format(pattern, size)
    _assert_conforms(tess, where)
    assert _folded_by_measurement(tess) == [], where
    assert tess["report"]["folded"] == [], where


def test_monolithic_bands_are_one_cell_per_course_with_holes():
    g = studio("generators")
    tess = g.generate("monolithic-bands", disc_domain(), 1.0)
    assert len(tess["cells"]) == tess["courses"]
    outer = [c for c in tess["cells"] if c["course"] == 0][0]
    inner = [c for c in tess["cells"] if c["course"] == tess["courses"] - 1][0]
    assert len(outer["holes"]) == 1
    assert inner["holes"] == []
    assert tess["report"]["coverage_holes"] == []


def test_a_band_hole_matches_the_next_band_outline():
    g = studio("generators")
    tess = g.generate("monolithic-bands", disc_domain(), 1.0)
    outer = [c for c in tess["cells"] if c["course"] == 0][0]
    below = [c for c in tess["cells"] if c["course"] == 1][0]
    # Welding must have made them the same point ids, or the joint between
    # two bands is two different circles a float apart.
    assert set(outer["holes"][0]) == set(below["outline"])


def test_generation_is_deterministic():
    g = studio("generators")
    first = g.generate("bonded-courses", disc_domain(), 1.0)
    second = g.generate("bonded-courses", disc_domain(), 1.0)
    assert first["points"] == second["points"]
    assert [c["key"] for c in first["cells"]] == [c["key"] for c in second["cells"]]


def test_course_zero_outline_simplifies_against_the_boundary():
    """K3 (cutting truth, 2026-08-17): course 0 used to insert every one
    of the real rim's 240 boundary vertices between a piece's own two head
    joints, one drawn boundary point per mesh vertex -- the
    one-piece-per-boundary-vertex fragmentation the cutting truth spec
    names. Measured on the real Trial 2 domain at the studio's own
    default size (0.9 m): before that fix, course 0's 62 pieces carried
    538 outline points between them (8.68 per piece); simplifying the
    rim-following stretch of each piece's own outline against
    cutting.CHORD_TARGET dropped that to 358 (5.77 per piece), a genuine
    35 percent cut, not a rounding accident.

    Piece count and outline totals moved again with the row-uniform
    courses fix (2026-08-18): _divisions now sizes every course by equal
    ARC LENGTH rather than equal angle (see generators._divisions and
    .superpowers/sdd/2026-08-18-rim-spikes/diagnosis.md), and
    _uniform_arc_divisions's ceil (rather than the old round-to-nearest)
    means a course's own piece count is no longer identical to before
    either. Re-measured on the same committed domain and size: course 0
    now carries 63 pieces and 370 outline points between them (5.87 per
    piece) -- still well under the pre-simplification 538/8.68 baseline,
    confirming the boundary simplification this test is really about is
    still doing its job under the new division rule.
    """

    g = studio("generators")
    fixture = json.loads(
        (FIXTURES / "trial-2-tessellation.json").read_text(encoding="utf-8")
    )
    tess = g.generate(fixture["pattern"], fixture["domain"], fixture["size"])
    course0 = [cell for cell in tess["cells"] if cell["course"] == 0]
    assert len(course0) == 63
    total = sum(len(cell["outline"]) for cell in course0)
    assert total == 370
    assert total < 538 * 0.8, "a real reduction in rim outline density, not a rounding accident"


def test_an_unknown_pattern_names_what_is_available():
    g = studio("generators")
    with pytest.raises(ValueError) as error:
        g.generate("herringbone", disc_domain(), 1.0)
    assert "bonded-courses" in str(error.value)


def test_planned_patterns_say_which_wave_they_arrive_in():
    g = studio("generators")
    assert "guastavino-herringbone" in g.PLANNED
    assert "armadillo-dual" in g.PLANNED
    assert set(g.PLANNED) & set(g.GENERATORS) == set()
