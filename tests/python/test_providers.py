"""AI providers: which agent commands cadchat knows (Claude Code, GitHub Copilot CLI, Codex, Gemini, any other), how to sign in to each,
and how to run one message through them."""
import os
import stat

import pytest

import providers


def test_the_catalog_knows_the_common_agents_and_a_custom_one():
    ids = [p["id"] for p in providers.catalog()]
    assert ids[:4] == ["claude", "copilot", "codex", "gemini"] and "custom" in ids
    for p in providers.catalog():
        assert p["name"] and p["subscription"] and p["login"] and p["install"] and isinstance(p["login"], list)
        assert p["interactive"] and "{prompt}" in p["oneshot"]


def test_claude_and_copilot_are_set_up_for_the_subscription_login():
    by = {p["id"]: p for p in providers.catalog()}
    assert by["claude"]["binary"] == "claude" and "Pro" in by["claude"]["subscription"] and any("/login" in s or "login" in s for s in by["claude"]["login"])
    assert by["copilot"]["binary"] == "copilot" and "Copilot" in by["copilot"]["subscription"]
    assert any("npm install -g @github/copilot" in by["copilot"]["install"] for _ in [0])
    assert by["claude"]["listens"] is True and by["copilot"]["listens"] is False           # only Claude Code keeps a live watch: others answer message by message


def test_one_message_becomes_the_argument_list_of_the_agent():
    argv = providers.oneshot_argv("copilot", "make the legs longer")
    assert argv[0] == "copilot" and "make the legs longer" in argv and "{prompt}" not in " ".join(argv)
    assert "-p" in argv and "-s" in argv                                                  # prompt mode, clean output
    claude = providers.oneshot_argv("claude", "hi")
    assert claude[:3] == ["claude", "-p", "hi"] and "--allowedTools" in claude
    assert claude.index("hi") < claude.index("--allowedTools")                            # a variadic flag must not swallow the prompt


def test_a_custom_command_gets_the_prompt_appended_or_substituted():
    assert providers.oneshot_argv("custom", "x", custom="myagent --fast") == ["myagent", "--fast", "x"]
    assert providers.oneshot_argv("custom", "x", custom="myagent --prompt {prompt} --yes") == ["myagent", "--prompt", "x", "--yes"]
    with pytest.raises(ValueError):
        providers.oneshot_argv("custom", "x", custom="")


def test_interactive_command_for_a_session():
    assert providers.interactive_argv("claude") == ["claude"]
    assert providers.interactive_argv("custom", custom="my agent --x") == ["my", "agent", "--x"]
    with pytest.raises(KeyError):
        providers.interactive_argv("nope")


def fake(tmp_path, name, body, code=0):
    f = tmp_path / name
    f.write_text(f"#!/bin/sh\n{body}\nexit {code}\n", encoding="utf-8")
    f.chmod(f.stat().st_mode | stat.S_IXUSR)
    return f


def test_detection_runs_the_version_command_because_a_stub_on_the_path_is_not_an_install(tmp_path, monkeypatch):
    fake(tmp_path, "claude", 'echo "claude 9.9"')
    fake(tmp_path, "copilot", 'echo "GitHub Copilot CLI was not found. Run copilot in a terminal to install it"', code=1)         # like the real bootstrap stub
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}/usr/bin:/bin")
    c = providers.detect("claude")
    assert c["installed"] is True and "9.9" in c["version"] and c["path"].endswith("claude")
    p = providers.detect("copilot")
    assert p["installed"] is False and p["path"].endswith("copilot")
    assert providers.detect("codex")["installed"] is False and providers.detect("codex")["path"] is None


def test_detection_survives_a_command_that_hangs(tmp_path, monkeypatch):
    fake(tmp_path, "gemini", "sleep 30")
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}/usr/bin:/bin")
    r = providers.detect("gemini", timeout=0.5)
    assert r["installed"] is False and "time" in r["version"].lower()
