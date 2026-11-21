"""Unit tests for worker packing (fix 4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector.pack import pack


def _cost(workers: list[list[int]], durations: dict[int, int]) -> int:
    occupied = [w for w in workers if w]
    if not occupied:
        return 0
    return max(sum(durations[t] for t in w) for w in occupied) + 2_000 * len(occupied)


def _brute_cost(tests: list[int], durations: dict[int, int]) -> tuple[int, list[list[int]]]:
    """Exhaustive optimum over all set partitions (restricted growth strings)."""
    n = len(tests)
    if n == 0:
        return 0, []
    best_cost = 10**18
    best_workers: list[list[int]] = []
    assign = [0] * n

    def rec(i: int, used: int) -> None:
        nonlocal best_cost, best_workers
        if i == n:
            workers: list[list[int]] = [[] for _ in range(used)]
            for t, a in zip(tests, assign):
                workers[a].append(t)
            c = _cost(workers, durations)
            if c < best_cost:
                best_cost = c
                best_workers = workers
            return
        for a in range(used + 1):
            assign[i] = a
            rec(i + 1, max(used, a + 1))

    rec(0, 0)
    return best_cost, best_workers


def test_single_worker_wins_when_cost_dominates():
    workers = pack([1, 2, 3], {1: 100, 2: 100, 3: 100})
    assert len(workers) == 1
    assert sorted(workers[0]) == [1, 2, 3]


def test_split_saves_for_large_tests():
    workers = pack([1, 2, 3], {1: 1000, 2: 2000, 3: 3000})
    assert len(workers) == 2


def test_empty_selection():
    assert pack([], {}) == []


def test_k_capped_at_8():
    workers = pack(list(range(30)), {t: 100 for t in range(30)})
    assert len(workers) <= 8


def test_bruteforce_matches_up_to_8():
    for n in range(1, 9):
        tests = list(range(n))
        durations = {t: (t * 137 + 1) % 5000 + 1 for t in tests}
        best_cost, _ = _brute_cost(tests, durations)
        workers = pack(tests, durations)
        assert _cost(workers, durations) == best_cost, (n, workers, best_cost)


def test_full_suite_is_reasonable():
    durations = {
        1082: 1364,
        1106: 21454,
        1295: 1963,
    }
    workers = pack([1082, 1106, 1295], durations)
    assert _cost(workers, durations) <= 36817
