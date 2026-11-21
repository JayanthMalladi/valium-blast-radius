"""Unit tests for the coarse canary rule."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector import patch as P
from selector.rules import RuleEngine
from selector.maps import Maps

REL = "sqlglot/opt.py"
PRISTINE = "x = 1\ny = 2\nz = 3\n"


def _patch(mod_path=REL):
    # replaces pristine line 2; the hunk's old-side context matches PRISTINE
    return """diff --git a/{rel} b/{rel}
--- a/{rel}
+++ b/{rel}
@@ -2,1 +2,1 @@
-y = 2
+z = 2
""".format(rel=mod_path)


def _engine(maps_dir, *, extra=None):
    data = {
        "id_order.json": ["a", "b", "c", "d", "e", "f"],
        "line_coverage.json": {},
        "source_readers.json": {},
        "test_files.json": {},
        "fixture_map.json": {},
    }
    if extra:
        data.update(extra)
    os.makedirs(maps_dir, exist_ok=True)
    for name, obj in data.items():
        with open(os.path.join(maps_dir, name), "w", encoding="utf-8") as f:
            json.dump(obj, f)
    m = Maps(maps_dir)
    m.load()
    id_by_node = {nid: i + 1 for i, nid in enumerate(m.id_order)}
    pristine = {REL: PRISTINE}
    return RuleEngine(m, id_by_node, pristine)


def test_canary_fires_when_line_map_empty(tmp_path):
    engine = _engine(str(tmp_path))
    sel = engine.select_for_files(P.parse_patch(_patch()))
    opt_exec = engine._opt_executor_numbers()
    assert sel == opt_exec, sel


def test_canary_does_not_override_line_map_hit(tmp_path):
    lc = {"sqlglot/opt.py": {"2": "0x08"}}
    engine = _engine(str(tmp_path), extra={"line_coverage.json": lc})
    sel = engine.select_for_files(P.parse_patch(_patch()))
    # line map covers test 4 (bit 3 -> "d" -> test 4)
    opt_exec = engine._opt_executor_numbers()
    # selected tests must be a subset of {covered tests} U {canary tests}
    assert sel <= opt_exec | {4}, sel


def test_canary_does_not_fire_on_comment_only(tmp_path):
    patch = """diff --git a/{rel} b/{rel}
--- a/{rel}
+++ b/{rel}
@@ -2,1 +2,2 @@
-y = 2
+y = 2
+# a comment
""".format(rel=REL)
    engine = _engine(str(tmp_path))
    sel = engine.select_for_files(P.parse_patch(patch))
    opt_exec = engine._opt_executor_numbers()
    assert sel & opt_exec == set(), sel
