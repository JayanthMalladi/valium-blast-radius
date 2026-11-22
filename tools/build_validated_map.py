"""Turn tools/record_validated.py output into maps/validated_classes.json.

Usage: python tools/build_validated_map.py <recorded.json> <maps dir>
Class and module fixture scopes are credited to every test in that scope,
using the node ids in <maps dir>/id_order.json. Doctest ids are dropped.
"""
import json
import os
import sys

recorded = json.load(open(sys.argv[1], encoding="utf-8"))
maps_dir = sys.argv[2]
ids = json.load(open(os.path.join(maps_dir, "id_order.json"), encoding="utf-8"))

by_class: dict[str, set[str]] = {}
outside: set[str] = set()
for key, owners in recorded.items():
    if key == "<import>":
        outside |= set(owners)
        continue
    if key.startswith("CLASS:"):
        prefix = key[len("CLASS:"):] + "::"
        tests = [i for i in ids if i.startswith(prefix)]
    elif key.startswith("MODULE:"):
        prefix = key[len("MODULE:"):] + "::"
        tests = [i for i in ids if i.startswith(prefix)]
    elif key.startswith("tests/"):
        tests = [key]
    else:
        continue
    for owner in owners:
        by_class.setdefault(owner, set()).update(tests)

out = {"by_class": {k: sorted(v) for k, v in sorted(by_class.items())},
       "outside": sorted(outside)}
with open(os.path.join(maps_dir, "validated_classes.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, separators=(",", ":"))
print(len(by_class), "classes,", len(outside), "validated outside tests", file=sys.stderr)
