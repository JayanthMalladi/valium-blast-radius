"""Edits that only flip True/False values in one class's arg_types dict.

An arg_types value is read in one place: Expression.__init_subclass__ turns
the dict into required_args, and required_args is read only by
Expression.error_messages. So such an edit can change a test's outcome only
if that test validated an instance whose arg_types dict carries the flipped
value. maps/validated_classes.json records, per test, the classes (owners of
the arg_types dict) whose instances went through error_messages.
"""
from __future__ import annotations
import ast


def _arg_types_assign(cls: ast.ClassDef):
    for stmt in cls.body:
        if (isinstance(stmt, (ast.Assign, ast.AnnAssign))
                and any(isinstance(t, ast.Name) and t.id == "arg_types"
                        for t in (stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]))
                and isinstance(stmt.value, ast.Dict)):
            return stmt
    return None


def _is_bool(node) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def flipped_class(pristine: str, patched: str) -> str | None:
    """The class name when the only change is True/False values in its arg_types."""
    try:
        a, b = ast.parse(pristine), ast.parse(patched)
    except SyntaxError:
        return None
    ca = [n for n in ast.walk(a) if isinstance(n, ast.ClassDef)]
    cb = [n for n in ast.walk(b) if isinstance(n, ast.ClassDef)]
    if [c.name for c in ca] != [c.name for c in cb]:
        return None
    hit = None
    for x, y in zip(ca, cb):
        sx, sy = _arg_types_assign(x), _arg_types_assign(y)
        if sx is None or sy is None:
            continue
        dx, dy = sx.value, sy.value
        if ast.dump(dx) == ast.dump(dy):
            continue
        if len(dx.keys) != len(dy.keys):
            return None
        for kx, ky, vx, vy in zip(dx.keys, dy.keys, dx.values, dy.values):
            if (kx is None) != (ky is None):
                return None
            if kx is not None and ast.dump(kx) != ast.dump(ky):
                return None
            if ast.dump(vx) != ast.dump(vy) and not (_is_bool(vx) and _is_bool(vy)):
                return None
        if hit is not None:
            return None
        hit = (x.name, sx, sy)
    if hit is None:
        return None
    # Everything outside that one dict must be identical.
    name, sx, sy = hit
    sy.value = sx.value
    if ast.dump(a) != ast.dump(b):
        return None
    return name


def affected_owners(pristine_files: dict[str, str], name: str) -> set[str] | None:
    """name plus every class whose arg_types literal copies an affected one.

    Returns None when the class name is defined more than once (ambiguous).
    """
    owners = {name}
    defs = 0
    spreads: list[tuple[str, set[str]]] = []
    for rel, text in pristine_files.items():
        if not rel.startswith("sqlglot/") or not rel.endswith(".py"):
            continue
        if "arg_types" not in text and name not in text:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for cls in ast.walk(tree):
            if not isinstance(cls, ast.ClassDef):
                continue
            if cls.name == name:
                defs += 1
            st = _arg_types_assign(cls)
            if st is None:
                continue
            refs = {n.value.attr if isinstance(n.value, ast.Attribute) else n.value.id
                    for n in ast.walk(st.value)
                    if isinstance(n, ast.Attribute) and n.attr == "arg_types"
                    and isinstance(n.value, (ast.Name, ast.Attribute))}
            if refs:
                spreads.append((cls.name, refs))
    if defs != 1:
        return None
    changed = True
    while changed:
        changed = False
        for cname, refs in spreads:
            if cname not in owners and refs & owners:
                owners.add(cname)
                changed = True
    return owners
