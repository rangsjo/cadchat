"""Instructions every AI agent can follow, whatever the vendor: AGENTS.md (read by Copilot CLI, Codex, OpenCode and others), GEMINI.md and CLAUDE.md
point to it or carry the same rules."""
from conftest import REPO


def text(name):
    return (REPO / name).read_text(encoding="utf-8")


def test_agents_md_explains_the_project_the_rules_and_how_to_listen_and_reply():
    t = text("AGENTS.md")
    for needle in ("mm", "z is up", "test first", "PARAMS", "cadwatch.py --once", "cadreply", "./cadchat run", "joints.py", "cadchat share", "never send PNG"):
        assert needle.lower() in t.lower(), needle
    assert "bridge" in t.lower()                                  # in per-message mode the final answer is posted automatically


def test_other_agents_files_point_to_it():
    assert "AGENTS.md" in text("GEMINI.md")
    assert "AGENTS.md" in text("CLAUDE.md")
