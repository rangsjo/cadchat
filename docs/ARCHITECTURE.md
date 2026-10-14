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
| `tools/cadserver.py` | Python (stdlib) | Static files, model listing, collision check, parameter rebuild, import, chat bridge |
| `tools/cadworker.py` | Python | Warm process that runs scripts and imports (build123d loaded once) |
| `tools/exchange.py` | Python | STEP assembly export, STEP/STL import, 3MF/STL export |
| `tools/static/app.js` | JavaScript + three.js | Viewer UI (DOM, WebGL) |
| `tools/static/lib/*.js` | JavaScript (pure) | Roles, grouping and grid layout, plate packing, slicing, STL, planes, model choice |

## Model format (`.cad/models/<id>/model.json`)

```
{ name, default,
  parts:       [{name, joint, role, material, volume, bbox[6], v64, t64}],   v64 = base64 float32 xyz, t64 = base64 uint32 triangle indices
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
| `POST /api/build {script}` | Run `parts/<script>.py` in the warm worker |
| `POST /api/import?name=&ext=` | Upload a STEP/STL (raw body) and publish it as a model |
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

## Rust

Measured, not assumed: see [PERFORMANCE.md](PERFORMANCE.md). The short version: the time is in OpenCascade and process start-up, not in our
Python or JavaScript. The one promising Rust experiment is mesh-based collision (BVH) as a faster alternative to OpenCascade booleans.

## Roadmap ideas

TypeScript + bundling (vendor three.js, work offline), split `app.js` into modules, WebSocket push instead of polling,
prismatic joints, sheet-goods nesting with kerf, holes and features in the part drawings, STEP export per part.
