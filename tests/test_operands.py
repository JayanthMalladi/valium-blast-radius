import difflib
import enum
import hashlib
import json
import sys
from pathlib import Path

from selector.maps import Maps
from selector.operands import comparison_swap, profiled_noop
from selector.patch import parse_patch
from selector.rules import RuleEngine

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from operand_profile import RECORDS, compare, eligible


def profile(source, rel="sqlglot/example.py"):
    site = comparison_swap(source, source.replace(" is None", " == None"))
    return {"version": 1, "complete": True, "verification_context": {"unittest": True, "pytest": True, "core_unittest": True}, "source_sha256": {rel: hashlib.sha256(source.encode()).hexdigest()},
            "sites": {f"{rel}:{site.lineno}:{site.col_offset}": {"pairs": [["builtins.int", "builtins.NoneType"]]}}}


def test_none_positive_and_normal_enum():
    assert eligible(None, 1)
    assert eligible([], None)
    assert eligible(object(), None)

    class Standard(str, enum.Enum):
        A = "A"
        B = "B"

    assert eligible(Standard.A, Standard.B)
    source = "def f(x):\n    return x is None\n"
    assert profiled_noop(profile(source), "sqlglot/example.py", source, source.replace(" is ", " == "))


def test_expression_and_wrappers_never_probed():
    class Expression:
        def __eq__(self, other):
            raise AssertionError("custom equality was probed")

    class Wrapper:
        def __ne__(self, other):
            raise AssertionError("custom inequality was probed")

    for operand in (Expression(), Wrapper()):
        assert not eligible(operand, None)
        assert compare("negative-site", "Is", operand, None) is False
    assert RECORDS["negative-site"]["safe"] is False


def test_custom_enum_and_builtin_subclass_excluded():
    class Custom(str, enum.Enum):
        A = "A"

        def __eq__(self, other):
            raise AssertionError("custom enum equality was probed")

    class WrappedInt(int):
        def __eq__(self, other):
            raise AssertionError("builtin subclass equality was probed")

    assert not eligible(Custom.A, Custom.A)
    assert not eligible(WrappedInt(2), None)


def test_original_custom_comparison_result_and_exception_preserved():
    import pytest
    marker = object()
    calls = []

    class Custom:
        def __eq__(self, other):
            calls.append(other)
            return marker

    assert compare("custom-result", "Eq", Custom(), None) is marker
    assert calls == [None]
    assert not RECORDS["custom-result"]["safe"]

    class Raises:
        def __eq__(self, other):
            raise RuntimeError("expected")

    with pytest.raises(RuntimeError, match="expected"):
        compare("custom-raises", "Eq", Raises(), None)
    assert not RECORDS["custom-raises"]["safe"]


def test_real_expression_excluded():
    import pytest
    sqlglot = pytest.importorskip("sqlglot")
    assert not eligible(sqlglot.exp.Literal.number(1), None)


def test_context_polarity_chains_and_partial_profiles_retain():
    source = "def f(x):\n    return x is None\n"
    data = profile(source)
    for patched in (source.replace(" is ", " != "), source.replace("x is", "y =="),
                    source.replace("x is None", "x == None == None"),
                    source.replace("x is None", "x == None").replace("def f", "def g")):
        assert not profiled_noop(data, "sqlglot/example.py", source, patched)
    assert not profiled_noop({}, "sqlglot/example.py", source, source.replace(" is ", " == "))
    legacy = dict(data)
    del legacy["verification_context"]
    assert not profiled_noop(legacy, "sqlglot/example.py", source, source.replace(" is ", " == "))
    partial = dict(data, complete=False)
    assert not profiled_noop(partial, "sqlglot/example.py", source, source.replace(" is ", " == "))
    assert not profiled_noop(data, "sqlglot/example.py", source + "\n", source.replace(" is ", " == "))
    data["sites"].clear()
    assert not profiled_noop(data, "sqlglot/example.py", source, source.replace(" is ", " == "))
    assert comparison_swap("a is not None", "a != None") is not None
    assert comparison_swap("a == None", "a is None") is not None
    assert comparison_swap("a is None; b is None", "a == None; b == None") is None


def test_preserves_reader_and_unknown_observers(tmp_path):
    rel = "sqlglot/example.py"
    source = "def f(x):\n    return x is None\n"
    (tmp_path / "operand_profiles.json").write_text(json.dumps(profile(source)))
    maps = Maps(str(tmp_path))
    maps.load()
    maps.source_readers = {rel: ["reader"]}
    maps.unknown_loaders = {rel: ["unknown"]}
    maps.id_order = ["ordinary"]
    maps.has_line_coverage = True
    maps._line_raw = {rel: {2: 1}}
    heap = "import tracemalloc\ndef test_heap():\n    tracemalloc.get_traced_memory()\n"
    engine = RuleEngine(maps, {"ordinary": 1, "reader": 2, "unknown": 3,
                              "tests/test_heap.py::test_heap": 4},
                        {rel: source, "tests/test_heap.py": heap})
    patched = source.replace(" is ", " == ")
    diff = "".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                       fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    patch = parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff)
    # Every observed evaluation agreed and the edit is inside a function
    # body, so the executed code is unchanged: the heap observer is dropped.
    assert engine.select_for_files(patch) == {2, 3}
    other = parse_patch("diff --git a/README.md b/README.md\n--- a/README.md\n+++ b/README.md\n@@ -1 +1 @@\n-old\n+new\n")
    assert 1 in engine.select_for_files(patch + other)


def test_actual_profile_fork_child_has_unittest_semantics(tmp_path):
    import multiprocessing
    import os

    import pytest
    if not hasattr(os, "fork"):
        pytest.skip("POSIX profile child")
    ctx = multiprocessing.get_context("fork")
    parent, child = ctx.Pipe(duplex=False)
    def verify(conn):
        try:
            import unittest

            import operand_profile as profiler
            import pytest
            root = Path(__file__).resolve().parents[2] / "work/sqlglot"
            sys.path.insert(0, str(root))
            for name in list(sys.modules):
                if name == "sqlglot" or name.startswith("sqlglot."):
                    del sys.modules[name]
            os.environ["BR_OPERAND_SOURCE"] = str(root)
            os.environ["BR_OPERAND_OUTPUT"] = str(tmp_path)
            profiler.RECORDS.clear()
            profiler.VALIDATED = False
            profiler.install()
            from sqlglot.expressions import core
            assert core.UNITTEST is True
            assert "unittest" in sys.modules and "pytest" in sys.modules
            assert unittest.TestCase and pytest.main
            assert profiler.VALIDATED is True
            marker = tmp_path / f"validated-{os.getpid()}.json"
            assert json.loads(marker.read_text())["core_unittest"] is True
            conn.send(True)
        except BaseException as exc:  # noqa: BLE001 - surface all isolated-child failures
            conn.send(repr(exc))
        finally:
            conn.close()
    process = ctx.Process(target=verify, args=(child,))
    process.start()
    child.close()
    try:
        assert parent.poll(15), "profile child failed to finish"
        assert parent.recv() is True
    finally:
        process.join(1)
        if process.is_alive():
            process.kill()
            process.join()
        parent.close()
    assert process.exitcode == 0


def test_profile_install_rejects_stale_sqlglot(monkeypatch):
    from types import SimpleNamespace

    import operand_profile as profiler
    import pytest
    monkeypatch.setitem(sys.modules, "sqlglot", SimpleNamespace(stale=True))
    with pytest.raises(RuntimeError, match="stale preloaded"):
        profiler.install()
