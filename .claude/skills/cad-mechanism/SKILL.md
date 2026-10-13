---
name: cad-mechanism
description: Build a jointed CAD mechanism (hinges, folding parts, swing legs, gates) with joint sliders, presets, constraints, editable parameters and a collision check in the cadchat viewer. Use when anything must move, fold or be tested for clearance.
---

# cad-mechanism

Start from `./cadchat new mechanism NAME` (a hinged-lid box); the finished reference is `parts/folding_table.py`. Posing and collision checking live in `tools/kinematics.py` (`Mechanism`, `mirrored_joint`), do not copy that code into scripts.

**Model**
- Build every part in one *reference pose* (e.g. fully open). Parts that move name a `joint`; fixed parts use `None`.
- A joint is revolute: `origin` and `axis` in the reference pose, `min`/`max` degrees, `parent` = joint that carries it (child-of-child chains work, e.g. outer flap on inner flap).
- Positive angle is right-handed about `axis`. Mirrored (left) copies: negate the x of `origin` and use axis `[ax, -ay, -az]` (axial vector under an x-mirror) so the same angle means the same motion.
- Pose maths (same in Python and the viewer): leaf joint first, then each parent: `M = R_parent * ... * R_leaf`.
- `presets` = named joint-value sets; the first is the default view.
- `check_pose = mech.check` must exist at module level and return `[[a, b, mm3], ...]`. The server imports the script and calls it on every slider move, so keep the top level free of exports (those go under `if __name__ == "__main__":`).
- `_exempt(a, b)` lists pairs that legitimately overlap (hinge hardware, tenoned rails). Keep it short and justified; never exempt to hide a real clash.

**Design for folding**
- Hinge on the *underside* edge so panels hang outward without overlapping; a 180 degree fold goes under the parent. Put hinge barrels in a notch cut from both panels.
- A fold that collides is information: report it with the colliding pair names, do not silently exempt it.

**Constraints and parameters (shown in the viewer's Constraints and Parameters tabs)**
- `constraints`: dicts with `id, kind (revolute|fixed|dimension), label, a, b, joint, parts, params, expr`. `a`/`b` draw the dashed connection line; `parts` are highlighted on click; `params` name the parameters it depends on; `expr` is a readable formula with the current numbers. Generate one per joint, per fixed connection and per derived dimension.
- `PARAMS = {name: (default, unit, group, description)}`; values come from `.cad/params.json` overrides. All dimensions belong in `PARAMS` so the user can edit them and the model rebuilds.

**Tests:** acceptance tests in `tests/python` (see `test_folding_table.py`): every preset collision-free, expected sizes, and one deliberately wrong pose that must be caught. Write them before changing joints or geometry.

**Workflow:** run the script (prints each preset's size and collisions), fix until clean, `tools/cadstart.sh`, open the viewer, drag the sliders. When the viewer reports a collision, reproduce it with `check_pose({...})` in a script and fix the geometry or the joint limits.
