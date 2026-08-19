"""Keep the API tests out of environments without fastapi.

Only the app tests need fastapi; geometry, tessellation, subdivision and
bundle tests are stdlib-only and always collect. Same per-suite
prerequisite pattern as tests/fea/conftest.py and tests/legacy/conftest.py.
"""

import sys
from pathlib import Path

import pytest

collect_ignore_glob = []

try:
    import fastapi  # noqa: F401
except ImportError:
    collect_ignore_glob = ["test_app*.py"]

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _reset_studio_state():
    """Every studio test starts and ends with a clean slate: an empty
    in-process cut memo, no in-flight build holders, no interactive
    registrations.

    bundle._cut_memo, bundle._cut_inflight and bundle._interactive_live
    are all process globals keyed only on (export_name, pattern, size) or
    on export name alone, so anything one test leaves in any of them
    leaks into the next one that happens to reuse the same key against
    its own tmp_path upload dir. Fix 10 (bundle honesty, 2026-08-19):
    bundle.reset_studio_state() clears all three together -- see its own
    docstring for why this is a SEPARATE, test-only function rather than
    an extension of bundle.clear_cut_memo() itself, which stays exactly
    as narrow as it always was because it also runs from a live path
    (app._invalidate_studio_cache, on every real export re-upload).
    Same sys.path dance test_bundle.py's own studio() helper does,
    tolerating ImportError so a suite run without the studio package on
    the path (or without its dependencies) still collects.
    """

    path = str(REPO / "bench" / "studio")
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import bundle
    except ImportError:
        yield
        return
    bundle.reset_studio_state()
    yield
    bundle.reset_studio_state()
