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
import signal
import sys
import shutil
import subprocess
import time
from pathlib import Path

import providers
import settings

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
    """The interactive agent (the chosen provider, or CADCHAT_ASSISTANT_CMD) with the prompt that makes it listen."""
    s = settings.load()
    env = os.environ.get("CADCHAT_ASSISTANT_CMD")
    cmd = shlex.split(env) if env else providers.interactive_argv(s["provider"], s["assistant_cmd"])
    prompt = (f"Start a cadchat session for the project at {project}: follow AGENTS.md (the cad-viewer skill in .claude/skills for Claude Code): "
              f"start the viewer if it is not running, then listen for popup messages with CADCHAT_ROOT={project} (Monitor on tools/cadwatch.py where "
              f"you have it, otherwise run `.venv/bin/python tools/cadwatch.py --once` in a loop) and answer them with tools/cadreply.py.")
    return cmd + [prompt]


def start_argv(project):
    """What "Start assistant" runs: the interactive agent, or in message mode the bridge that runs the agent once per chat message."""
    if settings.load()["assistant_mode"] == "message" and not os.environ.get("CADCHAT_ASSISTANT_CMD"):
        return [sys.executable, str(APP / "tools" / "cadchat.py"), "--project", str(project), "bridge"]
    return assistant_argv(project)


def terminal_argv(cmd):
    given = os.environ.get("CADCHAT_TERMINAL") or settings.load()["terminal"]
    if given:
        return shlex.split(given) + list(cmd)
    for name, flag in TERMINALS:
        if shutil.which(name):
            return [name, *flag, *cmd]
    return list(cmd)


WRAP = 'echo $$ > "$0"; exec "$@"'          # the agent replaces the shell, so the recorded pid is the agent's own


def pidfile(project):
    return Path(project) / ".cad" / "assistant.pid"


def _is_assistant(pid):
    """True if the process is an assistant started by us (its command line carries our start prompt); never trust a bare pid file."""
    try:
        text = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
    except OSError:
        return False
    return "cadchat session" in text or ("cadchat.py" in text and "bridge" in text.split("\0"))


def _stop_watch(project):
    """The message watch (tools/cadwatch.py) the assistant started may outlive it and keep reporting 'listening': end it too."""
    try:
        pid = int(json.loads((Path(project) / ".cad" / "assistant.json").read_text(encoding="utf-8")).get("pid"))
        if "cadwatch" in Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace"):
            os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError, TypeError):
        pass


def stop_assistant(project, wait=3.0):
    """End the assistant session the viewer started ("stopped"); "not running" if there is none, or the pid file is stale."""
    f = pidfile(project)
    try:
        pid = int(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "not running"
    if not _is_assistant(pid):
        f.unlink(missing_ok=True)
        return "not running"
    os.kill(pid, signal.SIGTERM)
    _stop_watch(project)
    end = time.time() + wait
    while time.time() < end and _is_assistant(pid):
        time.sleep(0.05)
    if _is_assistant(pid):
        os.kill(pid, signal.SIGKILL)
    f.unlink(missing_ok=True)
    return "stopped"


def restart_assistant(project):
    """A fresh session with an empty context in place of the one the viewer started ("restarted"); "none" if it started none."""
    if stop_assistant(project) != "stopped":
        return "none"
    start_assistant(project, min_gap=0)
    return "restarted"


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
    pidfile(project).unlink(missing_ok=True)
    subprocess.Popen(terminal_argv(["sh", "-c", WRAP, str(pidfile(project)), *start_argv(project)]), cwd=APP, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
    return "started"
