# cadchat

Code-CAD workbench: parametric parts and mechanisms written in Python (build123d), shown in a local 3D viewer with a
popup chat to the assistant, measuring, cross sections and manufacturing views (woodworking cut lists, 3D-print plates).
Units are mm, z is up.

## Commands
- Projects: a project is a folder with `cadproject.json`, `parts/`, `exports/`, `.cad/`. Commands act on the project around the cwd, else `--project DIR`, else the last used one (`./cadchat projects`; `init DIR` creates one; `library` / `add NAME` copy reusable models in).
- Joints: `tools/joints.py` (`dowel_butt`, `dado`, `rabbet`, `half_lap`, `mortise_tenon`, `defaults(kind, t)`), demo in `library/parts/joinery_demo.py`. Launcher: `./cadchat install-launcher`, `./cadchat app`, `./cadchat assistant`.
- Phone / workshop: never send PNGs. `./cadchat share` writes a static site (`<project>/share/`: views, dimensions, tap-to-measure, cut list); publish a page with the Artifact tool or use `share --serve`.
- Assistants: any agent can answer the chat: `./cadchat bridge` runs the chosen agent once per message (claude -p, copilot -p, codex exec, gemini -p), `cadwatch.py --once` lets agents without a Monitor tool listen; providers in `tools/providers.py`, wizard in the viewer (Help), docs in `docs/ASSISTANTS.md`.
- Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt`
- Viewer: `./cadchat start` / `restart` / `stop` / `status` (http://127.0.0.1:8765; `serve` runs it in the foreground), new model: `./cadchat new part NAME` or `./cadchat new mechanism NAME`
- Import from Creo or any CAD: `./cadchat import FILE.step`, `./cadchat watch FOLDER` (see `docs/CREO.md`)
- Creo link (Windows): `creo\start.cmd` (see `creo/README.md`); tests cover it against a stub of the J-Link classes
- Build a model: `./cadchat run NAME` (publishes it to `.cad/models/NAME/`; the viewer reloads by itself)
- Tests: `.venv/bin/python -m pytest -q` and `node --test tests/js/*.test.js`

## Rules
- **Test first.** Every behaviour change starts with a failing test (`tests/python`, `tests/js`), then the code, then green.
  Pure logic for the viewer lives in `tools/static/lib/*.js` so it can be tested without a browser.
- One model per script in the project's `parts/NAME.py`; all dimensions in a `PARAMS` block; name every part.
- Verify with numbers (volume, bounding box, collisions) before saying a design change is done.

## Skills (`.claude/skills/`)
- `cad-part`: one static part. `cad-mechanism`: jointed model with sliders and a collision check.
- `cad-viewer`: run the viewer, watch popup messages (`.cad/inbox.jsonl`), reply with `tools/cadreply.py`.
- `cad-iterate`: the working loop (references, parametric edits, numeric checks, commits).

Instructions for any AI agent (Copilot CLI, Codex, Gemini, ...) are in `AGENTS.md`; setting up an agent: `docs/ASSISTANTS.md`.
Architecture and design notes: `docs/ARCHITECTURE.md`. Reference model: `examples/parts/folding_table.py`. Reusable models: `library/parts/`. Version history of every model: `.cad/models/<id>/history/` (History tab, `tools/history.py`).
