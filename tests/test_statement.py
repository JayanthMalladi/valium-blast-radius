"""Unit tests for the statement-level AST lookup (fix 2)."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector.statement import range_for_line, statement_ranges


def test_continuation_of_return_maps_to_return_range():
    # A changed physical line inside the `return (` starting at line 63
    # (line 71) must map to the return statement's range (63, 77).
    src = open(
        Path(__file__).parent.parent.parent / "work/sqlglot/sqlglot/optimizer/eliminate_joins.py",
        encoding="utf-8",
    ).read()
    tree = ast.parse(src)
    assert range_for_line(tree, 71) == (63, 77)


def test_continuation_of_if_maps_to_if_header_range():
    # A changed physical line 101 inside the `if (` header at line 98
    # must map to the if statement's range (98, 103).
    src = open(
        Path(__file__).parent.parent.parent / "work/sqlglot/sqlglot/typing/snowflake.py",
        encoding="utf-8",
    ).read()
    tree = ast.parse(src)
    assert range_for_line(tree, 101) == (98, 103)
    # Header line itself maps to the same range
    assert range_for_line(tree, 98) == (98, 103)


def test_body_line_maps_to_enclosing_simple_stmt():
    src = open(
        Path(__file__).parent.parent.parent / "work/sqlglot/sqlglot/typing/snowflake.py",
        encoding="utf-8",
    ).read()
    tree = ast.parse(src)
    # Line 104 is `self._set_type(...)` inside the if-body
    r = range_for_line(tree, 104)
    assert r == (104, 104)


def test_simple_statement_its_own_range():
    tree = ast.parse("x = 1\ny = 2\n")
    assert range_for_line(tree, 1) == (1, 1)
    assert range_for_line(tree, 2) == (2, 2)


def test_statement_ranges_dedupes():
    tree = ast.parse("def f():\n    x = 1\n    return x\n")
    r = statement_ranges(tree, [3, 4, 3])
    assert sorted(r) == [(3, 3), (4, 4)]


def test_range_outside_any_stmt_falls_back():
    tree = ast.parse("x = 1\n")
    assert range_for_line(tree, 999) == (999, 999)
