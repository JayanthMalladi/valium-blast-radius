"""Safe fallbacks (fix 3): unparseable patched text and unknown paths
under sqlglot/ select the FULL SUITE. module_importers.json is a first-loader
artifact and is never a selection source.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector import patch as P
from selector.maps import Maps
from selector.rules import RuleEngine

REL = "sqlglot/helper.py"


def _maps_dir(tmp_path: Path, line_coverage: dict | None = None) -> Path:
    d = tmp_path / "maps"
    d.mkdir()
    data = {
        "id_order.json": ["a", "b", "c", "d", "e", "f", "g", "h"],
        "module_importers.json": {REL: ["a", "b"]},
        "source_readers.json": {REL: ["c"]},
        "test_files.json": {
            "tests/test_optimizer.py": ["c", "d"],
            "tests/test_executor.py": ["e"],
        },
        "fixture_map.json": {},
        "line_coverage.json": line_coverage or {},
        "unknown_loaders.json": {},
    }
    for name, obj in data.items():
        (d / name).write_text(json.dumps(obj), encoding="utf-8")
    return d


def _engine(tmp_path: Path, line_coverage: dict | None = None,
            pristine: dict | None = None) -> RuleEngine:
    m = Maps(str(_maps_dir(tmp_path, line_coverage)))
    m.load()
    id_by_node = {nid: i + 1 for i, nid in enumerate(m.id_order)}
    return RuleEngine(m, id_by_node, pristine if pristine is not None else {REL: "x = 1\n"})


def _full(engine: RuleEngine) -> set:
    return set(engine.id_by_node.values())


def test_import_break_selects_full_suite(tmp_path):
    patch = f"""diff --git a/{REL} b/{REL}
--- a/{REL}
+++ b/{REL}
@@ -1,2 +1,2 @@
 x = 1
-y = 2
+def f(:
     pass
"""
    engine = _engine(tmp_path, pristine={REL: "x = 1\ny = 2\n"})
    assert engine.select_for_files(P.parse_patch(patch)) == _full(engine)


def test_comment_only_uses_readers_not_full_suite(tmp_path):
    patch = f"""diff --git a/{REL} b/{REL}
--- a/{REL}
+++ b/{REL}
@@ -1,2 +1,3 @@
 x = 1
+# a comment
 y = 2
"""
    engine = _engine(tmp_path, pristine={REL: "x = 1\ny = 2\n"})
    sel = engine.select_for_files(P.parse_patch(patch))
    assert sel == {3}                   # source reader only


def test_non_py_outside_tests_and_sqlglot_selects_nothing(tmp_path):
    patch = """diff --git a/docs/notes.md b/docs/notes.md
--- a/docs/notes.md
+++ b/docs/notes.md
@@ -1,1 +1,2 @@
 hello
+world
"""
    engine = _engine(tmp_path)
    assert engine.select_for_files(P.parse_patch(patch)) == set()


def test_unparseable_patched_text_selects_full_suite(tmp_path):
    # The patch applies cleanly but the new text is not valid Python.
    patch = f"""diff --git a/{REL} b/{REL}
--- a/{REL}
+++ b/{REL}
@@ -1,1 +1,2 @@
 x = 1
+1+2=not valid python
"""
    engine = _engine(tmp_path)
    assert engine.select_for_files(P.parse_patch(patch)) == _full(engine)


def test_unknown_path_under_sqlglot_selects_full_suite(tmp_path):
    patch = """diff --git a/sqlglot/not_in_tree.py b/sqlglot/not_in_tree.py
--- a/sqlglot/not_in_tree.py
+++ b/sqlglot/not_in_tree.py
@@ -1,1 +1,2 @@
 x = 1
+y = 2
"""
    engine = _engine(tmp_path)          # pristine has no such file
    assert engine.select_for_files(P.parse_patch(patch)) == _full(engine)


def test_module_importers_does_not_drive_selection(tmp_path):
    # module_importers should not be used as a selection source for fallbacks.
    patch = f"""diff --git a/{REL} b/{REL}
--- a/{REL}
+++ b/{REL}
@@ -1,2 +1,2 @@
 x = 1
-y = 2
+def f(:
     pass
"""
    engine = _engine(tmp_path, pristine={REL: "x = 1\ny = 2\n"})
    sel = engine.select_for_files(P.parse_patch(patch))
    # full suite is selected; the two ids in module_importers are irrelevant
    assert {1, 2} < sel
