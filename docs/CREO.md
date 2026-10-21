# Working with Creo (and other CAD systems)

**Short answer:** yes, through files, and it is simple. A live, parametric link needs PTC's customization APIs and a Creo
licence; that part is described below but not built or tested.

## How the live link works

cadchat does not replace Creo and Creo does not replace build123d. The parametric model stays in Creo (features, relations); the link only moves parameters in
and geometry out. build123d scripts, joints, presets and collision checks are untouched and keep working next to it.

```
Creo Parametric (Windows)  <--J-Link async-->  creo/bridge/CreoBridge.java  <--JSON lines-->  tools/creolink.py  <--files-->  cadchat server  <--HTTP-->  viewer (Creo tab)
```

- **Java bridge** (`CreoBridge.java`): attaches to the running Creo through PTC's J-Link asynchronous connection (needs the J-Link component of a normal Creo licence). It lists the
  model's user parameters and dimensions, sets a value, regenerates and exports STEP.
- **Python link** (`tools/creolink.py`): starts the bridge, mirrors Creo's state into `.cad/creo/state.json` and executes the commands the viewer queues in `.cad/creo/commands.jsonl`.
  A sync loop notices when the model changed in Creo.
- **Viewer to Creo:** in the Creo tab you change a parameter (for example `LENGTH`) and press Set. Creo regenerates, the link exports STEP into the watched folder, cadchat imports it as a
  model (`exchange.import_to_model`) and the viewer shows the new geometry, usually within seconds.
- **Creo to viewer:** edit in Creo; with auto-sync on, the same export and import runs by itself.
- **What the imported model is:** a static, named mesh model from STEP: measure, section, cut list, print plates and chat work; it has no joints. For a mechanism around a Creo part,
  write a build123d script that uses the imported geometry as a reference part.
- **Limits:** Creo allows one session for this kind of connection and must be idle (no dialog open) for API calls. Features, constraints and relations never leave Creo.
- **Status:** written against PTC's documentation and tested with stubs only (`tests/creo/stubs`, `tests/python/test_creolink.py`, `test_creo_e2e.py`). Expect fixes on the first real Creo.

The Creo tab is an optional plugin (`tools/plugins.py`): it shows when "Creo Parametric link tab" is ticked in Settings, or by itself while the link is running.
Without it the viewer is unchanged and nothing else depends on Creo.

## What works now (file exchange, STEP first)

| Direction | How | Result |
|---|---|---|
| Creo to cadchat | In Creo save a copy as **STEP** (or STL). Then `./cadchat import FILE`, or drop the file on the viewer, or use the import button | A model with one part per solid, names kept, nested assemblies flattened to dotted names (`sub.part`). Measure, section, inspect, cut list, print plates all work |
| Creo folder to cadchat, automatically | `./cadchat watch ~/creo_exports` | Every STEP/STL that appears or changes is imported once it has stopped changing (half-written exports are skipped) |
| cadchat to Creo | Scripts export `exports/NAME.step` through `tools/exchange.py`: one STEP product per part under a named assembly | Opens in Creo as an assembly tree with part names; no feature history |
| Printing | `exchange.export_stl_parts`, `exchange.export_3mf`, or the viewer's plate STL | One STL per part, 3MF, or a packed plate |
| Mesh only | `./cadchat export NAME` | One binary STL of a published model (reference pose) |

Verified here: a STEP assembly written by cadchat round-trips with names, volumes and positions intact (`tests/python/test_exchange.py`),
and the 750 KB folding-table STEP re-imports as 33 named parts in about 0.4 s. **Not verified: files written by a real Creo.**
No Creo was available, so check these on a first real export: units (a Creo model can be in mm or inch; STEP carries the unit and OpenCascade
should convert to mm, so confirm a known dimension), the part names, the assembly structure, and colours (not carried over).

## What Creo supports (from PTC documentation and third-party tables)

- STEP export and import with AP203, AP214 and AP242 protocols. According to PTC, parameters are exported with the AP214, AP203 and
  AP242 protocols when annotations are exported, while PMI graphics and cross-sections go out with AP242 only. See PTC's page on [exporting a part or assembly to STEP](https://support.ptc.com/help/creo/creo_pma/r12/usascii/data_exchange/interface/Exporting_Part_or_Assembly_to_STEP.html).
- IGES and Parasolid are listed by third-party tools as exchange formats with Creo ([Altair's list](https://help.altair.com/form/en_us/topics/shared/unity_basics/file_formats_st_r.htm)); STL export is standard. I did not find PTC's own format matrix in my searches, so confirm against your Creo version's Data Exchange help.
- Native `.prt` / `.asm` files are proprietary: other tools can only read them with a licensed translator. Use STEP.

## Live link: what it would take

PTC's customization interfaces are [Creo Toolkit (C/C++)](https://www.ptc.com/en/support/article/CS222094), Creo Object Toolkit
(C++), J-Link (Java), Web.Link (JavaScript) and a VB API, plus trail files for scripted sessions
([trail file basics](https://www.ptc.com/en/support/article/CS38257), [running one from the command line](https://www.ptc.com/en/support/article/CS289105)).
I found no Python or REST API for Creo Parametric. So a live bridge would be a small J-Link or Toolkit application inside Creo
that, when a parameter or the model changes, exports STEP into the watched folder, and optionally reads back parameter values.
cadchat already covers the other half (`watch`, parameters in the viewer). It needs a Creo licence with the API option to build
and test, so it is not part of this repository.

## Practical notes

- Creo runs on Windows; cadchat runs on Linux, macOS and Windows. Share a folder between the machines, or run both on Windows.
- Licences: Creo has no free commercial tier. Student and academic editions and a 30-day trial exist; Creo Design Essentials was listed
  around US$3,600 per year in mid-2026 by a reseller ([Tristar](https://www.tristar.com/creo-parametric/software-pricing/)); check PTC for current prices.
- Exchange is geometry plus names. Features, constraints and relations stay in Creo; cadchat's joints and parameters stay in the scripts.
