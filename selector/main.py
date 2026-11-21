"""Blast-radius selector entry point.

Reads /data (patches + tests.json), prints one JSON line per commit on
stdout, logs to stderr, and falls back to the full suite on any internal
error - one bad patch must never reject the run.

Stdlib only. Maps (plain JSON, keyed by pytest node id) are read once at
startup and kept in memory; the whole batch stays well under the CPU budget.
"""
from __future__ import annotations
import json
import os
import sys
import time

from . import patch as P
from .maps import Maps
from .pack import pack
from .rules import RuleEngine

DATA = os.environ.get("BR_DATA", "/data")
MAPS_DIR = os.environ.get("BR_MAPS", "/app/maps")
PRISTINE_DIR = os.environ.get("BR_PRISTINE", "/opt/sqlglot")
RUN_NAME = os.environ.get("BR_DEBUG_RUN", "debug")


def _pristine_files() -> dict:
    out = {}
    for sub in ("sqlglot", "tests"):
        root = os.path.join(PRISTINE_DIR, sub)
        if not os.path.isdir(root):
            continue
        for dp, _dn, fn in os.walk(root):
            for f in fn:
                if f.endswith(".py"):
                    p = os.path.join(dp, f)
                    rel = os.path.relpath(p, PRISTINE_DIR).replace(os.sep, "/")
                    try:
                        out[rel] = open(p, encoding="utf-8", errors="replace").read()
                    except OSError:
                        pass
    return out


def main() -> None:
    t0 = time.monotonic()
    tests = json.load(open(os.path.join(DATA, "tests.json"), encoding="utf-8"))["tests"]
    durations_ms = {t["number"]: int(round(t["seconds"] * 1000 + 1e-9)) for t in tests}
    id_by_node = {t["id"]: t["number"] for t in tests}
    numbers = [t["number"] for t in tests]

    maps = Maps(MAPS_DIR)
    maps.load()
    engine = RuleEngine(maps, id_by_node, _pristine_files())

    full_workers = pack(sorted(numbers, key=lambda n: -durations_ms[n]), durations_ms)

    commits_dir = os.path.join(DATA, "commits")
    for cid in sorted(f[:-6] for f in os.listdir(commits_dir) if f.endswith(".patch")):
        try:
            text = open(os.path.join(commits_dir, cid + ".patch"),
                        encoding="utf-8", errors="replace").read()
            files = P.parse_patch(text)
            sel = engine.select_for_files(files)
            if not sel:
                workers = []
            else:
                workers = pack(list(sel), durations_ms)
        except Exception as exc:
            sys.stderr.write(f"[{cid}] selector error {exc!r}; full-suite fallback\n")
            workers = full_workers
        engine.record_reasons(cid, set(n for w in workers for n in w))
        print(json.dumps({"commit": cid, "workers": workers}))

    ts = os.times()
    sys.stderr.write(f"[selector] done in {time.monotonic() - t0:.3f}s; cpu_seconds={ts.user + ts.system:.6f}\n")


if __name__ == "__main__":
    main()
