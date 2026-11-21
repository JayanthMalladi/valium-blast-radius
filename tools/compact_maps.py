"""Compact the maps: drop empty entries, sort keys, strip coverage noise.

Usage: python compact_maps.py <maps_dir>
"""
from __future__ import annotations
import json
import os
import sys

def main():
    d = sys.argv[1]
    for name in ["module_importers.json", "fixture_map.json", "test_files.json",
                 "docstring_tests.json", "class_uses.json", "line_coverage.json"]:
        p = os.path.join(d, name)
        if not os.path.exists(p):
            continue
        obj = json.load(open(p))
        # drop keys with empty values
        cleaned = {k: v for k, v in obj.items() if v}
        if isinstance(cleaned, dict):
            cleaned = {k: cleaned[k] for k in sorted(cleaned)}
        with open(p, "w") as f:
            json.dump(cleaned, f, separators=(",", ":"))
        size = os.path.getsize(p)
        print(f"[compact] {name}: {size} bytes ({len(cleaned)} keys)")

    # print total maps size
    total = sum(os.path.getsize(os.path.join(d, n))
                for n in os.listdir(d) if n.endswith(".json"))
    print(f"[compact] total JSON maps: {total} bytes")

if __name__ == "__main__":
    main()
