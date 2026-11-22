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
    rel = "sqlglot/helper.py"
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
