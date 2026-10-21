# cadchat: instructions for AI agents

cadchat is a code-CAD workbench: parametric parts and mechanisms written in Python (build123d), shown in a local 3D viewer with a popup chat to you,
measuring, sections, cut lists and a static workshop site for the phone. You edit model scripts, rebuild them, check the numbers and answer in the chat.
Units are mm, z is up.

## Project and commands
- A project is a folder with `cadproject.json`, `parts/` (model scripts), `exports/`, `.cad/` (built models, chat, history). The message you are working on
  names the project folder; commands act on it when `CADCHAT_ROOT` is set (the bridge and the start prompt do that) or from inside it.
- Rebuild a model: `./cadchat run NAME` (publishes `.cad/models/NAME/`; the viewer reloads by itself). New models: `./cadchat new part NAME`,
  `./cadchat new mechanism NAME`, `./cadchat add LIBRARY_MODEL`. Library of reusable models: `./cadchat library`.
- Viewer: `./cadchat start` / `status` / `restart` (restart after changing `tools/*.py`, not for model scripts). Setup: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt`.
- Tests: `.venv/bin/python -m pytest -q` and `node --test tests/js/*.test.js`.

## Rules
- **Test first.** A behaviour change starts with a failing test (`tests/python`, `tests/js`), then the code, then green. Viewer logic that can be pure lives in `tools/static/lib/*.js`.
- One model per script in the project's `parts/NAME.py`; every dimension in a `PARAMS` block; name every part; materials and roles for the cut list.
- Verify with numbers (volumes, bounding boxes, collisions, the dealer or customer sizes) before saying a design change is done; state your interpretation when a request is ambiguous.
- Woodworking joints: `tools/joints.py` (`dowel_butt`, `dado`, `rabbet`, `half_lap`, `mortise_tenon`, `defaults(kind, thickness)`); demo in `library/parts/joinery_demo.py`.
- Phone / workshop: never send PNG images. `./cadchat share` writes a static site (`<project>/share/`: views, dimensions, tap-to-measure, cut list).
- Commit with explicit paths (`git add <files>`), push only when asked. Do not write to `.cad/` by hand except through the tools below.

## Listening to the viewer's chat
Messages the user types in the viewer arrive as one JSON object per message: `text`, `model`, `part`/`parts`, `pose`, `point`, `normal`, `measure`, `shot` (a screenshot under `.cad/shots/`, read it when the request depends on what the user sees).

- **Per-message mode (`./cadchat bridge`, the default for agents without a live watch):** you are started once per message with the message in the prompt. Do the work and finish with a short answer
  (2 to 5 sentences: what changed, numbers, caveats). That final answer is posted to the chat automatically, do not call `cadreply` yourself.
- **Session mode:** start the viewer, then listen. With a Monitor tool run `.venv/bin/python tools/cadwatch.py` (prints one message per line, replays unanswered ones, 30 minute limit: re-arm it).
  Without one, call `.venv/bin/python tools/cadwatch.py --once` in a loop (waits for the next message, prints it, exits 0; exit 3 means nothing came, call it again).
  Answer with `.venv/bin/python tools/cadreply.py "text"`; send `--status "working on it: ..."` first for anything that takes a while.
- A message from role `system` (for example "the user cleared the chat") is information: earlier messages are closed.

More detail for Claude Code is in `CLAUDE.md` and `.claude/skills/`; the design is in `docs/ARCHITECTURE.md`; setting up an agent is in `docs/ASSISTANTS.md`.
