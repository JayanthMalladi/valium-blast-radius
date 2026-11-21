"""Classify what changed in a patched file, and map the changed lines to the
executable regions they fall in (function, class body, or module level).

Stdlib only. Fast enough for the whole batch under the run container's limits.
"""
from __future__ import annotations
import ast
import difflib

# Category constants
CODE_CHANGE = "code_change"
COMMENT_ONLY = "comment_only"
IMPORT_BREAK = "import_break"


def classify_file_change(pristine_text: str | None, patched_text: str | None,
                         changed_lines: set[int] | None = None) -> tuple[str, list[dict]]:
    """Classify a per-file change.

    pristine_text / patched_text: full texts (None = file absent on that side).
    changed_lines: 1-based line numbers in the NEW file whose content is '+'
    (from the patch). If None, it is derived by diffing the two texts.

    Returns (category, regions): regions is a list of
    {"kind": "function"|"class"|"module", "name": str, "lines": [int,...]}.
    """
    if patched_text is None:
        # File deleted. Its code is gone; everything that imported it or
        # relied on its module-level state breaks. Category: code change.
        return (CODE_CHANGE, [])

    if pristine_text is None:
        # Brand-new file: every line is new code.
        return (CODE_CHANGE, _regions_of_new_file(patched_text, changed_lines or set()))

    new_tree = _safe_parse(patched_text)
    old_tree = _safe_parse(pristine_text)
    if new_tree is None:
        return (IMPORT_BREAK, [])

    # Comment-only? ASTs are identical when only comments or docstrings changed.
    if old_tree is not None and ast.dump(_norm(new_tree)) == ast.dump(_norm(old_tree)):
        return (COMMENT_ONLY, [])

    if changed_lines is None:
        changed_lines = _diff_changed_lines(pristine_text, patched_text)
    regions = _regions_for_lines(sorted(changed_lines), new_tree)
    return (CODE_CHANGE, regions)


def _safe_parse(text: str):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _norm(tree):
    """Tree with bare string expressions (docstrings) removed, so docstring
    edits do not count as code changes."""
    return _NormTree().visit(tree)


class _NormTree(ast.NodeTransformer):
    """Drop bare string Exprs from a tree in place."""

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        self.generic_visit(node)
        return node


def _diff_changed_lines(old_text: str, new_text: str) -> set[int]:
    sm = difflib.SequenceMatcher(
        a=old_text.splitlines(), b=new_text.splitlines(), autojunk=False)
    changed: set[int] = set()
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            changed.update(range(j1 + 1, j2 + 1))
    return changed


def _regions_for_lines(changed: list[int], tree) -> list[dict]:
    """Group changed lines by the deepest def/class enclosing each line."""
    funcs: list[tuple[int, int, str, str]] = []  # (start, end, name, kind)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.end_lineno and node.lineno:
                funcs.append((node.lineno, node.end_lineno, node.name, "function"))
        elif isinstance(node, ast.ClassDef):
            if node.end_lineno and node.lineno:
                funcs.append((node.lineno, node.end_lineno, node.name, "class"))
    if not funcs:
        return [{"kind": "module", "name": "<top>", "lines": changed}] if changed else []

    per: dict[tuple, list[int]] = {}
    for line in changed:
        # pick the deepest enclosing function/class (latest start, innermost)
        best = None
        # check enclosing candidates: the ones with start <= line and end >= line
        for f in funcs:
            s, e, name, kind = f
            if s <= line <= e:
                if best is None or s >= best[0]:
                    best = f
        if best is not None:
            per.setdefault((best[3], best[2]), []).append(line)
        else:
            per.setdefault(("module", "<top>"), []).append(line)
    return [{"kind": k, "name": n, "lines": sorted(ls)} for (k, n), ls in per.items()]


def _regions_of_new_file(text: str, changed: set[int]) -> list[dict]:
    tree = _safe_parse(text)
    if tree is None:
        return []
    return _regions_for_lines(sorted(changed), tree)
