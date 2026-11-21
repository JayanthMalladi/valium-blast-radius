"""Decide which tests to run for a commit, using maps from the pinned commit.

All lookups return node ids; the runtime layer maps them to test numbers.
BR_DEBUG=1 writes `work/runs/<run>.reasons.jsonl`:
  one JSON line per commit: {"commit": cid, "reasons": [{"test": <number>, "line": "<module>:<pristine line>", "rule": "<why selected>"}]}
"""
from __future__ import annotations
import ast
import json
import os

from . import patch as P
from .hunkapply import apply_file_patch
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

    def _module_numbers(self, rel: str) -> set:
        return self._ids(self.maps.module_ids(rel))

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
            out = set()
            if rel.endswith(".py") and rel.startswith("sqlglot/"):
                out |= self._module_numbers(rel)
            else:
                out |= self._fixture_numbers(rel)
            return out
        if fp.is_deleted:
            out = self._module_numbers(rel) | self._testfile_numbers(rel)
            if not out and rel.endswith(".py"):
                out = self._module_numbers(rel)
            return out
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
        patched = apply_file_patch(pristine, fp)
        changed = changed_pristine_lines(fp)

        cat = _classify(pristine, patched)
        if cat == "import_break":
            return self._module_numbers(rel)
        if cat == "comment_only":
            return self._reader_numbers(rel) | self._unknown_loader_numbers(rel)

        # CODE_CHANGE
        out = set()
        if self.maps.has_line_coverage and pristine and patched:
            try:
                tree = ast.parse(pristine)
            except Exception:
                tree = None
            if tree:
                ranges = statement_ranges(tree, changed)
                for a, b in ranges:
                    for ln in range(a, b + 1):
                        for num in self._line_numbers(rel, ln):
                            if self._debug:
                                self._reasons.append({
                                    "commit": "", "test": num,
                                    "line": f"{rel}:{ln}",
                                    "rule": "statement-range",
                                })
                            out.add(num)

        # Coarse canary: when line coverage is missing or selection is
        # "thin" (below threshold), add optimizer+executor suites.
        # This is the Section-7 safe-mode fallback enabler.
        if len(out) < _THIN_CANARY:
            out |= self._opt_executor_numbers()

        return out | self._unknown_loader_numbers(rel)

    def _new_source(self, fp: P.FilePatch, rel: str) -> set:
        text = apply_file_patch(None, fp) or ""
        if _safe_parse(text) is None:
            return self._testfile_numbers("tests/test_optimizer.py") | self._testfile_numbers("tests/test_executor.py")
        if rel.startswith("sqlglot/dialects/"):
            return self._testfile_numbers("tests/test_dialect.py")
        return set()
