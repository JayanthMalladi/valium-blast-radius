"""Worker packing: minimize busiest-worker recorded seconds + 2 s per worker.

For a given selection of test numbers with integer millisecond durations,
try k = 1..8 workers, run longest-processing-time-first (LPT) with a few
improvement swaps, and return the workers list (empty if selection empty)
for the k that minimizes makespan + 2000*k ms.
"""
from __future__ import annotations


def pack(tests: list[int], durations_ms: dict[int, int]) -> list[list[int]]:
    """Return worker lists for the best k in 1..8 (or [] for empty input)."""
    if not tests:
        return []
    loads = [durations_ms.get(t, 0) for t in tests]
    total = sum(loads)
    if total == 0:
        # all selected tests are zero-duration: one worker keeps them counted
        # but costs 2 s; empty selection would cost 0, so drop them.
        return []

    best: tuple[int, list[list[int]]] | None = None
    for k in range(1, 9):
        workers, load = _lpt(loads, tests, k)
        makespan = _improve(workers, load, durations_ms, k) + 2000 * k
        if best is None or makespan < best[0]:
            best = (makespan, [w for w in workers])
    return best[1] if best else []


def _lpt(loads: list[int], tests: list[int], k: int) -> tuple[list[list[int]], list[int]]:
    order = sorted(range(len(tests)), key=lambda i: loads[i], reverse=True)
    workers: list[list[int]] = [[] for _ in range(k)]
    load = [0] * k
    for i in order:
        j = load.index(min(load))
        workers[j].append(tests[i])
        load[j] += loads[i]
    return workers, load


def _improve(workers: list[list[int]], load: list[int], durations: dict[int, int], k: int) -> int:
    """One pass of pair-improvement: move a test from the busiest worker to a
    non-busiest worker if it strictly reduces the makespan. Repeated until no
    improvement. Cheap for <=1620 tests."""
    if k == 1:
        return load[0]
    improved = True
    while improved:
        improved = False
        busiest = max(range(k), key=lambda j: load[j])
        for idx, t in list(enumerate(workers[busiest])):
            d = durations.get(t, 0)
            target = min((j for j in range(k) if j != busiest), key=lambda j: load[j])
            if load[target] + d < load[busiest]:
                workers[busiest].pop(idx)
                load[busiest] -= d
                workers[target].append(t)
                load[target] += d
                improved = True
                busiest = max(range(k), key=lambda j: load[j])
                break
    return load[busiest] if k else 0
