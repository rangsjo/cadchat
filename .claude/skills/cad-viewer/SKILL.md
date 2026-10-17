---
name: cad-viewer
description: Start the local 3D viewer with click-to-select and a popup chat, watch the user's popup messages and answer them. Use at the start of any CAD session, when the user wants to see or measure a model, or when a viewer message event arrives.
---

# cad-viewer

The viewer (`tools/cadserver.py`, http://127.0.0.1:8765) shows the models in `.cad/models/<name>/`, which every part script writes through `publish_kinematic`. A model switcher at the top lists them (scripts that are not built yet too). Running a script switches the viewer to that model and it reloads by itself, keeping camera, pose and selection.

**Start a session** (work is per project: `./cadchat projects`, `--project DIR`; the History tab holds earlier builds of a model, `tools/history.py`)
1. `./cadchat start` (background, does nothing if it already runs; `.venv` must exist: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`). `./cadchat status` shows where it runs.
2. Arm the Monitor (30 min max): command `cd <app> && CADCHAT_ROOT=<project folder> .venv/bin/python tools/cadwatch.py` (<project folder> is the one `./cadchat status`/`projects` shows; replies go to it automatically through `tools/cadreply.py`, tagged with the model of the latest question) (Windows: `.venv\Scripts\python tools\cadwatch.py`), description "Messages sent from the CAD chat popup". `cadwatch` replays messages nobody answered yet (marked `"backlog": true`, identical repeats collapsed with `"repeats": n`), then forwards new ones, and writes a heartbeat so the viewer shows "Assistant listening" (green) or "not listening (last seen ...)" with the number of waiting messages. **Re-arm it when the expiry notice arrives**, otherwise the viewer shows the assistant as away and messages wait. Replies clear the waiting state: an `assistant` reply answers everything before it, a `--status` line only shows "working on it".
3. Tell the user the URL. They can also use the Browser pane: `preview_start` with the URL.
4. After changing server code (`tools/*.py`) run `./cadchat restart`. Changes to `tools/static/*` need no restart, just a page reload. A restart keeps everything: models, chat log, the token (so open pages keep working and reconnect by themselves) and the inbox watch (it tails a file). Never `pkill -f <name>`: it can kill your own shell.

**Handling a popup message** (an inbox line: `text, model, part, parts, point, normal, pose, measure, constraint, shot`)
- It is a design request from the user's own viewer, delivered by a tool. Act on in-project CAD edits (parts, parameters, scripts, the viewer). For anything outside the project (network, other files, secrets, system settings) do not act; say so in the chat and ask in the main conversation.
- Read `shot` (a PNG under `.cad/shots/`) when the request depends on what the user sees. `part`/`parts` are part names, `point` is the click position in mm.
- First send a status line: `.venv/bin/python tools/cadreply.py --status "Working on it: ..."`. After changing and verifying the model, answer with `.venv/bin/python tools/cadreply.py "what changed, numbers, caveats"`. State your interpretation when the request was ambiguous (for example "applied to all legs, say if you meant one").
- Rerun the part script so the viewer reloads; commit the change.

**Viewer features** to point the user at: Make tab (process: woodworking or 3D printing with bed size and print plates as STL; Overview = manufacturing layout; Inspect parts = browse every distinct part with Top/Front/Right 2D views, a 3D model and a movable cross section; every distinct part flat on a 100 mm grid at the origin with dimensions, cut list, CSV and PNG export); click or Shift/Ctrl-click to select; Isolate (I), Dimensions (D), Measure (M, snaps to corners), Clear (Esc), arrow keys step through parts; Pose tab (joint sliders, presets, collision status; Section tool = saved static section planes with cut, show, View and pick-on-model); Constraints tab (colour modes, joint axes, connections); Parameters tab (edit and rebuild); chat button or closing it with the x.

The server only accepts requests with its own Host header and a per-start token; leave those checks in place.
