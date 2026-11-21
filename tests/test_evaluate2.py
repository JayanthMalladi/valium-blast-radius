"""Tests for work/tools/evaluate2.py (submit-2 evaluator)."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "work" / "tools"))

import evaluate2  # noqa: E402

# tiny synthetic data set
TESTS = [
    {"number": 0, "id": "t0", "file": "tests/f0.py", "seconds": 0.1},
    {"number": 1, "id": "t1", "file": "tests/f1.py", "seconds": 0.2},
    {"number": 2, "id": "t2", "file": "tests/f2.py", "seconds": 0.3},
    {"number": 3, "id": "t3", "file": "tests/f3.py", "seconds": 0.4},
    {"number": 4, "id": "t4", "file": "tests/f4.py", "seconds": 0.5},
    {"number": 7, "id": "t7", "file": "tests/f7.py", "seconds": 1.5},
]
ANSWERS = {"c1": {"failing": [1, 4]}, "c2": {"failing": []}}
RUN_OK = '{"commit": "c1", "workers": [[1, 4]]}\n{"commit": "c2", "workers": []}\n'
RUN_MISS = '{"commit": "c1", "workers": [[]]}\n{"commit": "c2", "workers": []}\n'
RUN_OVER_FLOOR = '{"commit": "c1", "workers": [[0, 1, 4]]}\n{"commit": "c2", "workers": []}\n'
RUN_SLOW = '{"commit": "c1", "workers": [[7, 1, 4]]}\n{"commit": "c2", "workers": []}\n'
REASONS = '{"commit": "c1", "reasons": [{"test": 7, "line": "sqlglot/x.py:10", "rule": "line_coverage"}]}\n'


def test_perfect_run():
    res = evaluate2.evaluate(TESTS, ANSWERS, RUN_OK)
    assert res["simulated_ms"] == 2700
    assert res["misses"] == {}
    c = res["per_commit"]["c1"]
    assert c["cost_ms"] == 2700
    assert c["floor_ms"] == 2700
    assert c["over_floor_ms"] == 0


def test_miss_penalty():
    res = evaluate2.evaluate(TESTS, ANSWERS, RUN_MISS)
    assert res["misses"]["c1"] == [1, 4]
    assert res["simulated_ms"] == 300_000
    assert res["per_commit"]["c1"]["cost_ms"] == 0


def test_floor_vs_cost():
    res = evaluate2.evaluate(TESTS, ANSWERS, RUN_OVER_FLOOR)
    c = res["per_commit"]["c1"]
    assert c["cost_ms"] == 2800
    assert c["floor_ms"] == 2700
    assert c["over_floor_ms"] == 100
    assert abs(res["seconds_over_floor_s"] - 0.1) < 1e-9


def test_slow_test_default_reason():
    res = evaluate2.evaluate(TESTS, ANSWERS, RUN_SLOW)
    assert len(res["slow_tests"]) == 1
    assert res["slow_tests"][0]["test"] == 7
    assert res["slow_tests"][0]["commit"] == "c1"
    assert res["slow_tests"][0]["reason"] == "unknown"


def test_slow_test_with_reasons():
    res = evaluate2.evaluate(TESTS, ANSWERS, RUN_SLOW, reasons_text=REASONS)
    assert res["slow_tests"][0]["reason"] == "line_coverage @ sqlglot/x.py:10"


def test_compare_mode():
    run1 = '{"commit": "c1", "workers": [[1, 4, 7]]}\n{"commit": "c2", "workers": []}\n'
    run2 = '{"commit": "c1", "workers": [[1, 4]]}\n{"commit": "c2", "workers": []}\n'
    cmp = evaluate2.compare(TESTS, ANSWERS, run1, run2)
    assert cmp["run1_total_ms"] == 4200
    assert cmp["run2_total_ms"] == 2700
    assert cmp["total_delta_ms"] == -1500
    assert cmp["slow_moved_out"] == [("c1", 7)]
    assert cmp["slow_moved_in"] == []
