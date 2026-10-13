---
name: cad-iterate
description: The working loop for improving a CAD design step by step with the user: capture references and decisions, change parameters, verify with numbers, show, commit. Use when refining an existing design or starting a new project from reference photos or dimensions.
---

# cad-iterate

1. **Reference first.** Put photos, links and measurements in `reference/` (create it). Keep `reference/NOTES.md` with: sources, what is verified, what is a guess, open questions. When the user wants fidelity to a real object, find real dimensions and photos (search, dealer pages) before modelling, and say which parts are guesses.
2. **Parametric from the start.** All dimensions in a parameter block (`PARAMS` for mechanisms). A change request becomes a one-line parameter edit where possible.
3. **Test first, small steps.** One change per request. Write or extend the failing test (`tests/python`, `tests/js`) before the change; run the script; it prints size, volume/mass, and collisions per pose. Run the whole suite before committing.
4. **Verify with numbers, not looks.** Hand-check a volume, a clearance, a limit angle. A collision-free closed pose and a stable open pose are acceptance tests for mechanisms.
5. **Show it.** Viewer reloads on rerun; use the screenshot of the Browser pane to check your own result before reporting.
6. **Report honestly:** what changed, the numbers, assumptions, and anything that is still a guess or fails a check.
7. **Commit** each accepted change (`git add -A && git commit`), message = the design change. Easy rollback is what makes bold experiments safe.
8. **Record decisions** that are not visible in the code in `reference/NOTES.md` (why a dimension, why a joint limit).

Typical user requests and the move:
- "make it X mm / rectangular / thicker" → edit the parameter, rerun, confirm numbers, reply in chat.
- "can it fold / does it clash" → `cad-mechanism`, sweep the joint range with `check_pose`.
- "what is connected to what" → Constraints tab; if constraints are missing, add them to the script.
- "similar to <real product>" → references first, then a model that states its guesses.
