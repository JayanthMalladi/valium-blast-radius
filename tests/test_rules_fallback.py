"""Stub-safe selection: canary + unknown_loaders union."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector import patch as P
from selector.maps import Maps
from selector.rules import RuleEngine

REL = "sqlglot/helper.py"


def _patch_text():
    return """diff --git a/sqlglot/helper.py b/sqlglot/helper.py
--- a/sqlglot/helper.py
+++ b/sqlglot/helper.py
@@ -1,2 +1,3 @@
 x = 1
+y = 2
 z = 3
"""


def _engine(tmp_path: Path, extra: dict | None = None, line_coverage: str = "{}"):
    d = tmp_path / "maps"
    d.mkdir()
    (d / "line_coverage.json").write_text(line_coverage, encoding="utf-8")
    data = {
        "id_order.json": ["a", "b", "c", "d", "e", "f"],
        "module_importers.json": {REL: ["a", "b"]},
        "source_readers.json": {REL: ["c"]},
        "class_uses.json": {REL + "::X": ["d"]},
        "test_files.json": {
            "tests/test_optimizer.py": ["c", "d"],
            "tests/test_executor.py": ["e"],
        },
        "fixture_map.json": {},
    }
    data.update(extra or {})
    for name, obj in data.items():
        (d / name).write_text(json.dumps(obj), encoding="utf-8")
    m = Maps(str(d))
    m.load()
    id_by_node = {nid: i + 1 for i, nid in enumerate(m.id_order)}
    pristine = {REL: "x = 1\n"}
    return RuleEngine(m, id_by_node, pristine)


def test_stub_line_map_selects_canary(tmp_path):
    # Empty line map -> canary (optimizer+executor) fires.
    engine = _engine(tmp_path)
    sel = engine.select_for_files(P.parse_patch(_patch_text()))
    opt_exec = engine._opt_executor_numbers()
    assert sel == opt_exec, sel


def test_unknown_loaders_unioned_in(tmp_path):
    engine = _engine(tmp_path, {
        "unknown_loaders.json": {REL: ["e", "f"]},
    })
    sel = engine.select_for_files(P.parse_patch(_patch_text()))
    opt_exec = engine._opt_executor_numbers()
    assert sel == opt_exec | {5, 6}, sel


def test_absent_unknown_loaders_is_noop(tmp_path):
    engine = _engine(tmp_path)
    assert engine.maps.unknown_loader_ids(REL) == []


def test_module_ids_still_union_importers_and_readers():
    m = Maps()
    m._loaded = True
    m.module_importers = {REL: [1]}
    m.source_readers = {REL: [3]}
    m.line_index = {}
    m.class_uses = {}
    assert sorted(m.module_ids(REL)) == [1, 3]
