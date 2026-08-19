"""The one exception type every curated cutting-engine refusal raises.

Fix batch, bundle honesty (2026-08-19): before this module existed,
bundle.build_tessellation_for caught ANY ValueError out of the
generated-cut branch (domain.plan_domain, generators.generate) and
re-raised it as bundle.CutRefused, which build_bundle then reports as a
polite "this plan cannot be cut" uncut bundle. That catch could not tell
a CURATED refusal -- a message that means "this geometry cannot be cut
politely": the rim has no boundary, a boundary vertex branches, no loop
contains the others, two loops overlap, an opening self-crosses, the
axis falls inside an opening, the outer rim is not star shaped, or a
monolithic-bands cell is asked to cross an opening it cannot yet clip --
apart from a plain ValueError that is a genuine bug in the engine
itself, which was then also swallowed and reported as though it were a
refusal on otherwise valid geometry. PlanRefused gives every curated
site a type of its own: bundle.py's catch narrows to it, and any other
ValueError propagates as the bug it is.

PlanRefused subclasses ValueError, deliberately, so every existing
`pytest.raises(ValueError, ...)` message pin on these sites stays green
unchanged -- only the TYPE narrows at the one place that reads it
(bundle.build_tessellation_for), never the text a caller sees.
"""

from __future__ import annotations


class PlanRefused(ValueError):
    """A curated refusal on otherwise valid geometry, raised by name from
    domain.plan_domain (the axis falls inside an opening), openings.
    extract_loops and openings.classify (no boundary, a branching
    vertex, no loop containing the others, overlapping loops, a
    self-crossing opening), and generators.generate (the outer rim is
    not star shaped, or monolithic-bands is asked to cross an opening it
    cannot yet clip) -- see this module's own docstring for why the type
    exists and what it deliberately leaves alone.
    """
