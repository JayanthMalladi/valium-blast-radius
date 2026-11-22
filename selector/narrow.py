"""Narrow selection for class constants whose readers are bounded statically.

A class-level `NAME = <literal>` is observable only where code reads NAME.
When every read in sqlglot is inside a function body (none at import time, in
class-construction code, or built from pieces in an f-string), the tests that
executed a read, and test methods that name NAME, are the only ones that can
observe the new value. narrow() returns None when that does not hold; the
caller then keeps the ordinary statement-level rule.
"""
from __future__ import annotations

import ast
import re

_CONSTRUCTION_FUNCS = {"__new__", "__init_subclass__", "__set_name__", "__class_getitem__"}


def _diff(a, b, out: list) -> None:
    if type(a) is not type(b):
        out.append((a, b))
        return
    if isinstance(a, ast.AST):
        for f in a._fields:
            va, vb = getattr(a, f, None), getattr(b, f, None)
            if isinstance(va, list) and isinstance(vb, list):
                if len(va) != len(vb):
                    out.append((a, b))
                    return
                for x, y in zip(va, vb):
                    _diff(x, y, out)
            elif isinstance(va, ast.AST) or isinstance(vb, ast.AST):
                _diff(va, vb, out)
            elif va != vb:
                out.append((a, b))
                return
    elif a != b:
        out.append((a, b))


def _parents(tree) -> dict:
    p = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            p[child] = node
    return p


def _ancestors(node, parents):
    while node in parents:
        node = parents[node]
        yield node


def _within(node, root, parents) -> bool:
    return node is root or any(a is root for a in _ancestors(node, parents))


def _name_piece(name: str, text: str) -> bool:
    """True when `text` is a whole underscore-delimited prefix or suffix of
    `name` (with or without the joining underscore), e.g. "WEEK_", "_OFFSET"
    or "OFFSET" for WEEK_OFFSET: an f-string could build the name from it."""
    core = text.strip("_")
    if not core or core == name:
        return False
    return name.startswith(core + "_") or name.endswith("_" + core)


def _literal(node) -> bool:
    try:
        ast.literal_eval(node)
        return True
    except Exception:
        return False


class Narrower:
    def __init__(self, pristine: dict[str, str]) -> None:
        self.sources = {r: s for r, s in pristine.items()
                        if r.startswith("sqlglot/") and r.endswith(".py")}
        self.tests = {r: s for r, s in pristine.items()
                      if r.startswith("tests/") and r.endswith(".py")}
        self._index = None

    # -- pristine-tree index: function-body lines and class hierarchy ------
    def _build(self):
        body_lines: dict[str, dict[int, ast.AST]] = {}
        bases: dict[str, set[str]] = {}
        self._trees = {}
        self._parent_cache: dict = {}
        self._lambdas: dict[str, list] = {}
        self._docs: dict[str, set[int]] = {}
        self._spreads: dict[str, set[str]] = {}
        for rel, src in self.sources.items():
            try:
                tree = ast.parse(src)
            except SyntaxError:
                continue
            self._trees[rel] = tree
            fl: dict[int, ast.AST] = {}
            lams = []
            docs: set[int] = set()
            for node in ast.walk(tree):
                body = getattr(node, "body", None)
                if (isinstance(body, list) and body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    docs.update(range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1))
                if isinstance(node, ast.Lambda):
                    lams.append((node.lineno, node.body.end_lineno or node.lineno))
                if isinstance(node, ast.ClassDef):
                    names = set()
                    for b in node.bases:
                        if isinstance(b, ast.Name):
                            names.add(b.id)
                        elif isinstance(b, ast.Attribute):
                            names.add(b.attr)
                    bases.setdefault(node.name, set()).update(names)
                    for sub in ast.walk(node):
                        if (isinstance(sub, ast.Attribute) and sub.attr == "arg_types"
                                and isinstance(sub.value, ast.Name)):
                            self._spreads.setdefault(sub.value.id, set()).add(node.name)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for s in node.body:
                        for ln in range(s.lineno, (s.end_lineno or s.lineno) + 1):
                            # innermost function wins (ast.walk is breadth-first)
                            fl[ln] = node
            body_lines[rel] = fl
            self._lambdas[rel] = lams
            self._docs[rel] = docs
        self._index = (body_lines, bases)
        return self._index

    def _ancestry(self, name: str) -> set[str]:
        _, bases = self._index or self._build()
        seen, todo = set(), [name]
        while todo:
            n = todo.pop()
            for b in bases.get(n, ()):
                if b not in seen:
                    seen.add(b)
                    todo.append(b)
        return seen

    def _subclasses(self, name: str) -> set[str]:
        _, bases = self._index or self._build()
        return {c for c in bases if name in self._ancestry(c)}

    def _mentions(self, names: set[str]):
        """Yield (rel, line, function-or-None) for every non-comment mention."""
        body_lines, _ = self._index or self._build()
        pat = re.compile(r"\b(" + "|".join(re.escape(n) for n in sorted(names)) + r")\b")
        for rel, src in self.sources.items():
            fl = body_lines.get(rel, {})
            docs = self._docs.get(rel, set())
            for i, line in enumerate(src.splitlines(), 1):
                if line.lstrip().startswith("#") or i in docs or not pat.search(line):
                    continue
                yield rel, i, fl.get(i)

    def _test_mentions(self, name: str):
        """(node ids of test methods naming it, test files naming it elsewhere)."""
        pat = re.compile(r"\b" + re.escape(name) + r"\b")
        ids, files = set(), set()
        for rel, src in self.tests.items():
            if not pat.search(src):
                continue
            try:
                tree = ast.parse(src)
            except SyntaxError:
                files.add(rel)
                continue
            lines = src.splitlines()
            covered = set()
            for node in tree.body:
                classes = [node] if isinstance(node, ast.ClassDef) else []
                funcs = [(None, node)] if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) else []
                for c in classes:
                    funcs += [(c.name, f) for f in c.body
                              if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))]
                for cname, f in funcs:
                    if not f.name.startswith("test"):
                        continue
                    span = range(f.lineno, f.end_lineno + 1)
                    if any(pat.search(lines[i - 1]) for i in span):
                        ids.add(rel + "::" + (cname + "::" if cname else "") + f.name)
                    covered.update(span)
            if any(pat.search(l) for i, l in enumerate(lines, 1) if i not in covered):
                files.add(rel)
        return ids, files

    def _value_reference(self, rel: str, line: int, names: set[str]) -> bool:
        tree = self._trees.get(rel)
        if tree is None:
            return True
        if rel not in self._parent_cache:
            self._parent_cache[rel] = _parents(tree)
        parents = self._parent_cache[rel]
        for node in ast.walk(tree):
            ident = (node.attr if isinstance(node, ast.Attribute)
                     else node.id if isinstance(node, ast.Name) else None)
            if ident not in names or getattr(node, "lineno", None) != line:
                continue
            par = parents.get(node)
            if isinstance(par, ast.Attribute):
                continue  # e.g. C.arg_types or exp.C.something: handled by its own node
            if isinstance(par, ast.Dict) and any(k is node for k in par.keys):
                continue
            if isinstance(par, ast.ClassDef) and node in par.bases:
                continue
            anc = list(_ancestors(node, parents))
            if any(isinstance(a, (ast.arg,)) or
                   (isinstance(a, ast.AnnAssign) and _within(node, a.annotation, parents))
                   for a in anc):
                continue
            return True
        return False

    # -- entry point -------------------------------------------------------
    def narrow(self, rel: str, pristine: str, patched: str):
        """Return ("lines", [(rel, line), ...], test_files) or None."""
        try:
            ta, tb = ast.parse(pristine), ast.parse(patched)
        except SyntaxError:
            return None
        diffs: list = []
        _diff(ta, tb, diffs)
        if not diffs:
            return None
        pa, pb = _parents(ta), _parents(tb)
        for rule in (self._class_constant,):
            res = rule(rel, diffs, pa, pb)
            if res is not None:
                return res
        return None

    def _class_assign(self, node, parents):
        """The class-level single-target Assign whose value contains node."""
        for anc in _ancestors(node, parents):
            if isinstance(anc, ast.Assign):
                owner = parents.get(anc)
                if (isinstance(owner, ast.ClassDef) and len(anc.targets) == 1
                        and isinstance(anc.targets[0], ast.Name)
                        and _within(node, anc.value, parents)):
                    return anc, owner
                return None
        return None

    def _class_constant(self, rel, diffs, pa, pb):
        target = None
        for a, b in diffs:
            ha, hb = self._class_assign(a, pa), self._class_assign(b, pb)
            if ha is None or hb is None:
                return None
            if target is not None and ha[0] is not target[0]:
                return None
            target, other = ha, hb
        assign, owner = target
        name = assign.targets[0].id
        if (name == "arg_types" or other[0].targets[0].id != name
                or not _literal(assign.value) or not _literal(other[0].value)):
            return None
        if "type" in self._ancestry(owner.name) or any(
                isinstance(b, ast.Name) and b.id == "type" for b in owner.bases):
            return None
        # Names built from pieces in f-strings (e.g. f"{x}_OFFSET").
        self._index or self._build()
        for tree in self._trees.values():
            for node in ast.walk(tree):
                if isinstance(node, ast.JoinedStr):
                    for v in node.values:
                        if isinstance(v, ast.Constant) and isinstance(v.value, str) \
                                and _name_piece(name, v.value):
                            return None
        lines = []
        defn = re.compile(r"^\s*" + re.escape(name) + r"\s*(:[^=]*)?=(?!=)")
        for r, i, fn in self._mentions({name}):
            text = self.sources[r].splitlines()[i - 1]
            if fn is None:
                if defn.match(text) and len(re.findall(r"\b" + re.escape(name) + r"\b", text)) == 1:
                    continue
                return None
            fname = getattr(fn, "name", "")
            if fname in _CONSTRUCTION_FUNCS or fname.startswith("_init"):
                return None
            lines.append((r, i))
        return ("lines", lines, self._test_mentions(name))
