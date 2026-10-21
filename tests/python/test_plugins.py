"""Optional features (plugins) that share the one code base: switched on in Settings, or by themselves when their helper process is running."""
import json
import time

import pytest

import plugins
import settings


def test_the_known_plugins_have_names_for_the_settings_dialog():
    assert plugins.KNOWN["creo"]
    assert [p["id"] for p in plugins.available()] == list(plugins.KNOWN)


def test_nothing_is_enabled_by_default(project):
    assert plugins.enabled(project) == []


def test_a_plugin_is_enabled_in_settings(project):
    settings.save({"plugins": "creo"})
    assert plugins.enabled(project) == ["creo"]
    settings.save({"plugins": ""})
    assert plugins.enabled(project) == []


def test_the_creo_link_switches_itself_on_while_it_runs(project):
    d = project / ".cad" / "creo"
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({"updated": time.time(), "connected": True}), encoding="utf-8")
    assert plugins.enabled(project) == ["creo"]
    (d / "state.json").write_text(json.dumps({"updated": time.time() - 3600}), encoding="utf-8")        # a stale state from last week does not count
    assert plugins.enabled(project) == []


def test_settings_only_accept_known_plugins():
    assert settings.save({"plugins": "creo"})["plugins"] == "creo"
    with pytest.raises(ValueError):
        settings.save({"plugins": "creo, teleporter"})
    assert settings.load()["plugins"] == "creo"
