# Connecting an AI assistant

cadchat does not contain an AI. The chat in the viewer talks to an **agent**: a command line tool that can read files, edit them and run commands.
You pick one in the first-start wizard (also **Help ▸ Set up the AI assistant**, or **Settings**). Which one you can use depends on the subscription you already have.

| Agent | Command | Pays with | Per-message mode | Live session |
|---|---|---|---|---|
| Claude Code | `claude` | Claude Pro, Max, Team or Enterprise, or an Anthropic API key | yes (`claude -p`) | yes, with its live watch tool |
| GitHub Copilot CLI | `copilot` | any GitHub Copilot plan (Free, Pro, Pro+, Business, Enterprise) | yes (`copilot -p`) | yes, via `cadwatch --once` |
| OpenAI Codex CLI | `codex` | ChatGPT Plus, Pro, Team, Edu, Enterprise, or an OpenAI API key | yes (`codex exec`) | yes, via `cadwatch --once` |
| Gemini CLI | `gemini` | Google account (free tier), Gemini Code Assist, or a Gemini API key | yes (`gemini -p`) | yes, via `cadwatch --once` |
| anything else | your command | whatever it needs | yes | yes |

"Anything else" is any agent that can follow `AGENTS.md`, edit files and run shell commands: aider, OpenCode, Cursor CLI, a script around an API.
Chat-only tools (a web chat, an API call without file access) cannot change the models and do not fit.

## Two ways to answer

- **Once per message** (`assistant_mode: message`, runs `cadchat bridge`): every chat message starts the agent's non-interactive mode once, with the message, the selected part,
  the pose and the screenshot path in the prompt. The agent's final text becomes the chat reply. It works with every agent, needs no live watch, and **costs the same per message
  however long the project is**: nothing from earlier messages is resent. It is the cheapest option.
- **Live session** (`assistant_mode: session`): an interactive agent runs in a terminal, listens to the chat and remembers the conversation. Better for long, exploratory work; its
  context grows, so use **Clear chat** (it archives the conversation and starts a fresh session) when an old problem is solved.

The **Start assistant** button, the launcher icon's "Start assistant listening" and **Assistant ▸ Start listening** start whichever mode you chose.

## Claude (subscription)

1. Install Claude Code ([docs](https://docs.claude.com/en/docs/claude-code)).
2. Run `claude` once and choose the Claude account (subscription) login, or an API key.
3. In cadchat choose **Claude Code**. A subscription works for interactive use and for `claude -p` on the same machine. On a server without a browser, create a long-lived
   token with `claude setup-token` and export it as `CLAUDE_CODE_OAUTH_TOKEN`; with an API key export `ANTHROPIC_API_KEY` (billed per token, not by the subscription).

## GitHub Copilot (subscription)

1. You need an active GitHub Copilot plan. If it comes from an organisation, its owner must allow the Copilot CLI.
2. Install the CLI: `npm install -g @github/copilot` (Node.js 22 or newer), or follow [GitHub's install guide](https://docs.github.com/en/copilot/how-tos/copilot-cli/install-copilot-cli).
3. Run `copilot` once and type `/login`; finish the sign-in in the browser with your GitHub account. For unattended use set `COPILOT_GITHUB_TOKEN` (a fine-grained token with the Copilot Requests permission).
4. In cadchat choose **GitHub Copilot CLI**, mode **once per message**. cadchat runs
   `copilot -p "<message>" -s --no-ask-user --allow-tool=write --allow-tool='shell(.venv/bin/python:*)' ...`
   ([programmatic use](https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically)): file writes and a few commands are allowed, nothing else.
   If the agent needs more, change the command under **Another agent** (see below).

A stub named `copilot` can exist on the path without the CLI being installed (Ubuntu ships one). The wizard runs `copilot --version`, so it reports "not installed" until the real CLI is there.

## Codex and Gemini

- **Codex CLI** (`npm install -g @openai/codex`): `codex login`, then "Sign in with ChatGPT" for a plan, or an API key. Per message cadchat runs `codex exec --full-auto "<message>"`.
- **Gemini CLI** (`npm install -g @google/gemini-cli`): run `gemini` and "Login with Google", or set `GEMINI_API_KEY`. Per message cadchat runs `gemini -p "<message>" --yolo`.

Flags change between versions: if a run fails, check `<tool> --help`, then put the working command under **Another agent**.

## Another agent

Choose **Another agent** and enter the command. `{prompt}` is replaced by the message; without it the message is appended as the last argument:

```
aider --yes --message {prompt}
opencode run {prompt}
```

The command runs in the cadchat folder, so it finds `AGENTS.md` (the rules for agents: units, test first, how to rebuild and check models). It must print its final answer to standard output; that text is the reply.

## Safety and cost

- The agent can edit files and run commands in the cadchat folder and the project: that is its job here, so run it only on projects you trust, and prefer an agent with its own permission prompts or sandbox if you are unsure.
  Messages come from your own viewer (it only listens on 127.0.0.1 and checks a token).
- Screenshots are saved as files and only their path is sent; a text-only agent just ignores them.
- Subscription plans have usage limits; the token badge in the viewer (View ▸ Token usage) shows what Claude Code sessions used. Per-message mode keeps each message small.
- Settings live in `~/.config/cadchat/settings.json`; environment variables `CADCHAT_ASSISTANT_CMD` and `CADCHAT_TERMINAL` override the command and the terminal.

## For agent authors

Anything that can run these two commands can listen in a live session: `python tools/cadwatch.py --once` (waits for the next message, prints it as JSON, exits 0; exit 3 = nothing came) and
`python tools/cadreply.py "text"` (`--status` for progress lines). See `AGENTS.md`.
