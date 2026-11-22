"""Write maps/narrow_index.json: class bases and f-string pieces of the pinned
sqlglot tree, so the selector need not parse every source file at run time.

Usage: python tools/build_narrow_index.py <sqlglot checkout> <maps dir>
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from selector.narrow import global_facts  # noqa: E402

root, maps_dir = sys.argv[1], sys.argv[2]
sources = {}
for dp, _dn, fn in os.walk(os.path.join(root, "sqlglot")):
    for f in fn:
        if f.endswith(".py"):
            p = os.path.join(dp, f)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            sources[rel] = open(p, encoding="utf-8", errors="replace").read()
bases, fpieces, lpieces = global_facts(sources)
with open(os.path.join(maps_dir, "narrow_index.json"), "w", encoding="utf-8") as f:
    json.dump({"bases": {k: sorted(v) for k, v in sorted(bases.items())},
               "fstring_pieces": sorted(fpieces), "lookup_pieces": sorted(lpieces)},
              f, separators=(",", ":"))
print(len(sources), "files,", len(bases), "classes", file=sys.stderr)
