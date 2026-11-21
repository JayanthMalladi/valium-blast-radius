#!/usr/bin/env python3
"""Build blast-radius maps from the pinned sqlglot commit.

All maps are keyed by the STABLE pytest node id (tests/...::Class::method),
never by a test number: the run container's tests.json may number tests in a
different order than the build's. The selector resolves ids -> numbers at
runtime. Line coverage is stored as compact bitsets (one int per line) over a
stable build-time id order, so the whole map set stays under the 8 MB gate.

argv: SRC  OUT  TESTS_JSON

Env:
  MAP_XDIST   xdist worker count for the coverage run (default 16). Set 0 for
              a single-process run (slower but fewest moving parts).
  MAP_CORES   alias for MAP_XDIST when MAP_XDIST is unset.
"""
from __future__ import annotations
import ast
import collections
import coverage as cov_mod
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

SRC = os.path.abspath(sys.argv[1])
OUT = os.path.abspath(sys.argv[2])
TESTS_JSON = sys.argv[3]
NPROC = int(os.environ.get("MAP_XDIST", os.environ.get("MAP_CORES", "16")))

print(f"[build_maps] src={SRC} out={OUT} nproc={NPROC}", flush=True)
t0 = time.monotonic()
os.makedirs(OUT, exist_ok=True)

tests_data = json.load(open(TESTS_JSON, encoding="utf-8"))["tests"]
# stable id order = the build tests.json order
ID_ORDER = [t["id"] for t in tests_data]
with open(os.path.join(OUT, "id_order.json"), "w") as f:
    json.dump(ID_ORDER, f, separators=(",", ":"))
print(f"[build_maps] {len(ID_ORDER)} numbered tests; id_order written", flush=True)


def nodeid_to_context(nid: str) -> str:
    """pytest nodeid -> coverage test_function context string.

    tests/dialects/test_athena.py::TestAthena::test_athena
      -> tests.dialects.test_athena.TestAthena.test_athena
    tests/test_time.py::test_x
      -> tests.test_time.test_x
    """
    file_part, _, rest = nid.partition("::")
    module = file_part[:-3].replace("/", ".")
    if rest:
        return f"{module}." + rest.replace("::", ".")
    return module


# exact expected context string for every numbered test -> bit index
CTX_INDEX = {nodeid_to_context(nid): i for i, nid in enumerate(ID_ORDER)}

# coverage rcfile (coverage 7.x: `parallel` and `dynamic_context`; the old
# data_parallel/data_context names are gone)
covrc = os.path.join(SRC, ".coveragerc.br")
_rc_lines = [
    "[run]",
    "source = sqlglot",
    "parallel = " + ("True" if NPROC > 0 else "False"),
    "dynamic_context = test_function",
    "branch = false",
    "omit =",
    "    sqlglot/_version.py",
    "    sqlglot/dataframe/*",
]
open(covrc, "w").write("\n".join(_rc_lines) + "\n")

# ---- step 1: run the suite under coverage + the map_plugin -------------
print("[build_maps] step 1: full suite (coverage + plugin)...", flush=True)
mapout = os.path.join(OUT, "_mapout")
if os.path.isdir(mapout):
    shutil.rmtree(mapout)
os.makedirs(mapout)
tools_dir = os.path.dirname(os.path.abspath(__file__))

datafile = os.path.join(SRC, ".coverage")
if os.path.exists(datafile):
    os.remove(datafile)
for pth in pathlib.Path(SRC).glob(".coverage.*"):
    pth.unlink(missing_ok=True)

pytest_args = ["tests", "-q", "-p", "no:cacheprovider",
               "--rootdir=" + SRC, "--import-mode=prepend", "-p", "map_plugin"]
if NPROC > 0:
    pytest_args += ["-n", str(NPROC)]

if NPROC > 0:
    # xdist: use CLI with rcfile + COVERAGE_PROCESS_START for workers
    env = dict(os.environ)
    env["MAPOUT"] = mapout
    env["SKIP_INTEGRATION"] = "0"
    env["PYTHONPATH"] = SRC + os.pathsep + tools_dir
    env["COVERAGE_PROCESS_START"] = covrc
    env.pop("COVERAGE_FILE", None)
    run = [sys.executable, "-m", "coverage", "run", f"--data-file={datafile}",
           f"--rcfile={covrc}", "-m", "pytest"] + pytest_args
    p = subprocess.run(run, cwd=SRC, env=env, capture_output=True, timeout=3600)
    print(f"[build_maps] suite exit={p.returncode} after {time.monotonic()-t0:.0f}s", flush=True)
    print((p.stdout or b"")[-800:].decode(errors="replace"))
    print("--stderr--")
    print((p.stderr or b"")[-800:].decode(errors="replace"))
    p2 = subprocess.run([sys.executable, "-m", "coverage", "combine",
                         f"--data-file={datafile}", f"--rcfile={covrc}"],
                        cwd=SRC, capture_output=True, timeout=600)
    print("[build_maps] combine rc=" + str(p2.returncode)
          + " " + p2.stderr.decode(errors="replace")[-200:], flush=True)
else:
    # single-process: use CLI with rcfile (same mechanism that works in xdist)
    env = dict(os.environ)
    env["MAPOUT"] = mapout
    env["SKIP_INTEGRATION"] = "0"
    env["PYTHONPATH"] = SRC + os.pathsep + tools_dir
    env["COVERAGE_PROCESS_START"] = covrc
    env.pop("COVERAGE_FILE", None)
    run = [sys.executable, "-m", "coverage", "run",
           f"--data-file={datafile}", f"--rcfile={covrc}",
           "-m", "pytest"] + pytest_args
    p = subprocess.run(run, cwd=SRC, env=env, capture_output=True, timeout=3600)
    print(f"[build_maps] suite exit={p.returncode} after {time.monotonic()-t0:.0f}s", flush=True)
    print((p.stdout or b"")[-800:].decode(errors="replace"))
    print("--stderr--")
    print((p.stderr or b"")[-800:].decode(errors="replace"))

# ---- step 2: line coverage -> per-line bitsets --------------------------
print("[build_maps] step 2: line attribution -> bitsets...", flush=True)
line_bits = collections.defaultdict(lambda: collections.defaultdict(int))
cd = cov_mod.CoverageData(basename=datafile)
cd.read()
measured_files = cd.measured_files()
print(f"[build_maps] measured files: {len(measured_files)}", flush=True)

print("[DIAG] measured_contexts sample: " + str(sorted(cd.measured_contexts())[:5]), flush=True)
n_recognized = 0
total_ctx = 0
for fpath in measured_files:
    rel = os.path.relpath(fpath, SRC).replace(os.sep, "/")
    if not rel.startswith("sqlglot/"):
        continue
    cbl = cd.contexts_by_lineno(fpath)
    if not cbl:
        continue
    for ln, ctxs in cbl.items():
        for ctx in ctxs:
            total_ctx += 1
            bi = CTX_INDEX.get(ctx)
            if bi is None:
                continue
            n_recognized += 1
            line_bits[rel][ln] |= 1 << bi
print(f"[build_maps] line_bits: {len(line_bits)} files, "
      f"{sum(len(v) for v in line_bits.values())} attributed lines; "
      f"recognized {n_recognized}/{total_ctx} context hits", flush=True)

# ---- step 3: plugin records (module importers, fixtures, source readers) -
print("[build_maps] step 3: plugin records...", flush=True)
module_importers = collections.defaultdict(set)
fixture_map = collections.defaultdict(set)
source_readers = collections.defaultdict(set)
mod_to_rel = {}
for root, _d, files in os.walk(os.path.join(SRC, "sqlglot")):
    for ff in files:
        if ff.endswith(".py"):
            pth = os.path.join(root, ff)
            rel = os.path.relpath(pth, SRC).replace(os.sep, "/")
            mod_to_rel[rel.replace("/", ".").removesuffix(".py")] = rel
for wf in sorted(pathlib.Path(mapout).glob("worker_*.jsonl")):
    for line in wf.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        nid = rec.get("test", "")
        if not nid:
            continue
        if rec.get("type") == "load":
            for mod in rec.get("modules", []):
                rel = mod_to_rel.get(mod)
                if rel:
                    module_importers[rel].add(nid)
        elif rec.get("type") == "open":
            for path in rec.get("paths", []):
                if path.startswith("tests/fixtures/") or path.endswith((".sql", ".json")):
                    fixture_map[path].add(nid)
                if path.startswith("sqlglot/") and path.endswith(".py"):
                    source_readers[path].add(nid)

# ---- step 4: class usage (which tests executed lines inside each class) -
print("[build_maps] step 4: class usage...", flush=True)
class_uses = collections.defaultdict(set)
for rel, blocks in line_bits.items():
    pth = os.path.join(SRC, rel)
    if not os.path.isfile(pth):
        continue
    try:
        tree = ast.parse(open(pth, encoding="utf-8").read())
    except Exception:
        continue
    class_ranges = [(n.lineno, n.end_lineno, n.name) for n in ast.walk(tree)
                    if isinstance(n, ast.ClassDef) and n.lineno and n.end_lineno]
    for ln, bits in blocks.items():
        for cs, ce, cname in class_ranges:
            if cs <= ln <= ce:
                class_uses[f"{rel}::{cname}"].update(
                    ID_ORDER[i] for i in range(len(ID_ORDER)) if (bits >> i) & 1)
                break

# ---- step 5: test files ---------------------------------------------------
test_files = collections.defaultdict(set)
for t in tests_data:
    test_files[t["file"]].add(t["id"])

# ---- step 6: save ----------------------------------------------------------
def save(name, obj):
    pth = os.path.join(OUT, name)
    with open(pth, "w") as f:
        json.dump({k: sorted(v) for k, v in sorted(obj.items())},
                  f, separators=(",", ":"))
    print(f"[build_maps] {name}: {os.path.getsize(pth)} bytes, {len(obj)} keys",
          flush=True)

lc_serial = {rel: {str(ln): format(bits, "x") for ln, bits in sorted(blocks.items())}
             for rel, blocks in sorted(line_bits.items())}
with open(os.path.join(OUT, "line_coverage.json"), "w") as f:
    json.dump(lc_serial, f, separators=(",", ":"))
print(f"[build_maps] line_coverage.json: "
      f"{os.path.getsize(os.path.join(OUT,'line_coverage.json'))} bytes, "
      f"{len(lc_serial)} files", flush=True)

save("module_importers.json", module_importers)
save("class_uses.json", class_uses)
save("fixture_map.json", fixture_map)
save("source_readers.json", source_readers)
save("test_files.json", test_files)

shutil.rmtree(mapout, ignore_errors=True)
total = sum(os.path.getsize(os.path.join(OUT, n))
            for n in os.listdir(OUT) if n.endswith(".json"))
print(f"[build_maps] DONE in {time.monotonic()-t0:.0f}s; total JSON {total} bytes",
      flush=True)
