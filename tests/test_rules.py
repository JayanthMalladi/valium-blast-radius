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
