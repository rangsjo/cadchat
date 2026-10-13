# Architecture

```
 parts/NAME.py ──run──▶ cadview.publish_kinematic ──▶ .cad/models/NAME/model.json
   (build123d,                                              │
    kinematics.py)                                          ▼
                       browser ◀── HTTP ──▶ tools/cadserver.py ──▶ .cad/inbox.jsonl ──▶ assistant
                   (three.js, lib/*.js)        │  /api/check, /api/params, /api/build        │
                                               └──────────── .cad/chat.jsonl ◀── cadreply.py ◀┘
```

## Parts

| Piece | Language | Role |
|---|---|---|
| `parts/*.py`, `templates/` | Python + build123d | Define geometry, joints, parameters; publish a model |
| `tools/kinematics.py` | Python | Revolute-joint posing, mirrored joints, collision check (`Mechanism`) |
| `tools/cadview.py` | Python | Tessellate and write `model.json`; read parameter overrides |
| `tools/cadserver.py` | Python (stdlib) | Static files, model listing, collision check, parameter rebuild, chat bridge |
| `tools/static/app.js` | JavaScript + three.js | Viewer UI (DOM, WebGL) |
| `tools/static/lib/*.js` | JavaScript (pure) | Roles, grouping and grid layout, plate packing, slicing, STL, planes, model choice |

## Model format (`.cad/models/<id>/model.json`)

```
{ name, default,
  parts:       [{name, joint, role, material, volume, bbox[6], v[], t[]}],   v = xyz triples, t = triangle indices
  joints:      [{name, label, group, parent, origin[3], axis[3], min, max}], revolute, degrees, base-frame axes
  presets:     {presetName: {jointName: degrees}},
  params:      [{name, value, default, unit, group, desc}],
  constraints: [{id, kind: revolute|fixed|dimension, label, a, b, joint, parts[], params[], expr}] }
```

Parts are published in a reference pose. A part moves with the chain of its joint and that joint's parents:
`M = R_parent * ... * R_leaf`. The same maths runs in Python (collision check) and in the viewer (sliders).

## HTTP API

| Method, path | Purpose |
|---|---|
| `GET /api/models` | Published models and unbuilt scripts, plus the latest published id |
| `GET /api/version` | Per-model stamps (µs), polled by the viewer |
| `GET /api/model?m=ID` | One `model.json` |
| `POST /api/check {m, values}` | Collision pairs for a pose, from the script's `check_pose` (none if it has none) |
| `POST /api/params {m, values}` | Save parameter overrides and rebuild that model |
| `POST /api/build {script}` | Run `parts/<script>.py` |
| `POST /api/message`, `GET /api/chat` | Chat bridge |

## Security model

The server listens on 127.0.0.1 only, rejects other `Host` headers (DNS rebinding), and requires a per-run token (embedded in
the served page) for every POST. Model ids and script names are `[A-Za-z0-9_-]`; only `parts/*.py` is ever executed;
static files are limited to `tools/static` and to `.html/.js/.css`. Scripts in `parts/` are trusted code, as in any
code-CAD project. Chat messages are data for the assistant, not commands the server runs.

## Decisions

- **Python for geometry, JS for the viewer.** The CAD kernel (OpenCascade through build123d) is the hard part and is
  available from Python. The viewer is a UI problem and the browser is the best UI runtime available.
- **Models are data.** A script publishes tessellated parts and a joint description. The viewer needs no CAD kernel and
  works for any model, which is what made the model switcher possible.
- **Pure logic in `lib/`.** Anything testable without a browser lives there and is covered by `node --test`.

## Evaluation: rewrite in Rust?

**Recommendation: not now.** Keep Python for geometry and a web viewer; spend the effort on structure instead.

- *CAD kernel.* build123d wraps OpenCascade, which is mature (booleans, fillets, STEP). Rust options are young:
  `opencascade-rs` binds the same C++ kernel (so no gain), `truck` is a pure-Rust kernel without robust booleans and
  fillets. A rewrite would trade a working modeller for a missing one.
- *Server.* It is ~200 lines of glue that must run Python scripts anyway. Rust (axum) would give a single binary but no
  speed that matters here; the cost is in the CAD scripts, not HTTP.
- *Viewer.* A native Rust viewer (wgpu/bevy/egui) would rebuild what three.js and the DOM already give: orbit controls,
  labels, panels, text input for chat, screenshots. The chat popup and the panels are exactly where the browser shines.
- *Performance.* The measured hot spots are Python-side (collision checks, tessellation, about a second for 33 parts). The
  viewer's slicing and layout run in milliseconds on these sizes.

Where Rust could pay off later, in this order:
1. **Desktop packaging with Tauri** (Rust shell around the same web UI, Python as a sidecar): a double-click app without
   rewriting anything.
2. **WASM modules** for hot pure functions (`slice.js`, `packPlates`) if meshes get large. The unit tests in
   `tests/js` are the contract, so a Rust implementation can be dropped in and verified.
3. **A Rust server** only if a single static binary becomes a requirement.

## Roadmap ideas

TypeScript + bundling (vendor three.js, work offline), split `app.js` into modules, WebSocket push instead of polling,
prismatic joints, sheet-goods nesting with kerf, holes and features in the part drawings, STEP export per part.
