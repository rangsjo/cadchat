# cadchat

A small workbench for **code-CAD**: you describe parts and mechanisms in Python
([build123d](https://github.com/gumyr/build123d)), cadchat shows them in a local 3D viewer where you can click, measure,
cut cross sections, move joints, check collisions and prepare parts for the workshop or the 3D printer. A popup chat in
the viewer sends what you clicked, together with a screenshot, to an AI assistant (built for
[Claude Code](https://claude.com/claude-code)) that edits the model and answers in the same popup.

![viewer](docs/viewer.png)

## What you get

- **Viewer** (browser, three.js): orbit, click and multi-select parts, isolate, dimensions, point-to-point measuring with
  corner snapping, a model switcher for everything in `parts/`.
- **Mechanisms**: joint sliders, presets (open / closed / ...), live collision check that names the clashing parts,
  colour-coded constraints (movable joints, fixed connections, parametric relations).
- **Parameters**: every dimension is a named parameter you can edit in the viewer; the model rebuilds.
- **Section planes**: saved, static planes with cut faces, several at once.
- **Make tab**: every distinct part laid flat on a 100 mm grid with dimensions, a cut list (CSV), a part inspector with
  Top/Front/Right views, a 3D view and a movable cross section.
  *Woodworking*: material totals. *3D printing*: bed size check and print plates exported as STL.
- **Import and export**: STEP and STL in (button, drag and drop, `./cadchat import`, or `./cadchat watch FOLDER` for a Creo export folder); STEP assemblies with part names, STL and 3MF out. See [docs/CREO.md](docs/CREO.md).
- **Fast**: a warm build worker (rebuild in ~0.6 s instead of 2.7 s), cached polling, binary meshes. See [docs/PERFORMANCE.md](docs/PERFORMANCE.md).
- **Chat bridge**: click a part, type "make this 60 mm", get the change and an answer. The viewer shows whether the assistant
  is listening and where each message stands (sent, seen, working, answered); nothing is lost while it is away. Works with any assistant that can
  run `tools/cadwatch.py` (it forwards messages and keeps a heartbeat); the repository ships skills for Claude Code in `.claude/skills/`.

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
./cadchat run folding_table      # build the bundled example (the examples project is used until you create your own)
./cadchat start                  # viewer in the background: http://127.0.0.1:8765
```

### The menu bar

**File** (New project, New model from a template or the library, Open recent projects, Save version, Import, Export: pose STL, cut list, screenshot, workshop site for the
phone, and any STEP/STL your scripts wrote to `exports/`, Settings) · **View** (camera views and the display switches) · **Tools** (measure, section, isolate, collision check,
Joint library with the usual proportions) · **Assistant** (start listening, open chat, agent settings) · **Help** (quick start, shortcuts, how to resume, about).
**Settings** keeps the agent command, terminal, folder for new projects, default glue gap and chat behaviour in `~/.config/cadchat/settings.json`.

### Projects, and picking up again later

The app and your work are separate. A **project** is a folder with its own `parts/` (model scripts), `exports/` and `.cad/`
(built models, chat history per model, version history per model). The app only holds the tools, the viewer, `templates/`,
`library/` (reusable models) and `examples/` (a project to look at).

```bash
./cadchat init ~/cad/chairs --name "Dining chairs"   # a new project
cd ~/cad/chairs && /path/to/cadchat start            # a command works on the project around the current folder ...
./cadchat --project ~/cad/chairs start               # ... or name it; without either: the last one you used
./cadchat projects                                   # everything you have started, most recent first
./cadchat library                                    # reusable models;  ./cadchat add shaft --as rod  copies one into the project
```

**Coming back after a break:** `./cadchat start` (safe to repeat; each project gets its own port, the viewer shows the project name on top).
The model switcher lists every model of the project, the chat shows the whole conversation of the project (each question is labelled with the model it was about), and the
**History** tab lists every earlier build of that model (script and parameters, with what you had asked for) with a Restore button.
Chat replies only flow while an assistant session runs `tools/cadwatch.py`; the badge shows "Assistant away" when none does, and
your messages wait (state "queued") until one starts.

### The AI assistant: any provider

The chat talks to an AI **agent** you already have: Claude Code (Claude Pro/Max subscription or API key), GitHub Copilot CLI (any Copilot plan), OpenAI Codex CLI
(ChatGPT plan or API key), Gemini CLI, or any command line agent that can edit files and run commands. On the first start a short wizard shows what cadchat can do, finds the
agents installed on your machine, explains the sign-in and lets you choose how it answers: **once per message** (cheapest, works with every agent, nothing from earlier messages
is resent) or a **live session**. Run it again from **Help ▸ Set up the AI assistant**; the setup steps for each provider are in [docs/ASSISTANTS.md](docs/ASSISTANTS.md) and the rules
every agent follows are in [AGENTS.md](AGENTS.md). From a shell: `./cadchat bridge` (per-message mode) and `./cadchat assistant`.

### On the phone, in the workshop

```bash
./cadchat share              # <project>/share/index.html + one page per model: static, self-contained, no server needed
./cadchat share --serve      # the same, served on your wifi; prints the address to open on the phone
```

Each page shows the model in Front / Side / Top / 3D for every pose (open, folded, ...), with overall dimensions, tap a part for its size and position, **Measure**
(tap two corners for the distance, across and up), a cut list and the joints with their numbers. Pinch to zoom, drag to move, double-tap to fit. Small hardware is drawn as boxes
to keep the pages light (the table is 0.6 MB). Copy the folder to the phone, open it from any static host, or publish a page as an artifact.

### As an app (Ubuntu)

```bash
./cadchat install-launcher      # adds "CAD chat" to the app menu (remove with --uninstall)
```

The icon starts the viewer for your last used project and opens it in the browser. Right-click it for **Start assistant listening**, which opens a terminal with
Claude Code in this folder and a prompt that makes it follow the `cad-viewer` skill (start the viewer, arm the message watch, answer the popup messages).
The same is one click in the viewer: the chat shows a **Start assistant** button whenever nobody is listening. `CADCHAT_ASSISTANT_CMD` (default `claude`)
and `CADCHAT_TERMINAL` (default: the first terminal found) change what is started and where; `./cadchat app` and `./cadchat assistant` do the same from a shell.

Create your own models:

```bash
./cadchat new part bracket2          # a static part
./cadchat new mechanism lidbox       # parts + joints + presets + collision check
./cadchat run bracket2               # build and publish; the viewer switches to it
./cadchat list
./cadchat import part.step            # a STEP/STL from Creo or any CAD system
./cadchat watch ~/creo_exports       # import every export that appears
```

A model script is plain Python: parameters at the top, geometry with build123d, then `publish_kinematic(...)`.
See `templates/`, `library/parts/` (a shaft with a keyway, an L-bracket) and `examples/parts/` (a folding drop-leaf table).

## Woodworking joints

`tools/joints.py` cuts two boards to fit: `dowel_butt`, `dado`, `rabbet`, `half_lap` and `mortise_tenon`. Put the boards in their final position, overlapping by the
depth of the joint, and each function returns both boards cut (plus loose dowels), the parameters used and a note for the cut list; `joint.as_constraint(...)` shows
it in the viewer's constraint list. `joints.defaults(kind, thickness)` gives the usual proportions (tenon one third of the thickness and 1.5 x as long, dado a
third deep, half lap half, dowel a third). `library/parts/joinery_demo.py` is a bookcase and a frame using all of them (`./cadchat add joinery_demo`).

## Tests

```bash
.venv/bin/python -m pytest -q          # kinematics, publisher, server API, templates, example models
node --test tests/js/*.test.js         # layout, slicing, STL, section planes, model switching
```

The project is developed test first, see [CONTRIBUTING.md](CONTRIBUTING.md). A ready-made GitHub Actions workflow is in `docs/ci-workflow.yml` (copy it to `.github/workflows/ci.yml`). Design notes, the data format, the HTTP API,
the security model are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md); measured speed and the Rust question are in [docs/PERFORMANCE.md](docs/PERFORMANCE.md).

## Layout

```
tools/        server, publisher, kinematics, CLI     tools/static viewer (index.html, app.js, lib/*.js pure logic)
templates/    starting points for new models         library/     reusable models (`cadchat add`)
examples/     a project to look at                   tests/       pytest + node:test
docs/         architecture notes                     .claude/skills/  workflows for Claude Code

a project:    cadproject.json  parts/ (scripts)  exports/  .cad/ (models, chat, history; git-ignored)
```

## Status

Early but working. Revolute, sliding and coupled (mimic) joints, one model shown at a time, three.js is loaded from a CDN (pinned version).
The viewer binds to 127.0.0.1 and checks the Host header and a per-run token before accepting changes.

## License

MIT, see [LICENSE](LICENSE).
