# Creo link (experimental)

A live link between **PTC Creo Parametric** and cadchat. You change a parameter or dimension in the cadchat viewer, Creo
regenerates, and the new geometry comes back into the viewer (measure, sections, cut list, print plates). The reverse also
works: edit the model in Creo and cadchat follows. It needs a Creo licence. It is **experimental and was not tested against a
real Creo** (none was available while writing it); see "What is verified" at the end.

## Start everything with one command (Windows)

```bat
creo\start.cmd
```

First run: installs Python 3.12 and a JDK with `winget` if they are missing, builds a Python environment (a few minutes),
finds your Creo, starts Creo if it is not running (use `--no-launch` to only attach), starts cadchat, connects and opens
`http://127.0.0.1:8765/#creo`. Leave the window open; Ctrl+C stops the link.

From a fresh Windows machine (once this branch is on GitHub):

```bat
winget install -e --id Git.Git && git clone -b experimental/creo https://github.com/rangsjo/cadchat && cadchat\creo\start.cmd
```

Check without starting anything, with a concrete fix for every problem:

```bat
creo\start.cmd doctor
```

Options: `--creo "C:\Program Files\PTC\Creo 10.0.5.0"` (or set `CREO_HOME`), `--no-launch`, `--no-browser`, `--port N`, `--wait SECONDS`.

## What to ensure in Creo (checklist)

1. **Creo Parametric is installed and licensed** (a full Creo Parametric session, not a viewer or Express edition) and starts normally.
2. **The J-Link component is installed.** Look for `<Creo>\Common Files\text\java\pfcasync.jar`. If it is missing, run the Creo
   installer again and enable the API / J-Link ("Object TOOLKIT Java Free") components. J-Link in this form needs no extra licence.
   `creo\start.cmd doctor` tells you which of `pfcasync.jar`, `pfcasyncmt.dll`, `pro_comm_msg.exe` it can find.
3. **One Creo session only.** PTC documents that the asynchronous connection fails when several Creo sessions run. Close the others.
4. **Same Windows user, same elevation.** Do not start Creo "as Administrator" and the link normally (or the other way round).
5. **The name service must be reachable on this machine.** Creo's installer sets up its name service daemon (`nmsd`); allow
   `nmsd.exe` and `pro_comm_msg.exe` for local connections if a firewall or endpoint-protection tool asks. Nothing needs to be exposed
   to the network; everything stays on 127.0.0.1.
6. **64-bit JDK 11 or newer** (Creo is 64-bit). The launcher installs Temurin 17 with winget when none is found; or install one
   yourself and set `JAVA_HOME`.
7. **Creo must be idle for API calls**: no command in progress, no open dialog (press Esc). Creo reports these as `XToolkitBadContext`
   or similar. The launcher starts Creo from `creo\workdir`, whose `config.pro` sets `regen_failure_handling no_resolve_mode` so a
   failed regeneration does not open a blocking "Resolve" dialog.
8. **Have a model open** (part or assembly) in the active window. The link follows the active model.
9. **Make parameters easy to drive.** The viewer lists the model's user parameters and its dimensions (by symbol, `d12`, ...).
   The robust pattern is: define user parameters (Tools, Parameters), drive the dimensions from them with relations
   (`d5 = LENGTH`), and change the parameters from the viewer. You can also rename dimensions in Creo to meaningful names.
10. **Windchill / PDM:** work in an active workspace as usual; exporting STEP does not need the model to be saved.
11. **Group policy:** `start.cmd` runs PowerShell with `-ExecutionPolicy Bypass` for that one script. If AppLocker or similar blocks it,
    or winget is disabled, install Python 3.12 and a JDK 17 by hand, then run `.venv\Scripts\python tools\creolink.py start`.

## Troubleshooting

| Symptom | Likely cause and fix |
|---|---|
| `doctor` says Creo not found | Install location is not under `Program Files\PTC`: use `--creo` or `CREO_HOME` |
| `UnsatisfiedLinkError ... pfcasyncmt` | 32/64-bit mismatch (use a 64-bit JDK) or the DLL folder is not on `PATH`; `doctor` shows the folder that is used |
| `XToolkitNotFound` / "no Creo Parametric process found" | Creo is not running yet, `nmsd` is blocked, or the user/elevation differs |
| Connect fails with several sessions | Close all but one Creo session |
| `XToolkitBadContext` | Creo is busy: finish or cancel the active command and close dialogs |
| "no parameter or dimension named ..." | Names are case sensitive; use the names shown in the Creo tab |
| STEP export fails | Check the bridge log `.cad\creo\bridge.log`; try the export by hand in Creo with the same settings |
| Nothing updates for assemblies | The change detector uses mass properties, which an assembly may not provide: press **Sync now** |

Logs: `.cad\creo\bridge.log` (the Java bridge), the console window (sync events), `.cad\worker.log` (model builds).

## How it works

```
 viewer (Creo tab) ── POST /api/creo/command ──▶ .cad/creo/commands.jsonl ──▶ tools/creolink.py ──▶ creo/bridge/CreoBridge.java ──▶ Creo
 viewer ◀── GET /api/creo ◀── .cad/creo/state.json ◀──┘                          (JSON lines)          (J-Link async)
                                      model ◀── exchange.import_to_model ◀── STEP ◀── Model.Export
```

- `creo/bridge/CreoBridge.java` runs from source (`java -cp pfcasync.jar CreoBridge.java`), no build step. It reaches Creo only
  through reflection by method name, so a differing J-Link release shows up as a readable error for that one command.
- `tools/creolink.py` finds Creo and Java, sets `PRO_COMM_MSG_EXE`, `PATH` and `CLASSPATH`, starts Creo, runs the sync loop and
  writes `.cad/creo/state.json`.
- Change detection: volume and surface area of the active model. Press **Sync now** when it does not notice a change.

## What is verified

- The Java bridge, the sync loop, the server API and the viewer tab are tested end to end against a **stub of the J-Link classes**
  (`tests/creo/stubs`, 40+ tests). That proves the protocol, error handling and data flow.
- **Not verified:** the real J-Link calls (`AsyncConnection_Connect`, `STEP3DExportInstructions_Create`, `ListParams`, `SetDimValue`, ...).
  The names come from PTC's documentation and forum examples. The Windows launcher and Creo startup were also written without a
  Windows/Creo machine to run them on. Expect to fix small things on the first run; `doctor`, the per-command error messages and
  the bridge log are there to make that quick, and the places to adjust are `creo/bridge/CreoBridge.java` (Creo calls) and
  `creo/start.ps1` (installation).

References: PTC's guides on [setting up an asynchronous J-Link application](https://support.ptc.com/help/creo_toolkit/otk_java_plus/usascii/creo_toolkit/user_guide/Setting_up_an_Asynchronous_J_Link_Application.html)
and [connecting to a Creo process](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r11.0/usascii/creo_toolkit/user_guide/Connecting_to_a_Creo_Parametric_Creo_Process.html),
and the [AsyncConnection API](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r11.0/usascii/creo_toolkit/api/dita/c-pfcAsyncConnection-AsyncConnection.html).
