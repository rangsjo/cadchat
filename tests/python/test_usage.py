"""Token usage of the assistant sessions that worked on this project, read from Claude Code transcripts (~/.claude/projects/*/*.jsonl)."""
import json
import os
import time

import pytest

import usage


def line(mid, ts, inp=10, out=5, cr=100, cc=20, model="claude-sonnet-5-5", kind="assistant", extra=None):
    d = {"type": kind, "timestamp": ts, "message": {"id": mid, "model": model, "usage": {"input_tokens": inp, "output_tokens": out, "cache_read_input_tokens": cr, "cache_creation_input_tokens": cc}}}
    d.update(extra or {})
    return json.dumps(d)


@pytest.fixture
def claude(tmp_path):
    root = tmp_path / "projects"
    (root / "-p-one").mkdir(parents=True)
    return root


def write(claude, name, lines, sub="-p-one"):
    f = claude / sub / name
    f.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return f


def today():
    return time.strftime("%Y-%m-%dT12:00:00Z", time.gmtime())


def test_sums_the_four_kinds_of_tokens_per_message_once(claude, tmp_path):
    proj = tmp_path / "proj"
    write(claude, "s1.jsonl", [f'{{"type":"user","text":"work on {proj}"}}', line("m1", today()), line("m1", today(), out=9), line("m2", today(), inp=1, out=2, cr=3, cc=4)])
    r = usage.collect(proj, claude)
    t = r["total"]
    assert (t["input"], t["output"], t["cache_read"], t["cache_creation"]) == (11, 11, 103, 24)         # m1 counted once (largest output), plus m2
    assert t["messages"] == 2 and r["sources"] == 1


def test_only_sessions_that_mention_the_project_are_counted(claude, tmp_path):
    proj = tmp_path / "proj"
    write(claude, "mine.jsonl", [f'{{"cwd":"{proj}"}}', line("m1", today())])
    write(claude, "other.jsonl", ['{"cwd":"/somewhere/else"}', line("m9", today())])
    assert usage.collect(proj, claude)["total"]["messages"] == 1


def test_days_models_and_sessions(claude, tmp_path):
    proj = tmp_path / "proj"
    write(claude, "a.jsonl", [f'{{"cwd":"{proj}"}}', line("m1", "2026-10-15T09:00:00Z", model="x-opus"), line("m2", "2026-10-16T09:00:00Z", model="x-sonnet", out=50)])
    r = usage.collect(proj, claude)
    assert [d["date"] for d in r["days"]] == ["2026-10-15", "2026-10-16"]
    assert r["days"][1]["output"] == 50
    assert set(r["models"]) == {"x-opus", "x-sonnet"} and r["models"]["x-sonnet"]["output"] == 50
    s = r["sessions"][0]
    assert s["id"] == "a" and s["messages"] == 2 and s["first"] == "2026-10-15T09:00:00Z" and s["last"] == "2026-10-16T09:00:00Z"


def test_today_and_the_cache_share(claude, tmp_path):
    proj = tmp_path / "proj"
    write(claude, "a.jsonl", [f'{{"cwd":"{proj}"}}', line("old", "2020-01-01T00:00:00Z", cr=1000), line("now", today(), inp=10, out=5, cr=90, cc=0)])
    r = usage.collect(proj, claude)
    assert r["today"]["messages"] == 1 and r["today"]["cache_read"] == 90
    assert r["cache_share"] == pytest.approx((1000 + 90) / (1000 + 90 + 10 + 20 + 0 + 20 + 0), abs=0.2)      # share of input-side tokens served from cache


def test_damaged_lines_and_missing_dirs_are_ignored(claude, tmp_path):
    proj = tmp_path / "proj"
    write(claude, "a.jsonl", [f'{{"cwd":"{proj}"}}', "{broken", line("m1", today()), '{"type":"assistant","message":{"id":"x"}}'])
    assert usage.collect(proj, claude)["total"]["messages"] == 1
    assert usage.collect(proj, tmp_path / "nothing")["total"]["messages"] == 0


def test_changed_files_are_read_again_and_unchanged_ones_come_from_the_cache(claude, tmp_path):
    proj = tmp_path / "proj"
    f = write(claude, "a.jsonl", [f'{{"cwd":"{proj}"}}', line("m1", today())])
    usage.collect(proj, claude)
    n = usage.STATS["parsed"]
    usage.collect(proj, claude)
    assert usage.STATS["parsed"] == n                                           # nothing changed: not parsed again
    with open(f, "a", encoding="utf-8") as fh:
        fh.write(line("m2", today()) + "\n")
    assert usage.collect(proj, claude)["total"]["messages"] == 2


def test_explicit_directories_are_used_when_given(claude, tmp_path):
    proj = tmp_path / "proj"
    write(claude, "a.jsonl", [f'{{"cwd":"{proj}"}}', line("m1", today())])
    r = usage.collect(proj, None, dirs=[str(claude / "-p-one")])
    assert r["total"]["messages"] == 1
