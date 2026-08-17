# Bench Studio

A local web UI for viewing and cutting Grasshopper thrust-network vault
studies. It is the downstream step after
[COMPAS-workflow-GH_native](https://github.com/EJR-of-Scrutopia/COMPAS-workflow-GH_native),
the Grasshopper plugin that solves a vault's thrust network and exports it:
drop that export here, and the studio tessellates it into masonry, lets you
walk the cutting sequence stage by stage, and renders the result. Rhino is
never required for any of that.

## Prerequisite

Python 3.12 or later, on PATH. The launcher finds it through the `py`
launcher (`py -3.12`, falling back to `py -3`), which Python's own Windows
installer sets up for you if you tick "Add python.exe to PATH" and "py
launcher" during install. If neither resolves, the launcher tells you so
and stops rather than guessing.

## Quick start

Double-click **`Launch Bench Studio.cmd`**.

On first run it:

1. Creates a Python virtual environment at `%LOCALAPPDATA%\BenchStudio\venv`.
2. Installs `requirements.txt` into it, with the install output visible so
   you can see it working (and see clearly if something goes wrong).
3. Picks a free port starting at 8600.
4. Starts the local server hidden (no console window of its own) and opens
   it in your browser. The launcher's own window prints where the log is,
   then closes; the server keeps running.

Every later run skips straight to step 3, or, if Bench Studio is already
running, straight to opening the browser on it. The venv persists, and `pip
install` is quick when nothing changed. See "Logs and stopping" below for
how to check on it or shut it down.

## Logs and stopping

The server runs hidden, not in a console window, so there is nothing to
close to stop it. Instead:

- **Logs** live at `%LOCALAPPDATA%\BenchStudio\logs`, one file per run
  (`server-YYYYMMDD-HHmmss.log` for stdout, plus a matching `.err.log` for
  stderr). Only the newest 10 runs are kept; each launch deletes older
  ones. `Launch Bench Studio.cmd` prints the current run's log path before
  it closes.
- **Stopping**: double-click **`Stop Bench Studio.cmd`**. It reads the PID
  `Launch Bench Studio.cmd` wrote to `%LOCALAPPDATA%\BenchStudio\server.pid`,
  checks it is still a `python` process before touching it, stops it, and
  removes the pidfile.
- **Day to day**, the on-screen event log inside the studio itself (not
  the log files above) is what you actually watch while using it; the
  files on disk are for when something goes wrong and you need to see
  what the server printed.

## Updating

Double-click **`Update.cmd`**. If Bench Studio is running, it stops it
first (same as `Stop Bench Studio.cmd`), since `launcher/` is one of the
things about to be replaced. Then it downloads this repository's latest
`main` as a zip and replaces the app files (`bench/`, `src/`, `launcher/`,
`requirements*.txt`, `README.md`) with the new versions. It prints what it
changed as it goes.

It is a plain file-replace, not a merge, and it says so. It never touches
your data: `bench/studio/hdri/` (rendered environment maps), `bench/demo/
upload from grasshopper/` (your exports), and `bench/studies/` (studies and
their solved results) are always skipped, whichever way this runs.

## Create Desktop Shortcut.cmd

Double-click it once to drop a "Bench Studio" shortcut on your desktop that
points at `Launch Bench Studio.cmd`, so you do not have to keep this folder
open to start the studio.

## The workflow, in brief

1. In Grasshopper, the Export component writes a matched pair of files
   (`<name>-compas.json`, `<name>-contract.json`) for a solved vault.
2. Drop both into `bench/demo/upload from grasshopper/`, or upload them
   through the studio's own upload endpoint.
3. Pick a tessellation pattern, a target piece size, and a material
   thickness; the studio cuts the thrust mesh into masonry pieces.
4. Walk the build sequence stage by stage. Each stage can be analysed: a
   real per-stage structural solve (needs the optional `.venv-fea`
   environment) and a rigid-block stand/fall verdict (needs the optional
   `.venv-cra` environment), both documented in `docs/BENCH.md`. Neither is
   required to view and cut a study; they are advanced, opt-in checks.
5. Render the result, with the day-cycle lighting and HDRI environment
   controls in the viewer.

Set up the optional FEA solve environment with `launcher\setup-fea.cmd`:
it builds `.venv-fea` and everything `requirements-fea.txt` lists into
it, then points `bench/studio/staging.py` at it. One step it cannot
script: download OpenSees by hand from https://opensees.berkeley.edu/
and run `bench/scripts/install_opensees.py` against it, exactly as the
setup script's own final output explains. The CRA environment
(`.venv-cra`) is separate again, still built by
`bench/scripts/setup_cra_env.sh`, unchanged by any of this.

`docs/BENCH.md` is the fuller reference for the export format, the three
Python environments, and the solver internals.

## Optional: solver demos

`bench/demo/` also carries nine older, clickable demo scripts predating
the studio (`bench/demo/README.md` documents each one). Six of them,
`01_solve_pavilion.py`, `02_diagrams.py`, `03_load_cases.py`,
`04_masonry_blocks.py`, `05_robot_placing.py`, and `08_your_vault.py`,
import `ananke_equilibrium`, the solver package this repo does not carry
on purpose (the bench and the plugin never import each other's runtime;
see `docs/BENCH.md`). To run them, install the optional extra:

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-demos.txt
```

This is a separate, heavier environment than the studio's own `.venv`
(numpy, scipy, compas, compas_fab, compas_dem, compas_viewer, and more),
not something `Launch Bench Studio.cmd` installs for you.

`05_robot_placing.py` is worth calling out on its own: it is analytical
inverse-kinematics prior art the studio does not otherwise show, a UR5
placing the tessellated vault's blocks with closed-form IK, exact and
instant, no ROS and no simulator anywhere.

## Data folders

`bench/studio/hdri/`, `bench/demo/upload from grasshopper/`, and
`bench/studies/` hold your renders, your exports, and your studies. Updates
never touch them; back them up yourself if you care about keeping them.
