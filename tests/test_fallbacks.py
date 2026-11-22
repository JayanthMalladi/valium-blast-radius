"""Safe fallbacks (fix 3): any change whose effect cannot be bounded by the
maps selects the FULL SUITE.
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
PRISTINE = "x = 1\ny = 2\n"


def _maps_dir(tmp_path: Path, line_coverage: dict | None = None) -> Path:
    d = tmp_path / "maps"
    d.mkdir()
    data = {
        "id_order.json": ["a", "b", "c", "d", "e", "f", "g", "h"],
        # module_importers.json is no longer a selection source
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
    return RuleEngine(m, id_by_node, pristine if pristine is not None else {REL: PRISTINE})


def _full(engine: RuleEngine) -> set:
    return set(engine.id_by_node.values())


def test_import_break_selects_full_suite(tmp_path):
    patch = f"""diff --git a/{REL} b/{REL}
--- a/{REL}
+++ b/{REL}
@@ -2,1 +2,1 @@
-y = 2
+def f(:
"""
    engine = _engine(tmp_path)
    assert engine.select_for_files(P.parse_patch(patch)) == _full(engine)


def test_deleted_sqlglot_py_selects_full_suite(tmp_path):
    patch = f"""diff --git a/{REL} b/{REL}
deleted file mode 100644
index abcdef..0000000
--- a/{REL}
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
"""
    engine = _engine(tmp_path)
    assert engine.select_for_files(P.parse_patch(patch)) == _full(engine)


def test_binary_py_selects_full_suite(tmp_path):
    patch = f"""diff --git a/{REL} b/{REL}
new file mode 100644
Binary files /dev/null and b/{REL} differ
"""
    engine = _engine(tmp_path)
    assert engine.select_for_files(P.parse_patch(patch)) == _full(engine)


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


def test_mismatched_hunk_selects_full_suite(tmp_path):
    # A patch whose hunk does not match the pristine file.
    patch = f"""diff --git a/{REL} b/{REL}
--- a/{REL}
+++ b/{REL}
@@ -40,2 +40,2 @@
 totally = different
+here = 1
"""
    engine = _engine(tmp_path)
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
    engine = _engine(tmp_path)
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


def test_collection_sensitive_paths_use_full_suite(tmp_path):
    engine = _engine(tmp_path)
    for path in ("tests/helpers.py", "tests/dialects/conftest.py", "pyproject.toml", "sqlglotc/build.py"):
        patch = f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-old
+new
"""
        assert engine.select_for_files(P.parse_patch(patch)) == _full(engine)


def test_rename_handles_the_old_import_or_fixture_path(tmp_path):
    engine = _engine(tmp_path)
    for old in ("sqlglot/module.py", "tests/fixtures/data.sql", "tests/helpers.py"):
        patch = f"""diff --git a/{old} b/moved.txt
similarity index 100%
rename from {old}
rename to moved.txt
"""
        assert engine.select_for_files(P.parse_patch(patch)) == _full(engine)


def test_unrelated_rename_does_not_force_full_suite(tmp_path):
    engine = _engine(tmp_path)
    patch = """diff --git a/docs/old.md b/docs/new.md
similarity index 100%
rename from docs/old.md
rename to docs/new.md
"""
    assert engine.select_for_files(P.parse_patch(patch)) == set()
