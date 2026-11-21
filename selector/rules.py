"""Decide which tests to run for a commit, using maps from the pinned commit.

All lookups return node ids; the runtime layer maps them to test numbers.
"""
from __future__ import annotations
import ast

from . import patch as P
from . import scope as S
from .hunkapply import apply_file_patch


class RuleEngine:
    def __init__(self, maps, id_by_node, pristine_files):
        self.maps = maps
        self.id_by_node = id_by_node
        self.pristine = pristine_files

    def select_for_files(self, files: list) -> set:
        sel: set = set()
        for fp in files:
            sel |= self._file(fp)
        return sel

    def _ids(self, ids: list) -> set:
        out = set()
        for nid in ids:
            n = self.id_by_node.get(nid)
            if n is not None:
                out.add(n)
        return out

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

    def _full_suite_numbers(self) -> set:
        # Full-suite fallback: every test number known to the runtime.
        # NOTE: module_importers.json is a FIRST-LOADER map (one importer per
        # module, 86 modules). It is NOT all tests that load the module, so a
        # module-level union is unsafe as a stub fallback and would miss
        # failing tests that are absent from the map. The full suite
        # guarantees 0 misses by construction at the cost of simulated time.
        return {n for n in self.id_by_node.values()}

    def _unknown_loader_numbers(self, rel: str) -> set:
        return self._ids(self.maps.unknown_loader_ids(rel))

    # ------------------------------------------------------------------
    def _file(self, fp: P.FilePatch) -> set:
        rel = fp.path
        if fp.is_binary:
            out = self._fixture_numbers(rel)
            if not out and rel.endswith(".py"):
                out = self._module_numbers(rel)
            return out
        if fp.is_deleted:
            return self._module_numbers(rel) | self._testfile_numbers(rel)
        if rel.startswith("sqlglot/") and rel.endswith(".py"):
            return self._sqlglot(fp, rel)
        if rel.startswith("tests/"):
            if rel.endswith(".py"):
                return self._testfile_numbers(rel)
            if rel.startswith("tests/fixtures/") or rel.endswith((".sql", ".json")):
                out = self._fixture_numbers(rel)
                if not out:
                    out = self._testfile_numbers("tests/test_optimizer.py")
                return out
            return set()
        return set()

    def _sqlglot(self, fp: P.FilePatch, rel: str) -> set:
        if fp.is_new:
            out = self._new_source(fp, rel)
        else:
            pristine = self.pristine.get(rel, "")
            patched = apply_file_patch(pristine, fp) if pristine else apply_file_patch(None, fp)
            changed = self._plus_lines(fp)
            cat, regions = S.classify_file_change(pristine, patched, changed)
            if cat == S.IMPORT_BREAK:
                out = self._module_numbers(rel)
            elif cat == S.COMMENT_ONLY:
                return self._reader_numbers(rel) | self._unknown_loader_numbers(rel)
            else:
                out = set()
                # Fast path: without a complete line_coverage.json the
                # stub-safe behaviour is full-suite by construction.
                if self.maps.has_line_coverage:
                    for region in regions:
                        if region["kind"] == "function":
                            for ln in region["lines"]:
                                out |= self._line_numbers(rel, ln)
                        elif region["kind"] == "class":
                            out |= self._ids(self.maps.class_ids(rel, region["name"]))
                            for ln in region["lines"]:
                                out |= self._line_numbers(rel, ln)
                        else:
                            # module-level region: still try the fallback maps,
                            # but the final step below may upgrade to full suite.
                            out |= self._module_fallback_numbers(rel)
                # A code change must never select nothing (stub mode or when
                # line-level selection resolves to nothing): fall back to the
                # FULL SUITE. module_importers.json is a FIRST-LOADER map and
                # MUST NOT be used as a safe stub fallback.
                if not out:
                    out = self._full_suite_numbers()
        return out | self._unknown_loader_numbers(rel)

    def _new_source(self, fp: P.FilePatch, rel: str) -> set:
        text = apply_file_patch(None, fp) or ""
        parseable = _safe_parse(text) is not None
        scanners = ["tests/test_dialect.py", "tests/test_dialect_imports.py",
                    "tests/test_dialect_entry_points.py", "tests/test_typing.py"]
        out: set = set()
        if not parseable:
            for f in scanners:
                out |= self._testfile_numbers(f)
            return out
        if rel.startswith("sqlglot/dialects/"):
            out |= self._testfile_numbers("tests/test_dialect.py")
        return out

    def _plus_lines(self, fp: P.FilePatch) -> set:
        changed: set = set()
        for hunk in fp.hunks:
            nl = hunk.new_start
            for kind, _ in hunk.lines:
                if kind == "+":
                    changed.add(nl)
                nl += 1
        return changed


def _safe_parse(text: str):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None
