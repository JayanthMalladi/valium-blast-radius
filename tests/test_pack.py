"""Unit tests for worker packing."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from selector.pack import pack


def test_empty():
    assert pack([], {}) == []


def test_single_worker():
    # small tests: 2000ms worker overhead dominates, so 1 worker wins
    workers = pack([1, 2, 3], {1: 100, 2: 100, 3: 100})
    assert len(workers) == 1
    assert sorted(workers[0]) == [1, 2, 3]

def test_split_saves():
    # large tests where splitting helps: k=2 beats k=1
    workers = pack([1, 2, 3], {1: 1000, 2: 2000, 3: 3000})
    assert len(workers) == 2


def test_two_workers():
    workers = pack([1, 2, 3], {1: 10000, 2: 1000, 3: 1000})
    # heavy test 10000ms on one worker, 1000+1000 on the other; with 2 workers
    assert len(workers) <= 2


def test_k_capped_at_8():
    tests = list(range(30))
    ms = {t: 100 for t in tests}
    workers = pack(tests, ms)
    assert len(workers) <= 8


def test_lpt_balances():
    tests = [1, 2, 3, 4, 5, 6, 7, 8]
    ms = {t: 1000 for t in tests}
    workers = pack(tests, ms)
    for w in workers:
        assert len(w) > 0
