"""Integration test: selector on the sample dir produces valid JSONL."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_select_on_sample_dir():
    """Run the selector on a sample dir; every line must be valid and
    every commit answered."""
    sample = os.environ.get("BR_TEST_SAMPLE")
    if not sample:
        return
    sys.path.insert(0, str(Path(sample)))
    import selector.main as M
    import io
    out = io.StringIO()
    sys.stdout = out
    M.main()
    sys.stdout = sys.__stdout__
    lines = [ln for ln in out.getvalue().strip().split("\n") if ln]
    for line in lines:
        obj = json.loads(line)
        assert "commit" in obj and "workers" in obj
        assert isinstance(obj["workers"], list)
        for w in obj["workers"]:
            for x in w:
                assert isinstance(x, int) and x >= 0


def _const_engine(tmp_path, source, patched, reader):
    import difflib, json
    from selector.maps import Maps
    from selector.patch import parse_patch
    from selector.rules import RuleEngine
    rel = "sqlglot/dialects/demo.py"
    ids = ["tests/test_a.py::T::test_a", "tests/test_b.py::T::test_b"]
    (tmp_path / "id_order.json").write_text(json.dumps(ids))
    lines = {str(i): "3" for i in range(1, len(source.splitlines()) + 1)}
    lines[str(reader)] = "1"
    (tmp_path / "line_coverage.json").write_text(json.dumps({rel: lines}))
    maps = Maps(str(tmp_path))
    maps.load()
    engine = RuleEngine(maps, {i: n for n, i in enumerate(ids)}, {rel: source})
    diff = "".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff))


def test_constant_read_only_in_function_body_narrows(tmp_path):
    source = "class D:\n    WEEK_OFFSET = 1\n    def f(self):\n        return self.WEEK_OFFSET\n"
    patched = source.replace("WEEK_OFFSET = 1", "WEEK_OFFSET = 2")
    assert _const_engine(tmp_path, source, patched, reader=4) == {0}


def test_constant_read_at_import_time_keeps_statement_rule(tmp_path):
    source = "class D:\n    WEEK_OFFSET = 1\n    OTHER = WEEK_OFFSET + 1\n    def f(self):\n        return self.WEEK_OFFSET\n"
    patched = source.replace("WEEK_OFFSET = 1", "WEEK_OFFSET = 2")
    assert _const_engine(tmp_path, source, patched, reader=5) == {0, 1}


def _flip_engine(tmp_path, validated):
    import difflib, json
    from selector.maps import Maps
    from selector.patch import parse_patch
    from selector.rules import RuleEngine
    rel = "sqlglot/expressions/demo.py"
    source = 'class Expression:\n    pass\n\n\nclass Trig(Expression):\n    arg_types = {"this": True, "when": False}\n'
    ids = ["tests/test_a.py::T::test_a", "tests/test_b.py::T::test_b"]
    (tmp_path / "id_order.json").write_text(json.dumps(ids))
    (tmp_path / "line_coverage.json").write_text(json.dumps({rel: {str(i): "3" for i in range(1, 7)}}))
    (tmp_path / "validated_classes.json").write_text(json.dumps(validated))
    maps = Maps(str(tmp_path))
    maps.load()
    engine = RuleEngine(maps, {i: n for n, i in enumerate(ids)}, {rel: source})
    patched = source.replace('"when": False', '"when": True')
    diff = "".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    return engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff))


def test_arg_types_flip_selects_tests_that_validated_the_class(tmp_path):
    validated = {"by_class": {"Trig": ["tests/test_b.py::T::test_b"]}, "outside": []}
    assert _flip_engine(tmp_path, validated) == {1}


def test_arg_types_flip_validated_at_import_keeps_statement_rule(tmp_path):
    validated = {"by_class": {"Trig": ["tests/test_b.py::T::test_b"]}, "outside": ["Trig"]}
    assert _flip_engine(tmp_path, validated) == {0, 1}


def test_constant_read_through_unrelated_class_self_is_ignored(tmp_path):
    source = ("class Gen:\n    HINTS = False\n    def f(self):\n        return self.HINTS\n\n\n"
              "class Par:\n    HINTS = set()\n    def g(self):\n        return self.HINTS\n")
    patched = source.replace("HINTS = False", "HINTS = True")
    import difflib, json
    from selector.maps import Maps
    from selector.patch import parse_patch
    from selector.rules import RuleEngine
    rel = "sqlglot/generators/demo.py"
    ids = ["tests/test_a.py::T::test_a", "tests/test_b.py::T::test_b"]
    (tmp_path / "id_order.json").write_text(json.dumps(ids))
    cov = {str(i): "3" for i in range(1, 11)}
    cov["4"], cov["10"] = "1", "2"
    (tmp_path / "line_coverage.json").write_text(json.dumps({rel: cov}))
    maps = Maps(str(tmp_path))
    maps.load()
    engine = RuleEngine(maps, {i: n for n, i in enumerate(ids)}, {rel: source})
    diff = "".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                        fromfile=f"a/{rel}", tofile=f"b/{rel}"))
    assert engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff)) == {0}


def test_constant_read_through_self_is_bounded_by_instance_map(tmp_path):
    import difflib, json
    from selector.maps import Maps
    from selector.patch import parse_patch
    from selector.rules import RuleEngine
    rel = "sqlglot/generators/demo.py"
    source = ("class Gen:\n    HINTS = False\n    def f(self):\n        return self.HINTS\n\n\n"
              "class DemoGen(Gen):\n    HINTS = False\n")
    patched = source.replace("class DemoGen(Gen):\n    HINTS = False", "class DemoGen(Gen):\n    HINTS = True")
    ids = ["tests/test_a.py::T::test_a", "tests/test_b.py::T::test_b"]
    (tmp_path / "id_order.json").write_text(json.dumps(ids))
    cov = {str(i): "3" for i in range(1, 9)}
    (tmp_path / "line_coverage.json").write_text(json.dumps({rel: cov}))
    inst = {"by_class": {"sqlglot.generators.demo.DemoGen": ["tests/test_b.py::T::test_b"],
                         "sqlglot.generators.demo.Gen": ids}, "outside": []}
    (tmp_path / "instance_classes.json").write_text(json.dumps(inst))
    maps = Maps(str(tmp_path))
    maps.load()

    def select():
        engine = RuleEngine(maps, {i: n for n, i in enumerate(ids)}, {rel: source})
        diff = "".join(difflib.unified_diff(source.splitlines(True), patched.splitlines(True),
                                            fromfile=f"a/{rel}", tofile=f"b/{rel}"))
        return engine.select_for_files(parse_patch(f"diff --git a/{rel} b/{rel}\n" + diff))

    assert select() == {1}
    # An instance created outside any test removes the bound.
    inst["outside"] = ["sqlglot.generators.demo.DemoGen"]
    (tmp_path / "instance_classes.json").write_text(json.dumps(inst))
    assert select() == {0, 1}


def test_subprocess_tests_are_found():
    from selector.rules import _subprocess_tests
    src = ("import subprocess\nclass T:\n    def test_a(self):\n        subprocess.run(['python'])\n"
           "    def test_b(self):\n        return 1\n")
    assert _subprocess_tests({"tests/test_x.py": src}) == {"tests/test_x.py::T::test_a"}


def test_tpcds_probe_skipped_without_digest_or_for_executor_code(tmp_path):
    import json
    from selector.maps import Maps
    from selector.patch import parse_patch
    from selector.rules import RuleEngine
    ids = ["tests/test_executor.py::TestExecutor::test_execute_tpcds"]
    (tmp_path / "id_order.json").write_text(json.dumps(ids))
    maps = Maps(str(tmp_path))
    maps.load()
    rel = "sqlglot/executor/python.py"
    engine = RuleEngine(maps, {ids[0]: 0}, {rel: "def f():\n    return 1\n"})
    patch = parse_patch(f"diff --git a/{rel} b/{rel}\n--- a/{rel}\n+++ b/{rel}\n"
                        "@@ -1,2 +1,2 @@\n def f():\n-    return 1\n+    return 2\n")
    assert engine._tpcds_unchanged(patch) is False  # no digest
    engine._tpcds_digest = {"x": "y"}
    assert engine._tpcds_unchanged(patch) is False  # executor code is never probed
