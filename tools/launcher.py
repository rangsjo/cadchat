"""Ubuntu/Linux desktop launcher for cadchat and the one-click start of the listening assistant.

install() writes ~/.local/share/applications/cadchat.desktop: an app icon "CAD chat" that starts the viewer for the last used project
and opens it in the browser, with a right-click action "Start assistant listening". start_assistant() (also behind the button in the
viewer) opens a terminal with Claude Code in this folder and a prompt that makes it follow the cad-viewer skill: start the viewer if needed,
arm the message watch and answer the popup messages. CADCHAT_ASSISTANT_CMD (default: claude) and CADCHAT_TERMINAL (default: the first of
x-terminal-emulator, gnome-terminal, konsole, xterm) change what is started and where.
"""
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
TERMINALS = [("x-terminal-emulator", ["-e"]), ("gnome-terminal", ["--"]), ("konsole", ["-e"]), ("xterm", ["-e"])]


def _exec(path, *args):
    p = str(path)
    first = f'"{p}"' if " " in p else p
    return " ".join([first, *args])


def desktop_entry(app_dir=APP):
    app_dir = Path(app_dir)
    cadchat = app_dir / "cadchat"
    return "\n".join([
        "[Desktop Entry]", "Type=Application", "Name=CAD chat", "Comment=Code-CAD workbench with a chat to the assistant",
        f"Exec={_exec(cadchat, 'app')}", f"Icon={app_dir / 'assets' / 'cadchat.svg'}", "Terminal=false",
        "Categories=Graphics;Engineering;", "StartupWMClass=cadchat", "Actions=Assistant;Stop;", "",
        "[Desktop Action Assistant]", "Name=Start assistant listening", f"Exec={_exec(cadchat, 'assistant', '--terminal')}", "",
        "[Desktop Action Stop]", "Name=Stop the viewer", f"Exec={_exec(cadchat, 'stop')}", ""])


def applications_dir():
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "applications"


def install(app_dir=APP, apps_dir=None):
    apps = Path(apps_dir) if apps_dir else applications_dir()
    apps.mkdir(parents=True, exist_ok=True)
    f = apps / "cadchat.desktop"
    f.write_text(desktop_entry(app_dir), encoding="utf-8")
    f.chmod(0o755)
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(apps)], capture_output=True)
    return f


def uninstall(apps_dir=None):
    f = (Path(apps_dir) if apps_dir else applications_dir()) / "cadchat.desktop"
    if not f.exists():
        return False
    f.unlink()
    return True


def assistant_argv(project):
    cmd = shlex.split(os.environ.get("CADCHAT_ASSISTANT_CMD") or "claude")
    prompt = (f"Start a cadchat session for the project at {project}: follow the cad-viewer skill (start the viewer if it is not running, "
              f"arm the message watch with CADCHAT_ROOT={project}, then wait for popup messages and answer them).")
    return cmd + [prompt]


def terminal_argv(cmd):
    given = os.environ.get("CADCHAT_TERMINAL")
    if given:
        return shlex.split(given) + list(cmd)
    for name, flag in TERMINALS:
        if shutil.which(name):
            return [name, *flag, *cmd]
    return list(cmd)


def start_assistant(project, min_gap=20):
    """Open the assistant in a terminal. Returns "started", or "already starting" if it was started less than min_gap seconds ago."""
    stamp = Path(project) / ".cad" / "assistant_start.json"
    now = time.time()
    try:
        if now - json.loads(stamp.read_text(encoding="utf-8")).get("at", 0) < min_gap:
            return "already starting"
    except (OSError, ValueError):
        pass
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(json.dumps({"at": now}), encoding="utf-8")
    kw = {"start_new_session": True} if os.name != "nt" else {}
    subprocess.Popen(terminal_argv(assistant_argv(project)), cwd=APP, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    return "started"
