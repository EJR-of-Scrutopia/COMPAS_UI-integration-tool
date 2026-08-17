"""Play-button launcher for the studio, in the main venv.

Same bootstrap discipline as the demos: hand this file to .venv's
interpreter if the picker chose something else, then serve on localhost.

launcher/launch.ps1 in this repo runs this file directly with its own venv
python and sets ANANKE_DEMO_BOOTSTRAPPED=1 first, so ensure_venv() below
returns immediately instead of hunting for a ".venv" directory that does
not exist in this layout (the launcher's venv lives under
%LOCALAPPDATA%\\BenchStudio, not beside this file). BENCH_STUDIO_PORT lets
the launcher hand over whichever free port it picked; it defaults to 8600
when unset, unchanged from upstream.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[0] / "demo"))
sys.path.insert(0, str(HERE))

from _bootstrap import ensure_venv  # noqa: E402

ensure_venv(__file__)


def main() -> int:
    import uvicorn

    from app import create_app

    port = int(os.environ.get("BENCH_STUDIO_PORT", "8600"))
    print("Bench Studio at http://127.0.0.1:{}".format(port))
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
