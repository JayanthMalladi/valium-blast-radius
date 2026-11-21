"""Tests for changed_pristine_lines (fix 1: pristine line numbers)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector.pristine_lines import changed_pristine_lines
from selector import patch as P


def _parse(text):
    return P.parse_patch(text)


def test_mid_function_insertion():
    # Pure insertion between old lines 6 and 7
    text = """diff --git a/sqlglot/opt.py b/sqlglot/opt.py
--- a/sqlglot/opt.py
+++ b/sqlglot/opt.py
@@ -5,4 +5,5 @@ def f():
     x = 1
     y = 2
+    z = 3
     return x
"""
    fp = _parse(text)[0]
    assert changed_pristine_lines(fp) == [6, 7]


def test_deletion_only_hunk_produces_lines():
    text = """diff --git a/sqlglot/opt.py b/sqlglot/opt.py
--- a/sqlglot/opt.py
+++ b/sqlglot/opt.py
@@ -2,2 +2,2 @@ def f():
     x = 1
-    y = 2
     return x
"""
    fp = _parse(text)[0]
    assert changed_pristine_lines(fp) == [3]   # deleted line only; no trailing anchor


def test_two_hunks_in_one_file():
    text = """diff --git a/sqlglot/opt.py b/sqlglot/opt.py
--- a/sqlglot/opt.py
+++ b/sqlglot/opt.py
@@ -1,2 +2,2 @@ def f():
-x = 1
+xx = 11
     y = 2
@@ -10,3 +10,3 @@ def f():
     b = 2
-c = 3
+cc = 33
     d = 4
"""
    fp = _parse(text)[0]
    # each hunk independent; modifications anchor only to the `-` line
    assert changed_pristine_lines(fp) == [1, 11]


def test_2jrq_patch_real():
    text = open(
        Path(__file__).parent.parent.parent / "kit/sample/sample/commits/2jrq.patch",
        encoding="utf-8"
    ).read()
    fp = [f for f in _parse(text) if f.path == "sqlglot/optimizer/eliminate_joins.py"][0]
    res = changed_pristine_lines(fp)
    assert res == [71]


def test_rszg_snowflake_real():
    text = open(
        Path(__file__).parent.parent.parent / "kit/sample/sample/commits/rszg.patch",
        encoding="utf-8"
    ).read()
    fp = [f for f in _parse(text) if f.path == "sqlglot/typing/snowflake.py"][0]
    res = changed_pristine_lines(fp)
    assert res == [101]
