"""The workshop site: static, self-contained pages (one per model, plus an index) with flat views, dimensions, tap-to-measure and a cut list,
made from the published models, so a phone in the workshop needs nothing but a browser. No PNG, no external files."""
import json
import re

import pytest
from build123d import Box, Pos

import cadview
import share


@pytest.fixture
def model(project):
    """A base box with a lid on a hinge (z axis at its left edge) and a slider box: published like any model."""
    parts = [dict(name="base", shape=Box(100, 50, 20), joint=None, role="board", material="oak"),
             dict(name="lid", shape=Pos(100, 0, 0) * Box(100, 50, 20), joint="hinge", role="board", material="oak"),
             dict(name="car", shape=Pos(0, 0, 40) * Box(10, 10, 10), joint="slide", role="hardware", material="steel")]
    joints = [dict(name="hinge", label="Hinge", group="g", type="revolute", parent=None, origin=[50, 0, 0], axis=[0, 0, 1], min=0, max=90),
              dict(name="slide", label="Slide", group="g", type="prismatic", parent=None, origin=[0, 0, 0], axis=[1, 0, 0], min=0, max=100,
                   mimic={"of": "hinge", "table": [[0, 0], [90, 100]]})]
    cadview.publish_kinematic(parts, joints, {"open": {}, "folded": {"hinge": 90}}, "parts/demo.py", None,
                              [dict(id="c1", kind="fixed", label="Lid hinge", a="base", b="lid", parts=["base", "lid"], params=[], expr="hinge at x = 50")], name="demo")
    return share.load_model(project, "demo")


def bbox(parts, name):
    import numpy as np
    v = dict((n, vv) for n, vv, _ in parts)[name]
    return v.min(axis=0), v.max(axis=0)


def test_posing_follows_revolute_prismatic_and_mimic_joints(model):
    lo, hi = bbox(share.posed_parts(model, {}), "lid")
    assert (round(lo[0]), round(hi[0])) == (50, 150)                              # open: the lid lies beside the base
    lo, hi = bbox(share.posed_parts(model, {"hinge": 90}), "lid")
    assert (round(lo[0]), round(hi[0]), round(lo[1]), round(hi[1])) == (25, 75, 0, 100)            # turned up about the hinge at x = 50
    lo, hi = bbox(share.posed_parts(model, {"hinge": 90}), "car")
    assert round(lo[0]) == 95                                                      # the slide follows the hinge by its table: 100 mm at 90 deg


def test_a_scene_lists_the_parts_and_the_drawing_box_in_tenths_of_a_mm(model):
    s = share.scene(model, {"hinge": 90}, "front")
    assert [p["name"] for p in s["parts"]] == ["base", "lid", "car"]
    assert s["bbox"] == [-500, -100, 1050, 450]                                    # x -50..105, z -10..45 mm


def test_views_project_onto_the_right_axes(model):
    box = lambda v: [x / 10 for x in share.scene(model, {}, v)["bbox"]]
    assert box("front") == [-50, -10, 150, 45]                                     # length x height
    assert box("top") == [-50, -25, 150, 25]                                       # length x depth
    assert box("side") == [-25, -10, 25, 45]                                       # depth x height (seen from the right: y runs to the right)


def test_triangles_are_flat_rows_far_to_near_with_a_shade(model):
    s = share.scene(model, {}, "front")
    rows = s["tris"]
    assert len(rows) % 8 == 0 and len(rows) >= 8 * 12
    assert all(isinstance(v, int) for v in rows[:80])
    assert {rows[i] for i in range(0, len(rows), 8)} <= {0, 1, 2}                    # part indexes
    assert all(0 <= rows[i] % 16 <= 9 and rows[i] < 128 for i in range(7, len(rows), 8))   # shade (0..9) + 16 x the mask of feature edges to draw


def test_part_sizes_are_those_of_the_posed_part(model):
    s = share.scene(model, {"hinge": 90}, "front")
    lid = [p for p in s["parts"] if p["name"] == "lid"][0]
    assert lid["size"] == pytest.approx([50, 100, 20], abs=0.2)


def test_the_page_is_self_contained_and_carries_the_data(model, project):
    html = share.model_page(model, "demo")
    assert "<title>demo" in html and "Lid hinge" in html and "hinge at x = 50" in html
    assert "function pickPart" in html and "function formatMm" in html                  # the tested helpers are inlined
    assert not re.search(r"(src|href)=[\"']https?://", html) and "cdn." not in html and "<img" not in html
    data = json.loads(re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S).group(1))
    assert set(data["scenes"]) == {"open", "folded"} and set(data["scenes"]["open"]) == {"front", "side", "top", "iso"}
    assert [p["name"] for p in data["parts"]] == ["base", "lid", "car"] and data["parts"][0]["material"] == "oak"
    assert data["constraints"][0]["label"] == "Lid hinge"


def test_build_site_writes_an_index_and_a_page_per_model(model, project):
    out = project / "share"
    files = share.build_site(project, out)
    assert (out / "index.html").exists() and (out / "demo.html").exists() and len(files) == 2
    idx = (out / "index.html").read_text(encoding="utf-8")
    assert 'href="demo.html"' in idx and "demo" in idx
    assert not re.search(r"(src|href)=[\"']https?://", idx)


def test_build_site_can_be_limited_to_some_models(model, project):
    assert share.build_site(project, project / "s2", models=["nope"]) == [project / "s2" / "index.html"]


def test_the_data_stays_small_enough_for_a_phone(model):
    html = share.model_page(model, "demo")
    assert len(html) < 400_000
