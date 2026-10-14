"""Import/export for exchanging parts with other CAD systems (STEP assemblies keep names and hierarchy)."""
import json
import struct

import pytest
from build123d import Box, Color, Cylinder, Pos, import_step

import exchange


def shapes():
    return [("base_plate", Box(10, 20, 30)), ("pin", Pos(20, 0, 0) * Cylinder(5, 40)), ("cube", Pos(0, 50, 0) * Box(5, 5, 5))]


def test_step_assembly_roundtrip_keeps_names_volumes_and_positions(tmp_path):
    f = tmp_path / "asm.step"
    exchange.export_step_assembly(shapes(), f, name="demo")
    parts = exchange.import_parts(f)
    assert [n for n, _ in parts] == ["base_plate", "pin", "cube"]
    assert [round(s.volume) for _, s in parts] == [6000, 3142, 125]
    cube = dict(parts)["cube"].bounding_box()
    assert (cube.min.Y, cube.max.Y) == (pytest.approx(47.5), pytest.approx(52.5))


def test_step_assembly_has_one_product_per_part_so_other_cad_shows_a_tree(tmp_path):
    f = tmp_path / "asm.step"
    exchange.export_step_assembly(shapes(), f, name="demo")
    text = f.read_text(encoding="utf-8")
    assert text.count("PRODUCT(") == 4 and "demo" in text and "base_plate" in text


def test_export_does_not_rename_the_callers_shapes(tmp_path):
    s = shapes()
    exchange.export_step_assembly(s, tmp_path / "a.step", name="x")
    assert all(shape.label == "" for _, shape in s)


def test_names_are_made_unique_on_import(tmp_path):
    f = tmp_path / "dup.step"
    exchange.export_step_assembly([("leg", Box(1, 1, 1)), ("leg", Pos(5, 0, 0) * Box(1, 1, 1))], f, name="d")
    assert [n for n, _ in exchange.import_parts(f)] == ["leg", "leg_2"]


def test_nested_assemblies_are_flattened_with_dotted_names(tmp_path):
    from build123d import Compound
    a = Box(1, 1, 1); a.label = "a"
    b = Pos(3, 0, 0) * Box(1, 1, 1); b.label = "b"
    asm = Compound(label="top", children=[Compound(label="sub", children=[a, b])])
    from build123d import export_step
    f = tmp_path / "n.step"
    export_step(asm, f)
    assert [n for n, _ in exchange.import_parts(f)] == ["sub.a", "sub.b"]


def test_stl_import_gives_one_part_named_after_the_file(tmp_path):
    from build123d import export_stl
    export_stl(Box(10, 20, 30), tmp_path / "bracket.stl")
    (name, shape), = exchange.import_parts(tmp_path / "bracket.stl")
    assert name == "bracket" and tuple(round(v) for v in shape.bounding_box().size) == (10, 20, 30)


def test_unknown_extension_is_rejected(tmp_path):
    (tmp_path / "x.dwg").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        exchange.import_parts(tmp_path / "x.dwg")


def test_import_to_model_publishes_a_static_model(project, tmp_path):
    f = tmp_path / "asm.step"
    exchange.export_step_assembly(shapes(), f, name="demo")
    exchange.import_to_model(f, "creo_part")
    m = json.loads((project / ".cad" / "models" / "creo_part" / "model.json").read_text(encoding="utf-8"))
    assert [p["name"] for p in m["parts"]] == ["base_plate", "pin", "cube"] and m["joints"] == []
    assert m["parts"][0]["volume"] == pytest.approx(6000, abs=1)


def test_import_to_model_rejects_unsafe_names(project, tmp_path):
    f = tmp_path / "a.step"
    exchange.export_step_assembly(shapes(), f, name="demo")
    with pytest.raises(ValueError):
        exchange.import_to_model(f, "../evil")


def test_export_3mf_writes_a_file(tmp_path):
    exchange.export_3mf(shapes(), tmp_path / "p.3mf")
    assert (tmp_path / "p.3mf").stat().st_size > 1000


def test_export_stl_parts_writes_one_file_per_part(tmp_path):
    files = exchange.export_stl_parts(shapes(), tmp_path)
    assert sorted(p.name for p in files) == ["base_plate.stl", "cube.stl", "pin.stl"]


def test_model_stl_from_published_mesh_has_the_right_triangle_count(project, tmp_path):
    import cadview
    cadview.publish_kinematic([dict(name="b", shape=Box(2, 2, 2), joint=None)], [], {"default": {}}, "parts/x.py")
    out = exchange.model_to_stl("x", tmp_path / "x.stl")
    data = out.read_bytes()
    assert struct.unpack("<I", data[80:84])[0] == 12 and len(data) == 84 + 50 * 12
