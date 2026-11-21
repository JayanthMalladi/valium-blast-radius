"""Decide which tests to run for a commit, using maps from the pinned commit.

All lookups return node ids; the runtime layer maps them to test numbers.
BR_DEBUG=1 writes `work/runs/<run>.reasons.jsonl`:
  one JSON line per commit: {"commit": cid, "reasons": [{"test": <number>, "line": "<module>:<pristine line>", "rule": "<why selected>"}]}
BR_NO_CANARY=1 disables the coarse optimizer+executor canary (used to measure
the precise line-map + dialect-family rules alone).
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


DATA = os.environ.get("BR_DATA", "/data")
RUN_NAME = os.environ.get("BR_DEBUG_RUN", "debug")
_THIN_CANARY = 50   # fire canary when code-change selection is below this


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


class RuleEngine:
    def __init__(self, maps: Maps, id_by_node: dict[str, int],
                 pristine_files: dict[str, str]) -> None:
        self.maps = maps
        self.id_by_node = id_by_node
        self.pristine = pristine_files
        self._debug = os.environ.get("BR_DEBUG") == "1"
        self._no_canary = os.environ.get("BR_NO_CANARY") == "1"
        self._reasons: list[dict] = []
        self._opt_exec_ids: set[int] | None = None

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

    def _fixture_numbers(self, rel: str) -> set:
        return self._ids(self.maps.fixture_ids(rel))

    def _reader_numbers(self, rel: str) -> set:
        return self._ids(self.maps.reader_ids(rel))

    def _unknown_loader_numbers(self, rel: str) -> set:
        return self._ids(self.maps.unknown_loader_ids(rel))

    # ------------------------------------------------------------------
    def select_for_files(self, files: list) -> set:
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
        if fp.is_binary:
            # A source file replaced by a binary blob cannot be bounded by the
            # maps: any importer can break. Safe fallback: full suite.
            if rel.endswith(".py") and rel.startswith("sqlglot/"):
                return self._full_suite_numbers()
            return set()
        if fp.is_deleted:
            if rel.startswith("sqlglot/") and rel.endswith(".py"):
                return self._full_suite_numbers()
            if rel.startswith("tests/") and rel.endswith(".py"):
                return self._testfile_numbers(rel)
            if rel.startswith("tests/fixtures/") or rel.endswith((".sql", ".json")):
                return self._fixture_numbers(rel) or self._testfile_numbers("tests/test_optimizer.py")
            return set()
        if rel.startswith("tests/"):
            if rel.endswith(".py"):
                return self._testfile_numbers(rel)
            if rel.startswith("tests/fixtures/") or rel.endswith((".sql", ".json")):
                return self._fixture_numbers(rel) or self._testfile_numbers("tests/test_optimizer.py")
            return set()
        if not rel.startswith("sqlglot/") or not rel.endswith(".py"):
            return set()
        return self._sqlglot(fp, rel)

    def _sqlglot(self, fp: P.FilePatch, rel: str) -> set:
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
            return self._reader_numbers(rel) | self._unknown_loader_numbers(rel)

        # A patch whose hunks do not match the pristine file cannot be applied
        # to the pinned source, so its effect cannot be bounded.
        if not patch_applies(pristine, fp):
            return self._full_suite_numbers()
        # Patched text that is not valid Python breaks the import chain.
        if _safe_parse(patched) is None:
            return self._full_suite_numbers()

        # CODE_CHANGE
        changed = changed_pristine_lines(fp)
        out: set = set()
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
        fam = self._family_numbers(rel)
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
        if not self._no_canary and len(out) < _THIN_CANARY:
            out |= self._opt_executor_numbers()

        return out | self._unknown_loader_numbers(rel)

    def _new_source(self, fp: P.FilePatch, rel: str) -> set:
        text = apply_file_patch(None, fp) or ""
        if _safe_parse(text) is None:
            # Unparseable new .py under sqlglot/: the import chain can break.
            return self._full_suite_numbers()
        if rel.startswith("sqlglot/dialects/"):
            return self._testfile_numbers("tests/test_dialect.py")
        return set()
