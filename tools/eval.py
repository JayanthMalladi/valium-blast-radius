"""Score a selector output against any labels file with score.py's exact rules.

Usage:
    python tools/eval.py <tests.json> <answers.json> <selector_output.jsonl>
or, with a labels file of shape {commit: {"failing": [...], "kind": ...}}.

Prints: simulated seconds, misses (commit + missed tests), seconds over floor
per commit, total. Exits 0 if no misses, 1 otherwise.
"""
from __future__ import annotations
import json
import math
import sys

WORKER_MS = 2000
MISS_MS = 300_000


def _duration_ms(seconds: float) -> int:
    return math.floor(seconds * 1000 + 0.5)


def _split(text: str) -> list[str]:
    pieces = text.split("\n")
    if text.endswith("\n"):
        pieces.pop()
    return pieces


def evaluate(tests: list[dict], answers: dict, stdout_text: str) -> dict:
    dur = {t["number"]: _duration_ms(t["seconds"]) for t in tests}
    failing = {cid: set(v.get("failing", [])) for cid, v in answers.items()}
    per_commit: dict[str, int] = {}
    misses: dict[str, list[int]] = {}
    for line in _split(stdout_text):
        obj = json.loads(line)
        cid = obj["commit"]
        workers = [w for w in obj["workers"] if w]
        cost = 0
        if workers:
            loads = [sum(dur[t] for t in w) for w in workers]
            cost = max(loads) + WORKER_MS * len(workers)
        per_commit[cid] = cost
        missed = failing.get(cid, set()) - {t for w in workers for t in w}
        if missed:
            misses[cid] = sorted(missed)
    missing_commits = sorted(set(answers) - set(per_commit))
    # Kit scorer rejects a run with missing commits; it does NOT add a
    # 300s penalty for them. Only answered-but-missed commits carry the penalty.
    simulated_ms = sum(per_commit.values()) + MISS_MS * len(misses)
    return {
        "simulated_s": simulated_ms / 1000.0,
        "misses": misses,
        "missing_commits": missing_commits,
        "per_commit_s": {c: v / 1000.0 for c, v in sorted(per_commit.items())},
    }


def main() -> None:
    tests_json, answers_json, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    tests = json.load(open(tests_json))["tests"]
    answers = json.load(open(answers_json))["commits"]
    result = evaluate(tests, answers, open(out_path, encoding="utf-8").read())
    print(f"Simulated: {result['simulated_s']:.3f} s")
    print(f"Misses:    {len(result['misses'])} (commits: {list(result['misses'])[:10]})")
    for cid, nums in result["misses"].items():
        print(f"  {cid}: missed {nums[:10]}")
    for cid in result["missing_commits"]:
        print(f"  MISSING COMMIT {cid}")
    # floor: 1 worker carrying exactly the failing tests
    dur_of = {t["number"]: _duration_ms(t["seconds"]) for t in tests}
    floor_ms = 0
    for cid, v in answers.items():
        fs = v.get("failing", [])
        if fs:
            floor_ms += max(dur_of[n] for n in fs) + WORKER_MS
    print(f"Floor:     {floor_ms/1000:.3f} s (exact-failing, 1 worker)")
    sys.exit(1 if (result["misses"] or result["missing_commits"]) else 0)


if __name__ == "__main__":
    main()
