"""Worker packing: minimize busiest-worker recorded seconds + 2 s per worker.

For a selection of test numbers with integer-millisecond durations, choose the
k = 1..8 that minimizes `max(worker load) + 2000*k` ms.

- For small selections (<= 10 tests) the optimum is found exactly by
  enumerating set partitions (restricted growth strings, capped at 8 bins).
- For large selections each k is seeded with longest-processing-time-first
  (LPT) and improved with a local pass (best single move or swap that lowers
  the makespan) until it stops improving.

All arithmetic is in integer milliseconds (the scorer's unit). An empty
selection returns []; a non-empty selection always returns at least one worker
so that its tests are counted (zero-duration tests included) - dropping a
selected test would risk missing a failure.
"""
from __future__ import annotations

# cap local-improvement sweeps; plenty for <=1620 tests, cheap for the k=1..8 loop
_MAX_SWEEPS = 40
# selections up to this size are packed exactly (set-partition enumeration)
_EXACT_MAX = 10


def pack(tests: list[int], durations_ms: dict[int, int]) -> list[list[int]]:
    """Return worker lists for the best k in 1..8 (or [] for empty input)."""
    if not tests:
        return []
    if len(tests) <= _EXACT_MAX:
        return _pack_exact(tests, durations_ms)
    loads = [durations_ms.get(t, 0) for t in tests]
    best: tuple[int, list[list[int]]] | None = None
    for k in range(1, min(8, len(tests)) + 1):
        workers, load = _lpt(loads, tests, k)
        _improve(workers, load, durations_ms, k)
        makespan = max(load) + 2000 * k
        if best is None or makespan < best[0]:
            best = (makespan, [list(w) for w in workers])
    return best[1]


def _pack_exact(tests: list[int], durations_ms: dict[int, int]) -> list[list[int]]:
    """Exact min over k = 1..min(8, n) of makespan + 2000*k, by enumerating the
    set partitions of `tests` (restricted-growth strings capped at 8 bins).
    n is small enough here that the enumeration is cheap."""
    n = len(tests)
    caps = min(8, n)
    d = [durations_ms.get(t, 0) for t in tests]
    best_cost = 10**18
    best_assign: list[int] = []
    assign = [0] * n
    loads = [0] * caps

    def rec(i: int, used: int) -> None:
        nonlocal best_cost, best_assign
        if i == n:
            cost = max(loads[:used]) + 2000 * used
            if cost < best_cost:
                best_cost = cost
                best_assign = assign[:]
            return
        for a in range(used):
            assign[i] = a
            loads[a] += d[i]
            rec(i + 1, used)
            loads[a] -= d[i]
        if used < caps:
            assign[i] = used
            loads[used] += d[i]
            rec(i + 1, used + 1)
            loads[used] -= d[i]

    rec(0, 1)
    used = max(best_assign) + 1 if best_assign else 0
    workers = [[] for _ in range(used)]
    for t, a in zip(tests, best_assign):
        workers[a].append(t)
    return workers


def _lpt(loads: list[int], tests: list[int], k: int) -> tuple[list[list[int]], list[int]]:
    order = sorted(range(len(tests)), key=lambda i: loads[i], reverse=True)
    workers: list[list[int]] = [[] for _ in range(k)]
    load = [0] * k
    for i in order:
        j = load.index(min(load))
        workers[j].append(tests[i])
        load[j] += loads[i]
    return workers, load


def _improve(workers: list[list[int]], load: list[int],
             durations: dict[int, int], k: int) -> None:
    """In-place local improvement: repeatedly apply the single best move or
    swap that strictly lowers the makespan, until no such step remains."""
    if k == 1:
        return
    for _ in range(_MAX_SWEEPS):
        cur = max(load)
        busiest = max(range(k), key=lambda j: load[j])

        best_newmax = cur
        best_move: tuple[int, int] | None = None        # (i in busiest, target j)
        best_swap: tuple[int, int, int] | None = None   # (i in busiest, j, jj in j)

        for i, t in enumerate(workers[busiest]):
            d = durations.get(t, 0)
            for j in range(k):
                if j == busiest:
                    continue
                nm = _newmax(load, busiest, j, -d, d)
                if nm < best_newmax:
                    best_newmax, best_move, best_swap = nm, (i, j), None
        for i, t in enumerate(workers[busiest]):
            d1 = durations.get(t, 0)
            for j in range(k):
                if j == busiest:
                    continue
                for jj, t2 in enumerate(workers[j]):
                    d2 = durations.get(t2, 0)
                    if d2 >= d1:
                        continue
                    nm = _newmax(load, busiest, j, d2 - d1, d1 - d2)
                    if nm < best_newmax:
                        best_newmax, best_move, best_swap = nm, None, (i, j, jj)

        if best_move is not None:
            i, j = best_move
            t = workers[busiest].pop(i)
            workers[j].append(t)
            d = durations.get(t, 0)
            load[busiest] -= d
            load[j] += d
        elif best_swap is not None:
            i, j, jj = best_swap
            t1 = workers[busiest][i]
            t2 = workers[j][jj]
            workers[busiest][i] = t2
            workers[j][jj] = t1
            load[busiest] += durations.get(t2, 0) - durations.get(t1, 0)
            load[j] += durations.get(t1, 0) - durations.get(t2, 0)
        else:
            return


def _newmax(load: list[int], a: int, b: int, delta_a: int, delta_b: int) -> int:
    """Makespan after adding delta_a to load[a] and delta_b to load[b]."""
    m = 0
    for x in range(len(load)):
        v = load[x] + (delta_a if x == a else delta_b if x == b else 0)
        if v > m:
            m = v
    return m
