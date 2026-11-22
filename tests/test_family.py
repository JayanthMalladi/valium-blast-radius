"""Dialect-family rule: a change to one file of a sqlglot dialect family
(dialects/, generators/, parsers/, typing/ with the same module stem)
also selects tests that executed any line of the sibling family files,
at the pinned commit. This is general line-coverage structure, not
patch-specific data.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector import patch as P
from selector.maps import Maps
from selector.rules import RuleEngine

REL = "sqlglot/dialects/tsql.py"
PRISTINE = "x = 1\ny = 2\nz = 3\n"


def _engine(tmp_path: Path, line_coverage: dict | None = None,
            extra_pristine: dict | None = None) -> RuleEngine:
    d = tmp_path / "maps"
    d.mkdir()
    data = {
        "id_order.json": ["a", "b", "c", "d", "e", "f"],
        "line_coverage.json": line_coverage or {},
        "source_readers.json": {},
        "fixture_map.json": {},
        "test_files.json": {},
        "unknown_loaders.json": {},
    }
    for name, obj in data.items():
        (d / name).write_text(json.dumps(obj), encoding="utf-8")
    m = Maps(str(d))
    m.load()
    id_by_node = {nid: i + 1 for i, nid in enumerate(m.id_order)}
    pristine = {REL: PRISTINE}
    if extra_pristine:
        pristine.update(extra_pristine)
    eng = RuleEngine(m, id_by_node, pristine)
    eng._family = True   # BR_FAMILY=1 (off by default)
    return eng


def test_family_sibling_file_lines_are_selected(tmp_path):
    # line 2 of dialects/tsql.py runs in test "d" (bit 3);
    # line 2 of the sibling generators/tsql.py runs in test "e" (bit 4).
    # A change to line 2 must select both: the statement credit and the
    # family sibling credit.
    lc = {
        REL: {"2": "0x08"},                    # bit 3 -> "d" (test 4)
        "sqlglot/generators/tsql.py": {"2": "0x10"},  # bit 4 -> "e" (test 5)
    }
    engine = _engine(tmp_path, lc)
    patch = f"""diff --git a/{REL} b/{REL}
--- a/{REL}
+++ b/{REL}
@@ -2,1 +2,1 @@
-y = 2
+z = 2
"""
    sel = engine.select_for_files(P.parse_patch(patch))
    assert sel == {4, 5}, sel


def test_family_is_by_dialect_stem_not_directory(tmp_path):
    # parsers/bigquery.py is a sibling of dialects/bigquery.py;
    # a different stem (tsql) never pulls in bigquery credits.
    lc = {
        "sqlglot/dialects/bigquery.py": {"2": "0x08"},  # "d"
        "sqlglot/parsers/bigquery.py": {"2": "0x10"},   # "e"
        "sqlglot/generators/tsql.py": {"2": "0x20"},    # "f"
    }
    engine = _engine(tmp_path, lc, extra_pristine={
        "sqlglot/dialects/bigquery.py": PRISTINE,
        "sqlglot/parsers/bigquery.py": PRISTINE,
        "sqlglot/generators/tsql.py": PRISTINE,
    })
    patch = """diff --git a/sqlglot/dialects/bigquery.py b/sqlglot/dialects/bigquery.py
--- a/sqlglot/dialects/bigquery.py
+++ b/sqlglot/dialects/bigquery.py
@@ -2,1 +2,1 @@
-y = 2
+z = 2
"""
    sel = engine.select_for_files(P.parse_patch(patch))
    assert sel == {4, 5}, sel
    assert 6 not in sel


def test_family_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("BR_FAMILY", raising=False)
    eng = _engine(tmp_path)
    assert RuleEngine(eng.maps, eng.id_by_node, eng.pristine)._family is False
