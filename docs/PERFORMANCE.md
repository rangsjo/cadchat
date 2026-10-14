# Performance review

Measured on the bundled folding table (33 parts, 8 joints, 2,796 triangles), Linux, Python 3.14, build123d 0.13 (OpenCascade).
Re-run the numbers with the scripts described at the end before and after any optimisation.

## Where the time goes

| Step | Time | Who spends it |
|---|---|---|
| `import build123d` (loads OpenCascade) | 1,360 ms, once per process | OpenCascade shared libraries |
| Build the 33 parts and 8 joints | 77 ms | OpenCascade modelling |
| Tessellate all parts | 183 ms | OpenCascade meshing |
| Collision check of one pose | 80-95 ms | 73 ms in `BRepAlgoAPI.Build` (18 boolean ops, about 4 ms each), the rest is Python bookkeeping |
| STEP / STL export of the table | 58 / 24 ms | OpenCascade |
| Moving a joint slider in the viewer | 0.7 ms | JavaScript (matrices for 33 meshes) |
| Slice a 1,000,000 triangle mesh | 42 ms | JavaScript |
| Group, grid-lay out 2,000 parts / pack 2,000 print items | 3 + 0.3 ms / 10 ms | JavaScript |

Almost everything that costs real time is C++ inside OpenCascade or process start-up. The Python and JavaScript we wrote is
a small share, so a rewrite of our code in Rust would not change what the user waits for.

## What was slow for the user, and what changed

| Interaction | Before | After | Change |
|---|---|---|---|
| Edit a parameter or press rebuild (folding table) | 2.7 s | 0.63 s | A long-lived worker keeps build123d loaded (`tools/cadworker.py`) |
| Rebuild of a small part (bracket) | 2.0 s | 0.1 s | same |
| Viewer polling (`/api/version`, every 1.5 s) | 13.9 ms | 1.3 ms | stats the files instead of parsing every `model.json`; listing cached by file stamp |
| Collision check per slider move | 155-257 ms (browser round trip) | 83-178 ms | pairs that move together are computed once and reused |
| STL download, 200k triangles | 506 ms (ASCII) | 16 ms (binary, 10 MB) | `toBinaryStl` |
| Publish a 1M triangle part | 3.4 s | 0.6 s | binary base64 meshes instead of JSON number lists |
| Load a 1M triangle model in the browser | 399 ms | 119 ms | typed-array decode |
| Model size on disk, this table | 258 KB | 265 KB | about equal for small meshes (the constraint text dominates); about 1/3 smaller for large ones |

The remaining collision time is OpenCascade booleans. The per-move cost is small enough for interactive use (the viewer waits
250 ms after you stop dragging), but it grows with the number of overlapping part pairs.

## Is Rust worth it?

Not for what is slow today. Reasons, with the numbers above:

- The hot spots are OpenCascade (C++), so they run at native speed already. Python is about 10-20 % of a collision check and
  a few percent elsewhere.
- Our JavaScript processes a million triangles in tens of milliseconds.
- Real wins came from architecture: a warm process, caching, binary formats.

Where Rust could pay off, in order of expected value:

1. **Mesh-based collision** instead of OpenCascade booleans. A bounding-volume hierarchy over the tessellated parts
   (for example with the `parry3d` crate, exposed to Python with PyO3) answers "do these two parts overlap" in microseconds,
   not milliseconds. That would matter for assemblies with hundreds of overlapping pairs. This is the one experiment worth
   doing. Acceptance test: identical results to the OpenCascade check on every preset in `tests/python/test_folding_table.py`
   and at least 5x faster on a generated 500-part assembly. Not done yet; the speed-up is an estimate, not a measurement.
2. **WASM for the pure libraries** (`slice.js`, layout, plate packing) only if meshes grow beyond a few million triangles.
   `tests/js` is the contract for a drop-in replacement.
3. **A Tauri desktop shell** (Rust around the same web UI) for a double-click app. That is packaging, not speed.

A full rewrite of viewer and server in Rust is not recommended: the CAD kernel stays Python/C++, and the browser UI (panels,
labels, chat popup, three.js) is where the browser is strongest.

## Reproduce

The measurements came from ad-hoc scripts: `time ./cadchat run NAME` for rebuilds (process start included),
`cProfile` around `Mechanism.check`, `performance.now()` around the slider handler, and a Node script that feeds generated
meshes to `tools/static/lib/*.js`. Timing assertions inside the test suite are deliberately coarse (binary STL must beat ASCII)
to avoid flaky tests.
