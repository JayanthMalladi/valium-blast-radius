"""Heap observations have dependencies outside instruction coverage."""
import difflib

from selector.maps import Maps
from selector.patch import parse_patch
from selector.rules import RuleEngine, _heap_observers


def test_observers_derived_from_source_and_current_numbering():
    source = """import tracemalloc as tm
from tracemalloc import get_traced_memory as memory
class TestHeap:
    def test_heap(self):
        before = tm.get_traced_memory()
    def test_alias(self):
        before = memory()
    def test_ordinary(self):
        return 1
"""
    ids = {"tests/test_heap.py::TestHeap::test_heap": 93,
           "tests/test_heap.py::TestHeap::test_alias": 17,
           "tests/test_heap.py::TestHeap::test_ordinary": 4}
    assert _heap_observers({"tests/test_heap.py": source}, ids) == {93, 17}
    assert _heap_observers({"sqlglot/helper.py": source}, ids) == set()


def test_semantic_change_keeps_heap_observer_without_line_coverage(tmp_path):
    rel = "sqlglot/dialects/dialect.py"
    source = "def helper():\n    return 1\n"
    tests = "import tracemalloc\ndef test_heap():\n    return tracemalloc.get_traced_memory()\n"
    maps = Maps(str(tmp_path))
    maps.load()
    engine = RuleEngine(maps, {"tests/test_heap.py::test_heap": 77},
                        {rel: source, "tests/test_heap.py": tests})

    def select(patched):
        diff = "".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                            fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        return engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff))

    assert select(source.replace("return 1", "return 2")) == {77}
    # Textual edits cannot change the allocation behavior of executed code.
    assert select(source.replace("return 1", "return 1  # explanation")) == set()


def test_snapshot_observer_and_uncollected_helper():
    source = """import tracemalloc
def observe():
    return tracemalloc.take_snapshot()
def test_heap():
    return tracemalloc.take_snapshot()
"""
    assert _heap_observers({"tests/test_heap.py": source},
                           {"tests/test_heap.py::test_heap": 5}) == {5}


def _heap_engine(tmp_path, rel):
    source = "def helper():\n    return 1\n"
    tests = "import tracemalloc\ndef test_heap():\n    return tracemalloc.get_traced_memory()\n"
    maps = Maps(str(tmp_path))
    maps.load()
    engine = RuleEngine(maps, {"tests/test_heap.py::test_heap": 77},
                        {rel: source, "tests/test_heap.py": tests})
    diff = "".join(difflib.unified_diff(source.splitlines(True),
                                        source.replace("return 1", "return 2").splitlines(True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff))


def test_heap_observer_kept_for_dialect_construction_code(tmp_path):
    assert _heap_engine(tmp_path, "sqlglot/dialects/dialect.py") == {77}


def test_heap_observer_dropped_outside_dialect_construction_code(tmp_path):
    assert _heap_engine(tmp_path, "sqlglot/optimizer/simplify.py") == set()


def _covered_engine(tmp_path, rel, source, patched, covered_lines):
    import json
    (tmp_path / "id_order.json").write_text(json.dumps(["tests/test_x.py::test_x", "tests/test_heap.py::test_heap"]))
    (tmp_path / "line_coverage.json").write_text(json.dumps({rel: {str(ln): "1" for ln in covered_lines}}))
    tests = "import tracemalloc\ndef test_heap():\n    return tracemalloc.get_traced_memory()\n"
    maps = Maps(str(tmp_path))
    maps.load()
    engine = RuleEngine(maps, {"tests/test_x.py::test_x": 0, "tests/test_heap.py::test_heap": 1},
                        {rel: source, "tests/test_heap.py": tests})
    diff = "".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff))


def test_narrow_function_body_edit_drops_heap_observer(tmp_path):
    source = "X = 1\ndef helper():\n    return 1\n"
    patched = source.replace("return 1", "return 2")
    assert _covered_engine(tmp_path, "sqlglot/dialects/dialect.py", source, patched, [1, 2, 3]) == {0}


def test_class_level_edit_and_time_module_keep_heap_observer(tmp_path):
    source = "X = 1\ndef helper():\n    return 1\n"
    assert _covered_engine(tmp_path, "sqlglot/dialects/dialect.py", source,
                           source.replace("X = 1", "X = 2"), [1, 2, 3]) == {0, 1}
    assert _covered_engine(tmp_path, "sqlglot/time.py", source,
                           source.replace("return 1", "return 2"), [1, 2, 3]) == {0, 1}


def test_lambda_interior_edit_drops_heap_observer(tmp_path):
    source = "F = {\n    'a': lambda args: max(\n        args,\n    ),\n}\n"
    patched = source.replace("        args,", "        args[1:],")
    assert _covered_engine(tmp_path, "sqlglot/dialects/dialect.py", source, patched, [1, 2, 3, 4, 5]) == {0}
    # The lambda's first line also holds the dict key, which runs at import.
    header = source.replace("'a': lambda", "'b': lambda")
    assert _covered_engine(tmp_path, "sqlglot/dialects/dialect.py", source, header, [1, 2, 3, 4, 5]) == {0, 1}


def test_lambda_interior_uses_only_lambda_line_coverage(tmp_path):
    import json
    rel = "sqlglot/parsers/demo.py"
    source = "F = {\n    'a': lambda args: max(\n        args,\n    ),\n}\n"
    patched = source.replace("        args,", "        args[1:],")
    ids = ["tests/test_x.py::test_x", "tests/test_y.py::test_y"]
    (tmp_path / "id_order.json").write_text(json.dumps(ids))
    # test_y imported the module (every line of the statement); test_x called the lambda.
    cov = {"1": "2", "2": "3", "3": "1", "4": "2", "5": "2"}
    (tmp_path / "line_coverage.json").write_text(json.dumps({rel: cov}))
    maps = Maps(str(tmp_path))
    maps.load()
    engine = RuleEngine(maps, {i: n for n, i in enumerate(ids)}, {rel: source})
    diff = "".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    assert engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff)) == {0}
    # An immediately called lambda runs at import: the statement rule stays.
    called = source.replace("lambda args: max(\n        args,\n    ),", "(lambda args: max(\n        args,\n    ))(1),")
    engine = RuleEngine(maps, {i: n for n, i in enumerate(ids)}, {rel: called})
    diff = "".join(difflib.unified_diff(called.splitlines(True), called.replace("        args,", "        args[1:],").splitlines(True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    assert engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff)) == {0, 1}
