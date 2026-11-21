"""Statement-level lookup: find the smallest AST statement enclosing a
pristine line, and the line range to query the line map with.

Rules (S2 fix 2):
- simple statement  -> full [lineno..end_lineno]
- compound (if/elif/while/for/with/try/def/class) -> if the changed line
  is on the header, use the header only; otherwise the smallest enclosing
  statement inside the body is used (a continuation line of an inner
  `return (` maps to that return's range, not the whole def).
"""
from __future__ import annotations
import ast
from typing import Sequence


def _body_statements(node):
    """Direct child statements of a compound node (flat list)."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return list(node.body)
    if isinstance(node, ast.If):
        return list(node.body) + list(node.orelse or [])
    if isinstance(node, (ast.While, ast.For, ast.AsyncFor)):
        return list(node.body) + list(node.orelse or [])
    if isinstance(node, (ast.With, ast.AsyncWith)):
        return list(node.body)
    if isinstance(node, ast.Try):
        out = list(node.body) + list(node.orelse or []) + list(node.finalbody or [])
        for h in node.handlers:
            out.extend(h.body)
        return out
    return []


def _innermost(tree: ast.AST, line: int) -> ast.stmt | None:
    """Smallest statement whose [lineno..end_lineno] contains `line`."""
    best: ast.stmt | None = None
    stack = list(tree.body) if hasattr(tree, "body") else []
    while stack:
        s = stack.pop()
        if not hasattr(s, "lineno") or not hasattr(s, "end_lineno"):
            continue
        lo = s.lineno or 1
        hi = s.end_lineno or lo
        if lo <= line <= hi:
            best = s
            stack.extend(_body_statements(s))
    return best


def _header_end(s: ast.stmt) -> int:
    """Last header line of a compound statement."""
    children = _body_statements(s)
    if children:
        return min((x.lineno or 1) for x in children) - 1
    return s.end_lineno or s.lineno


def statement_range(tree: ast.AST, line: int) -> tuple[int, int]:
    """(start, end) 1-based inclusive range of the smallest enclosing stmt.
    Falls back to (line, line) when `line` is outside any stmt."""
    s = _innermost(tree, line)
    if s is None:
        return line, line
    if isinstance(s, (ast.If, ast.While, ast.For, ast.AsyncFor,
                      ast.With, ast.AsyncWith, ast.Try,
                      ast.FunctionDef, ast.AsyncFunctionDef,
                      ast.ClassDef)) and line <= _header_end(s):
        return s.lineno, _header_end(s)
    return s.lineno, s.end_lineno or s.lineno


def statement_ranges(tree: ast.AST, lines: Sequence[int]) -> list[tuple[int, int]]:
    """Deduplicated ranges covering each changed pristine line."""
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for ln in lines:
        r = statement_range(tree, ln)
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


# Back-compat alias used by older tests.
range_for_line = statement_range
