# Contributing

## Workflow: test first

1. Write a failing test that describes the behaviour (`tests/python/test_*.py` or `tests/js/*.test.js`).
2. Run it and watch it fail for the right reason.
3. Write the smallest change that makes it pass.
4. Refactor with the tests green, then run everything:

```bash
.venv/bin/python -m pytest -q
node --test tests/js/*.test.js
```

Keep viewer logic that does not need a browser in `tools/static/lib/*.js` (pure functions, no DOM, no three.js), so it can
be tested with `node --test`. DOM and WebGL code stays in `app.js` and is checked by hand in the browser.

New models need an acceptance test with numbers that were computed by hand (volume, bounding box, collision-free
presets, one deliberately wrong pose that must be caught). See `tests/python/test_folding_table.py` and
`tests/python/test_example_parts.py`.

## Conventions

- Units are mm, z is up. One model per script in `parts/NAME.py`, all dimensions in a `PARAMS` block, every part named.
- Posing and collision checking come from `tools/kinematics.py`; do not copy that code into model scripts.
- Anything the server runs (`check_pose`, rebuilds) must live in `parts/`; ids are `[A-Za-z0-9_-]`.
