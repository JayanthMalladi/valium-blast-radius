"""Conservative identity/equality substitutions from pristine operand profiles."""
from __future__ import annotations

import ast
import hashlib

_POLARITY = ({ast.Is, ast.Eq}, {ast.IsNot, ast.NotEq})


def comparison_swap(pristine: str, patched: str):
    """Return the sole changed comparison, with identical AST everywhere else.

    Restrict to one nonchained comparison and same polarity. Exact surrounding
    AST and operand equality prevent profile reuse for altered evaluation order,
    control flow, operands or another semantic edit in the file.
    """
    try:
        old, new = ast.parse(pristine), ast.parse(patched)
    except (SyntaxError, ValueError):
        return None
    swaps = []

    def same(a, b, parent=None):
        if type(a) is not type(b):
            if (isinstance(parent, ast.Compare) and len(parent.ops) == 1
                    and any({type(a), type(b)} == group for group in _POLARITY)):
                swaps.append(parent)
                return True
            return False
        if isinstance(a, ast.AST):
            return all(same(getattr(a, field), getattr(b, field), a) for field in a._fields)
        if isinstance(a, list):
            return len(a) == len(b) and all(same(x, y, parent) for x, y in zip(a, b))
        return a == b

    return swaps[0] if same(old, new) and len(swaps) == 1 else None


def profiled_noop(profiles: dict, rel: str, pristine: str, patched: str) -> bool:
    if profiles.get("version") != 1 or profiles.get("complete") is not True:
        return False
    context = profiles.get("verification_context", {})
    if not all(context.get(key) is True for key in ("unittest", "pytest", "core_unittest")):
        return False
    digest = hashlib.sha256(pristine.encode()).hexdigest()
    if profiles.get("source_sha256", {}).get(rel) != digest:
        return False
    site = comparison_swap(pristine, patched)
    if site is None:
        return False
    key = f"{rel}:{site.lineno}:{site.col_offset}"
    row = profiles.get("sites", {}).get(key)
    # An empty/unknown/unsafe site provides no applicability evidence.
    return isinstance(row, dict) and bool(row.get("pairs"))
