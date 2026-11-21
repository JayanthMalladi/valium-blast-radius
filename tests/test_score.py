"""Tests for the local score/eval utilities."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.eval import evaluate


SAMPLE_TESTS = [{"number": i, "id": f"t{i}", "file": f"tests/f{i}.py", "seconds": 0.1 * (i % 10 + 1)}
                 for i in range(5)]
SAMPLE_ANSWERS = {
    "c1": {"failing": [1], "kind": "code"},
    "c2": {"failing": [3, 4], "kind": "fixture"},
    "c3": {"failing": [], "kind": "comment"},
}


def test_perfect_hit():
    stdout = json.dumps({"commit": "c1", "workers": [[1]]}) + "\n"
    res = evaluate(SAMPLE_TESTS, SAMPLE_ANSWERS, stdout)
    assert res["simulated_s"] > 0
    assert "c1" not in res["misses"]


def test_miss_penalty():
    stdout = json.dumps({"commit": "c1", "workers": [[]]}) + "\n"
    res = evaluate(SAMPLE_TESTS, SAMPLE_ANSWERS, stdout)
    assert "c1" in res["misses"]
    assert 300 <= res["simulated_s"] <= 310
