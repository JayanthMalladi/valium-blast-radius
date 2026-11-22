"""Stub-safe selection: canary + unknown_loaders union."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector import patch as P
from selector.maps import Maps
from selector.rules import RuleEngine

REL = "sqlglot/helper.py"
PRISTINE = "x = 1\ny = 2\nz = 3\n"


def _patch_text():
    # replaces pristine line 2; the hunk's old-side context matches PRISTINE
    return """diff --git a/sqlglot/helper.py b/sqlglot/helper.py
--- a/sqlglot/helper.py
+++ b/sqlglot/helper.py
@@ -2,1 +2,1 @@
-y = 2
+z = 2
"""


def _engine(tmp_path: Path, extra: dict | None = None, line_coverage: str = "{}"):
    d = tmp_path / "maps"
    d.mkdir()
    data = {
        "id_order.json": ["a", "b", "c", "d", "e", "f"],
        "source_readers.json": {REL: ["c"]},
        "test_files.json": {
            "tests/test_optimizer.py": ["c", "d"],
            "tests/test_executor.py": ["e"],
        },
        "fixture_map.json": {},
        "line_coverage.json": json.loads(line_coverage),
    }
    data.update(extra or {})
    for name, obj in data.items():
        (d / name).write_text(json.dumps(obj), encoding="utf-8")
    m = Maps(str(d))
    m.load()
    id_by_node = {nid: i + 1 for i, nid in enumerate(m.id_order)}
    pristine = {REL: PRISTINE}
    return RuleEngine(m, id_by_node, pristine)


def test_stub_line_map_selects_canary(tmp_path):
    # Empty line map -> canary (optimizer+executor) fires.
    engine = _engine(tmp_path)
    engine._canary = True   # BR_CANARY=1
    sel = engine.select_for_files(P.parse_patch(_patch_text()))
    opt_exec = engine._opt_executor_numbers()
    assert sel == opt_exec, sel


def test_unknown_loaders_unioned_in(tmp_path):
    engine = _engine(tmp_path, {
        "unknown_loaders.json": {REL: ["e", "f"]},
    })
    engine._canary = True   # BR_CANARY=1
    sel = engine.select_for_files(P.parse_patch(_patch_text()))
    opt_exec = engine._opt_executor_numbers()
    assert sel == opt_exec | {5, 6}, sel


def test_absent_unknown_loaders_is_noop(tmp_path):
    engine = _engine(tmp_path)
    assert engine.maps.unknown_loader_ids(REL) == []


def test_family_ids_empty_without_siblings(tmp_path):
    engine = _engine(tmp_path)
    assert engine.maps.family_ids(REL) == []
