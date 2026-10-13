---
name: cad-part
description: Create or modify a single parametric CAD part (build123d) in this project, run it, verify it and show it in the viewer. Use when the user asks to design, draw or change a part, bracket, shaft, plate, table, or any solid.
---

# cad-part

Project conventions are in `CLAUDE.md` (mm, z up, one part per file in `parts/`, exports in `exports/`).

1. **Start from the template:** `./cadchat new part NAME` (copies `templates/part.py` with the name filled in). Put every dimension in a parameter block at the top. For anything with moving parts use the `cad-mechanism` skill instead.
2. **Test first for new logic:** if the part needs a helper or a rule (a size from a standard, a derived dimension), write the failing test in `tests/python` first. For the part itself, add an acceptance test with hand-computed numbers (volume, bounding box), see `tests/python/test_example_parts.py`.
3. **State assumptions** the user did not give (diameter, standard sizes, tolerances) in the reply, and look up standards (DIN/ISO) rather than guessing.
4. **Run:** `./cadchat run NAME`. It must print size and volume and assert `part.is_valid`.
5. **Verify numerically** before saying done: compare volume or bounding box with a hand calculation, check hole/feature positions with `bounding_box()` or `.edges()` filters. build123d gotchas: do not name a variable `chamfer`/`fillet` (shadows the function); `Hole` needs a `BuildPart` context; `shape.intersect()` returns a `ShapeList`.
6. **Show it:** `./cadchat serve` (see `cad-viewer`), the model appears in the viewer's model switcher.
7. **Commit** the script (not `exports/` or `.cad/`, both are git-ignored) with a message describing the design change.

Name every solid you publish (`publish_kinematic` part names). The user selects parts by name in the viewer.
