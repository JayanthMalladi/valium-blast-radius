"""Decide which tests to run for a commit, using maps from the pinned commit.

All lookups return node ids; the runtime layer maps them to test numbers.
BR_DEBUG=1 writes `work/runs/<run>.reasons.jsonl`:
  one JSON line per commit: {"commit": cid, "reasons": [{"test": <number>, "line": "<module>:<pristine line>", "rule": "<why selected>"}]}
BR_FAMILY=1 re-enables the dialect-family union (off by default).
BR_CANARY=1 enables the coarse optimizer+executor canary (off by default since
the v2 per-test maps credit the spawn-pool optimizer/executor tests directly).
"""
from __future__ import annotations
import ast
import json
import os

from . import patch as P
from .hunkapply import apply_file_patch, patch_applies
from .maps import Maps
from .pristine_lines import changed_pristine_lines
from .statement import statement_ranges
from .operands import profiled_noop


DATA = os.environ.get("BR_DATA", "/data")
RUN_NAME = os.environ.get("BR_DEBUG_RUN", "debug")
_THIN_CANARY = 50   # fire canary when code-change selection is below this
_SHARED_TEST_FILES = {"tests/__init__.py", "tests/helpers.py"}
_HEAP_REACH = ("sqlglot/dialects/", "sqlglot/generators/", "sqlglot/parsers/",
               "sqlglot/tokenizers/", "sqlglot/generator.py", "sqlglot/parser.py",
               "sqlglot/tokens.py", "sqlglot/time.py")
_BUILD_FILES = {"pyproject.toml", "setup.py", "setup.cfg", "pytest.ini", "tox.ini", "conftest.py"}


def _write_reasons(path: str, entries: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")
    except OSError:
        pass


def _safe_parse(text: str):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _norm(tree):
    return _NormTree().visit(tree)


class _NormTree(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        self.generic_visit(node)
        return node


def _classify(pristine: str | None, patched: str | None) -> str:
    if patched is None:
        return "code_change"
    if pristine is None:
        return "code_change"
    new_tree = _safe_parse(patched)
    old_tree = _safe_parse(pristine)
    if new_tree is None:
        return "import_break"
    if old_tree is not None and ast.dump(_norm(new_tree)) == ast.dump(_norm(old_tree)):
        return "comment_only"
    return "code_change"


_GM_NARROW = int(os.environ.get("BR_GM_K", "50"))


def _body_only(tree, lines) -> bool:
    """True when every line lies in code that runs only when called.

    That is a function body after its header, or a lambda's lines strictly
    between its first and last line (those two can hold dict keys, defaults
    or other code that runs where the lambda is defined).
    """
    if not lines:
        return False
    spans = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            spans.append((node.body[0].lineno, node.end_lineno))
        elif isinstance(node, ast.Lambda) and not node.args.defaults and not node.args.kw_defaults:
            spans.append((node.lineno + 1, node.end_lineno - 1))
    return all(any(a <= ln <= b for a, b in spans) for ln in lines)


def _with_hunks(fp: P.FilePatch, hunks: list) -> P.FilePatch:
    return P.FilePatch(path=fp.path, old_path=fp.old_path, is_new=fp.is_new,
                       is_deleted=fp.is_deleted, is_binary=fp.is_binary,
                       is_renamed=fp.is_renamed, hunks=list(hunks))


def _hunk_is_comment_only(pristine: str, fp: P.FilePatch, hunk) -> bool:
    """True when applying `hunk` alone to the pristine file parses and leaves
    the docstring-stripped AST identical (only comments, blank lines or
    docstrings changed)."""
    if len(fp.hunks) == 1:
        return False   # the whole-file check already decided this
    one = apply_file_patch(pristine, _with_hunks(fp, [hunk]))
    return one is not None and _classify(pristine, one) == "comment_only"


def _heap_observers(pristine: dict[str, str], id_by_node: dict[str, int]) -> set[int]:
    """Find tests directly observing the process-wide Python allocation heap.

    Coverage bounds executed instructions, not retained objects/finalizers from
    other tests in the same worker. A semantic source change can alter that
    heap even when an observing test never executes the changed instruction.
    Derive observers from pinned source, without names or runtime test numbers.
    """
    observers = set()
    probes = {"get_traced_memory", "get_tracemalloc_memory", "take_snapshot"}
    for rel, source in pristine.items():
        if not rel.startswith("tests/") or "tracemalloc" not in source:
            continue
        tree = _safe_parse(source)
        if tree is None:
            continue
        modules = set()
        functions = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(a.asname or a.name for a in node.names if a.name == "tracemalloc")
            elif isinstance(node, ast.ImportFrom) and node.module == "tracemalloc":
                functions.update(a.asname or a.name for a in node.names if a.name in probes)

        def visit(node, names, modules=modules, functions=functions, rel=rel):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                names = [*names, node.name]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for call in ast.walk(node):
                    if not isinstance(call, ast.Call):
                        continue
                    target = call.func
                    if ((isinstance(target, ast.Name) and target.id in functions)
                            or (isinstance(target, ast.Attribute) and target.attr in probes
                                and isinstance(target.value, ast.Name)
                                and target.value.id in modules)):
                        number = id_by_node.get("::".join([rel, *names]))
                        if number is not None:
                            observers.add(number)
            for child in ast.iter_child_nodes(node):
                visit(child, names)

        visit(tree, [])
    return observers


def _test_importers(pristine: dict[str, str]) -> dict[str, set[str]]:
    """Test files that import each test module, transitively (e.g. every
    dialect test imports Validator from tests/dialects/test_dialect.py)."""
    files = {rel: src for rel, src in pristine.items()
             if rel.startswith("tests/") and rel.endswith(".py")}
    by_module = {rel[:-3].replace("/", "."): rel for rel in files}
    for rel in list(files):
        if rel.endswith("/__init__.py"):
            by_module[rel[:-12].replace("/", ".")] = rel
    direct: dict[str, set[str]] = {}
    for rel, src in files.items():
        tree = _safe_parse(src)
        if tree is None:
            continue
        pkg = rel.rsplit("/", 1)[0].replace("/", ".")
        for node in ast.walk(tree):
            mods = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = pkg.split(".")
                    parts = parts[:len(parts) - node.level + 1]
                    base = ".".join(parts + ([base] if base else []))
                mods = [base] + [f"{base}.{a.name}" for a in node.names]
            for mod in mods:
                target = by_module.get(mod)
                if target and target != rel:
                    direct.setdefault(target, set()).add(rel)
    out: dict[str, set[str]] = {}
    for target in direct:
        seen, todo = set(), list(direct[target])
        while todo:
            f = todo.pop()
            if f not in seen:
                seen.add(f)
                todo.extend(direct.get(f, ()))
        out[target] = seen
    return out


def _class_setup_paths(pristine: dict[str, str]) -> dict[tuple[str, str], set[str]]:
    """Path fragments read in each test class's setUpClass. Coverage maps
    credit a file opened there to the first test the class ran, but every
    test in the class depends on it."""
    out: dict[tuple[str, str], set[str]] = {}
    for rel, src in pristine.items():
        if not (rel.startswith("tests/") and rel.endswith(".py")):
            continue
        tree = _safe_parse(src)
        if tree is None:
            continue
        consts: dict[str, set[str]] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                strs = {c.value for c in ast.walk(node.value)
                        if isinstance(c, ast.Constant) and isinstance(c.value, str)}
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        consts[t.id] = strs
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef):
                continue
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == "setUpClass":
                    frags = set()
                    for n in ast.walk(fn):
                        if isinstance(n, ast.Constant) and isinstance(n.value, str):
                            frags.add(n.value)
                        elif isinstance(n, ast.Name):
                            frags |= consts.get(n.id, set())
                    frags = {f.strip("/") for f in frags if "/" in f or "." in f}
                    frags = {f for f in frags if len(f) >= 4}
                    if frags:
                        out[(rel, cls.name)] = frags
    return out


class RuleEngine:
    def __init__(self, maps: Maps, id_by_node: dict[str, int],
                 pristine_files: dict[str, str]) -> None:
        self.maps = maps
        self.id_by_node = id_by_node
        self.pristine = pristine_files
        self._debug = os.environ.get("BR_DEBUG") == "1"
        self._canary = os.environ.get("BR_CANARY") == "1"
        # Dialect-family union: off by default. It was added to cover gaps in
        # the v1 maps; the v2 per-test maps credit sibling files directly, and
        # the union (which includes the changed file's own lines) undoes
        # statement-level precision for every dialect-family file.
        self._family = os.environ.get("BR_FAMILY") == "1"
        self._reasons: list[dict] = []
        self._opt_exec_ids: set[int] | None = None
        self._heap_observer_ids = _heap_observers(pristine_files, id_by_node)
        self._test_importers = _test_importers(pristine_files)
        self._class_setup_paths = _class_setup_paths(pristine_files)

    # ------------------------------------------------------------------
    def _ids(self, node_ids: list) -> set:
        out = set()
        for nid in node_ids:
            n = self.id_by_node.get(nid)
            if n is not None:
                out.add(n)
        return out

    def _full_suite_numbers(self) -> set:
        return set(self.id_by_node.values())

    def _opt_executor_numbers(self) -> set:
        if self._opt_exec_ids is None:
            nids = set()
            for rel in ("tests/test_optimizer.py", "tests/test_executor.py"):
                nids |= set(self.maps.testfile_ids(rel))
            self._opt_exec_ids = self._ids(list(nids))
        return self._opt_exec_ids

    def _line_numbers(self, rel: str, ln: int) -> set:
        return self._ids(self.maps.line_ids(rel, ln))

    def _family_numbers(self, rel: str) -> set:
        return self._ids(self.maps.family_ids(rel))

    def _testfile_numbers(self, rel: str) -> set:
        return self._ids(self.maps.testfile_ids(rel))

    def _test_module_numbers(self, rel: str) -> set:
        # A test module's own tests plus the tests of every module importing it.
        out = self._testfile_numbers(rel)
        for importer in self._test_importers.get(rel, ()):
            out |= self._testfile_numbers(importer)
        return out

    def _fixture_numbers(self, rel: str) -> set:
        out = self._ids(self.maps.fixture_ids(rel))
        for (test_rel, cls), frags in self._class_setup_paths.items():
            if any(f in rel for f in frags):
                marker = f"::{cls}::"
                out |= self._ids([n for n in self.maps.testfile_ids(test_rel) if marker in n])
        return out

    def _reader_numbers(self, rel: str) -> set:
        return self._ids(self.maps.reader_ids(rel))

    def _unknown_loader_numbers(self, rel: str) -> set:
        return self._ids(self.maps.unknown_loader_ids(rel))

    # ------------------------------------------------------------------
    def select_for_files(self, files: list) -> set:
        # The first evaluation argument requires an isolated semantic edit:
        # another file could change which operand values reach this site.
        self._operand_isolated_file = len(files) == 1
        sel: set = set()
        for fp in files:
            sel |= self._file(fp)
        return sel

    def record_reasons(self, commit: str, selected: set[int]) -> None:
        if not self._debug or not selected:
            return
        reasons_path = os.path.join("work", "runs", f"{RUN_NAME}.reasons.jsonl")
        entries = []
        for num in sorted(selected):
            line_label = ""
            rule_label = "canary"
            for r in self._reasons:
                if r.get("commit") == commit and r.get("test") == num:
                    line_label = r.get("line", "")
                    rule_label = r.get("rule", rule_label)
                    break
            entries.append({"commit": commit, "test": num, "line": line_label, "rule": rule_label})
        _write_reasons(reasons_path, entries)

    # ------------------------------------------------------------------
    def _file(self, fp: P.FilePatch) -> set:
        rel = fp.path
        paths = {rel, fp.old_path}
        if any(path in _BUILD_FILES or path in _SHARED_TEST_FILES or
               path.startswith("sqlglotc/") or path.endswith("/conftest.py") for path in paths):
            # Shared setup and build changes can affect collection outside
            # the edited file. Line coverage does not capture that dependency.
            return self._full_suite_numbers()
        if fp.is_renamed:
            if any(path.startswith(("sqlglot/", "tests/")) for path in paths):
                # Imports and fixture reads may still resolve the old path.
                return self._full_suite_numbers()
        if fp.is_binary:
            # A source file replaced by a binary blob cannot be bounded by the
            # maps: any importer can break. Safe fallback: full suite.
            if rel.endswith(".py") and rel.startswith("sqlglot/"):
                return self._full_suite_numbers()
            if rel.startswith("tests/") and rel.endswith(".py"):
                return self._test_module_numbers(rel)
            if rel.startswith("tests/fixtures/"):
                return self._fixture_numbers(rel) or self._testfile_numbers("tests/test_optimizer.py")
            return set()
        if fp.is_deleted:
            if rel.startswith("sqlglot/") and rel.endswith(".py"):
                return self._full_suite_numbers()
            if rel.startswith("tests/") and rel.endswith(".py"):
                return self._test_module_numbers(rel)
            if rel.startswith("tests/fixtures/") or rel.endswith((".sql", ".json")):
                return self._fixture_numbers(rel) or self._testfile_numbers("tests/test_optimizer.py")
            return set()
        if rel.startswith("tests/"):
            if rel.endswith(".py"):
                return self._test_module_numbers(rel)
            if rel.startswith("tests/fixtures/") or rel.endswith((".sql", ".json")):
                return self._fixture_numbers(rel) or self._testfile_numbers("tests/test_optimizer.py")
            return set()
        if not rel.startswith("sqlglot/") or not rel.endswith(".py"):
            return set()
        return self._sqlglot(fp, rel)

    def _sqlglot(self, fp: P.FilePatch, rel: str) -> set:
        # The heap observers (test_generator_memory) are kept for edits that can
        # reach dialect construction or the generator: every labelled change that
        # broke it, including one that broke it only in a grouped run, was in this
        # code. Elsewhere they are kept only when coverage selects them.
        if os.environ.get("BR_GM_GUARD", "1") == "1" and not rel.startswith(_HEAP_REACH):
            saved = self._heap_observer_ids
            self._heap_observer_ids = set()
            try:
                return self._sqlglot_inner(fp, rel)
            finally:
                self._heap_observer_ids = saved
        return self._sqlglot_inner(fp, rel)

    def _sqlglot_inner(self, fp: P.FilePatch, rel: str) -> set:
        if fp.is_new:
            return self._new_source(fp, rel)

        pristine = self.pristine.get(rel, "")
        # Unknown path under sqlglot/: the pristine tree does not contain this
        # file, so no statement or line lookup is possible. Safe fallback.
        if not pristine:
            return self._full_suite_numbers()

        patched = apply_file_patch(pristine, fp)
        if patched is None:
            return self._full_suite_numbers()

        cat = _classify(pristine, patched)
        if cat == "import_break":
            return self._full_suite_numbers()
        if cat == "comment_only":
            # Source readers and tests with unknown coverage retain their
            # existing signal for textual edits.
            return self._reader_numbers(rel) | self._unknown_loader_numbers(rel)

        # A patch whose hunks do not match the pristine file cannot be applied
        # to the pinned source, so its effect cannot be bounded.
        if not patch_applies(pristine, fp):
            return self._full_suite_numbers()
        # Patched text that is not valid Python breaks the import chain.
        if _safe_parse(patched) is None:
            return self._full_suite_numbers()

        # All operand pairs observed in the complete pristine suite must have
        # agreed under identity/equality, with comparison methods established
        # as safe at profile time. Unknown, custom-rich-comparison and partial
        # profiles retain ordinary selection. Text/loader and process-wide heap
        # observers still see the source or allocation change.
        if (getattr(self, "_operand_isolated_file", False)
                and os.environ.get("BR_OPERANDS", "1") == "1"
                and profiled_noop(self.maps.operand_profiles, rel, pristine, patched)):
            # Every observed evaluation agreed, so the executed code and its
            # allocations are unchanged; a body-only edit cannot reach the
            # heap observers either.
            heap = self._heap_observer_ids
            try:
                if _body_only(ast.parse(pristine), changed_pristine_lines(fp)):
                    heap = set()
            except SyntaxError:
                pass
            return self._reader_numbers(rel) | self._unknown_loader_numbers(rel) | heap

        # CODE_CHANGE. Hunks that are comment/docstring-only on their own
        # (applying just that hunk leaves the AST unchanged) contribute no
        # changed statement; they only reach the source readers.
        code_hunks = [h for h in fp.hunks if not _hunk_is_comment_only(pristine, fp, h)]
        out: set = set()
        if len(code_hunks) < len(fp.hunks):
            out |= self._reader_numbers(rel)
        changed = changed_pristine_lines(_with_hunks(fp, code_hunks))
        tree = None
        if self.maps.has_line_coverage:
            try:
                tree = ast.parse(pristine)
            except Exception:
                tree = None
            if tree:
                for a, b in statement_ranges(tree, changed):
                    for ln in range(a, b + 1):
                        for num in self._line_numbers(rel, ln):
                            if self._debug:
                                self._reasons.append({
                                    "commit": "", "test": num,
                                    "line": f"{rel}:{ln}",
                                    "rule": "statement-range",
                                })
                            out.add(num)

        # Dialect-family rule: sibling files of the same dialect module
        # (generators/parsers/typing/<stem>.py) share the dialect's behavior.
        # Every test that executed any sibling line at the pinned commit is
        # potentially affected.
        fam = self._family_numbers(rel) if self._family else set()
        if fam:
            out |= fam
            if self._debug:
                for num in fam:
                    self._reasons.append({
                        "commit": "", "test": num,
                        "line": rel,
                        "rule": "dialect-family",
                    })

        # Coarse canary: when the precise selection is thin, add the
        # optimizer+executor suites. Safe-mode fallback enabler.
        if self._canary and len(out) < _THIN_CANARY:
            out |= self._opt_executor_numbers()

        heap = self._heap_observer_ids
        if (heap and tree and rel != "sqlglot/time.py" and _body_only(tree, changed)
                and len(out - heap) < _GM_NARROW):
            # The heap observers measure generator construction, which nearly
            # every test runs. A function body that fewer than _GM_NARROW tests
            # execute is not on that path. The labelled function-body edits
            # that broke the observers ran in 54 (time.format_time, which also
            # runs while dialects are built) and 1,533 tests.
            heap = set()
        return out | self._unknown_loader_numbers(rel) | heap

    def _new_source(self, fp: P.FilePatch, rel: str) -> set:
        text = apply_file_patch(None, fp) or ""
        if _safe_parse(text) is None:
            # Unparseable new .py under sqlglot/: the import chain can break.
            return self._full_suite_numbers()
        if rel.startswith("sqlglot/dialects/"):
            return self._testfile_numbers("tests/test_dialect.py") | self._heap_observer_ids
        return set(self._heap_observer_ids)
