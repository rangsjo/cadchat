"""AI providers: the agent command line tools cadchat can talk to, how to sign in to each, and how to run one message through them.

Two ways to use an agent:
  session  an interactive agent (Claude Code) is started in a terminal, follows AGENTS.md / the cad-viewer skill and keeps a live message watch;
  message  `cadchat bridge` runs the agent's non-interactive mode once per chat message ("claude -p", "copilot -p", "codex exec", "gemini -p"):
           works with every agent that can edit files and run commands, and the context never grows (nothing is resent from earlier messages).
Flags below follow each vendor's documentation at the time of writing; `<command> --help` is the authority and a custom command can replace any of them."""
import shlex
import shutil
import subprocess

PROMPT = "{prompt}"

_CATALOG = [
    dict(id="claude", name="Claude Code", binary="claude", listens=True,
         subscription="Claude Pro, Max, Team or Enterprise subscription, or an Anthropic API key (pay per token)",
         install="Install Claude Code (https://docs.claude.com/en/docs/claude-code), e.g. the native installer or npm install -g @anthropic-ai/claude-code",
         login=["Run: claude (it asks you to log in; /login does it later)", "Choose 'Claude account' (subscription) and finish the sign-in in the browser, or choose the API key option",
                "In a script or on a server you can set ANTHROPIC_API_KEY, or CLAUDE_CODE_OAUTH_TOKEN for a subscription (claude setup-token)"],
         interactive=["claude"],
         oneshot=["claude", "-p", PROMPT, "--permission-mode", "acceptEdits", "--allowedTools", "Bash", "Edit", "Write", "Read", "Glob", "Grep"],
         agent_file="CLAUDE.md"),
    dict(id="copilot", name="GitHub Copilot CLI", binary="copilot", listens=False,
         subscription="Any GitHub Copilot plan (Free, Pro, Pro+, Business, Enterprise); an organisation can switch the CLI off",
         install="npm install -g @github/copilot (needs Node.js 22 or newer), or see https://docs.github.com/en/copilot/how-tos/copilot-cli/install-copilot-cli",
         login=["Run: copilot", "Type /login and follow the browser sign-in with your GitHub account",
                "For scripts set COPILOT_GITHUB_TOKEN (or GH_TOKEN) to a fine-grained token with the Copilot Requests permission"],
         interactive=["copilot"],
         oneshot=["copilot", "-p", PROMPT, "-s", "--no-ask-user", "--allow-tool=write", "--allow-tool=shell(.venv/bin/python:*)",
                  "--allow-tool=shell(./cadchat:*)", "--allow-tool=shell(git:*)", "--allow-tool=shell(node:*)"],
         agent_file="AGENTS.md"),
    dict(id="codex", name="OpenAI Codex CLI", binary="codex", listens=False,
         subscription="ChatGPT Plus, Pro, Team, Edu or Enterprise plan, or an OpenAI API key (pay per token)",
         install="npm install -g @openai/codex, or brew install codex",
         login=["Run: codex login", "Choose 'Sign in with ChatGPT' (plan) or paste an API key", "On a headless machine use the device code option, or set CODEX_API_KEY"],
         interactive=["codex"], oneshot=["codex", "exec", "--full-auto", PROMPT], agent_file="AGENTS.md"),
    dict(id="gemini", name="Gemini CLI", binary="gemini", listens=False,
         subscription="A Google account (free tier with daily limits), Gemini Code Assist, or a Gemini API key",
         install="npm install -g @google/gemini-cli",
         login=["Run: gemini", "Choose 'Login with Google' and finish in the browser, or set GEMINI_API_KEY"],
         interactive=["gemini"], oneshot=["gemini", "-p", PROMPT, "--yolo"], agent_file="GEMINI.md"),
    dict(id="custom", name="Another agent (your own command)", binary=None, listens=False,
         subscription="Whatever that tool needs: it only has to read the project instructions, edit files and run commands",
         install="Any command line agent that can edit files and run shell commands (aider, OpenCode, Cursor CLI, a script around an API, ...)",
         login=["Sign in the way that tool describes", "Enter the command below; {prompt} is replaced by the message, without it the message is appended as the last argument"],
         interactive=["true"], oneshot=[PROMPT], agent_file="AGENTS.md"),
]


def catalog():
    return [dict(p) for p in _CATALOG]


def get(pid):
    for p in _CATALOG:
        if p["id"] == pid:
            return dict(p)
    raise KeyError(pid)


def oneshot_argv(pid, prompt, custom=""):
    """The command that runs the agent once for one message."""
    p = get(pid)
    if pid == "custom":
        words = shlex.split(custom or "")
        if not words:
            raise ValueError("a custom agent needs a command")
        return [w.replace(PROMPT, prompt) for w in words] if any(PROMPT in w for w in words) else words + [prompt]
    return [a.replace(PROMPT, prompt) for a in p["oneshot"]]


def interactive_argv(pid, custom=""):
    """The command that starts the agent as an interactive session."""
    p = get(pid)
    if pid == "custom":
        words = shlex.split(custom or "")
        if not words:
            raise ValueError("a custom agent needs a command")
        return words
    return list(p["interactive"])


def detect(pid, timeout=8.0):
    """{"installed", "path", "version"}: the binary must be on PATH and answer --version with success (a stub that only explains how to
    install it, such as the Copilot bootstrap, counts as not installed)."""
    binary = get(pid).get("binary")
    path = shutil.which(binary) if binary else None
    if not path:
        return {"installed": False, "path": None, "version": ""}
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
        out = (r.stdout or r.stderr).strip().splitlines()
        return {"installed": r.returncode == 0, "path": path, "version": out[0][:120] if out else ""}
    except subprocess.TimeoutExpired:
        return {"installed": False, "path": path, "version": "timed out after %gs" % timeout}
    except OSError as e:
        return {"installed": False, "path": path, "version": str(e)[:120]}
