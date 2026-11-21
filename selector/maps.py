"""Load the blast-radius maps (plain JSON, stdlib only).

Maps are keyed by pytest node id, built from the pinned sqlglot commit.
Files in the maps dir:
  line_coverage.json      rel path -> {str(line): hex_bitset}
  id_order.json           [nodeid,...]   bit i = this node id
  module_importers.json   rel path -> [nodeid,...]
  class_uses.json         "rel::Class" -> [nodeid,...]
  fixture_map.json        "tests/...file" -> [nodeid,...]
  source_readers.json     "sqlglot/...py" -> [nodeid,...]
  test_files.json         "tests/...py" -> [nodeid,...]
"""
from __future__ import annotations
import json
import os

MAPS_DIR = os.environ.get("BR_MAPS", "/app/maps")


class Maps:
    def __init__(self, maps_dir: str = MAPS_DIR):
        self.dir = maps_dir
        self.line_index: dict = {}          # reserved; line data lives in _line_raw
        self._line_raw: dict = {}           # path -> {int(line): int_bitset}
        self._mod_cache: dict = {}
        self.module_importers: dict = {}
        self.class_uses: dict = {}
        self.fixture_map: dict = {}
        self.source_readers: dict = {}
        self.test_files: dict = {}
        self.unknown_loaders: dict = {}
        self.has_line_coverage: bool = False   # set in load()
        self.id_order: list = []
        self._loaded = False

    def load(self) -> None:
        if self._loaded:
            return

        def rd(name: str, default):
            p = os.path.join(self.dir, name)
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    return json.load(f)
            return default

        self.id_order = rd("id_order.json", [])
        lc = rd("line_coverage.json", {})
        # Keep line data as raw bitsets: expanding every line to a node-id
        # list at load time is O(total attributed line-test pairs) (~70M)
        # and blows the 0.3 s load gate. Bitsets decode lazily per lookup.
        for path, lines in lc.items():
            raw = {}
            for ln_s, hexstr in lines.items():
                if not hexstr:
                    continue
                bits = int(hexstr, 16)
                if bits:
                    raw[int(ln_s)] = bits
            if raw:
                self._line_raw[path] = raw
        self.module_importers = rd("module_importers.json", {})
        self.class_uses = rd("class_uses.json", {})
        self.fixture_map = rd("fixture_map.json", {})
        self.source_readers = rd("source_readers.json", {})
        self.test_files = rd("test_files.json", {})
        # unknown_loaders.json is optional (Stream A writes it): rel path ->
        # [nodeid,...] of tests that load files/modules not covered by the
        # other maps. Absent or empty file is a no-op.
        self.unknown_loaders = rd("unknown_loaders.json", {})
        self.has_line_coverage = bool(self._line_raw)
        self._loaded = True

    # -- selectors use these; all return sets of node ids --
    def _decode(self, bits: int) -> list:
        """Node ids covered by a line bitset, in id_order order."""
        order = self.id_order
        out = []
        while bits:
            low = bits & -bits
            out.append(order[low.bit_length() - 1])
            bits ^= low
        return out

    def line_ids(self, path: str, line: int) -> list:
        raw = self._line_raw.get(path, {})
        for ln in (line, line - 1, line + 1):
            bits = raw.get(ln)
            if bits:
                return self._decode(bits)
        return []

    def module_ids(self, rel: str) -> list:
        out = set(self.module_importers.get(rel, []))
        out.update(self.source_readers.get(rel, []))
        cached = self._mod_cache.get(rel)
        if cached is None:
            covered = set()
            for bits in self._line_raw.get(rel, {}).values():
                b = bits
                while b:
                    low = b & -b
                    covered.add(self.id_order[low.bit_length() - 1])
                    b ^= low
            cached = covered
            self._mod_cache[rel] = cached
        out.update(cached)
        return list(out)

    def class_ids(self, rel: str, name: str) -> list:
        return list(self.class_uses.get(f"{rel}::{name}", []))

    def fixture_ids(self, rel: str) -> list:
        return list(self.fixture_map.get(rel, []))

    def testfile_ids(self, rel: str) -> list:
        return list(self.test_files.get(rel, []))

    def reader_ids(self, rel: str) -> list:
        return list(self.source_readers.get(rel, []))

    def unknown_loader_ids(self, rel: str) -> list:
        return list(self.unknown_loaders.get(rel, []))

    def unknown_loaders(self, rel: str) -> list:
        """Node ids of unknown-coverage tests that load `rel`. No-op when
        unknown_loaders.json is absent/empty."""
        return self.unknown_loader_ids(rel)

    def module_fallback_ids(self, rel: str) -> list:
        """Module-level selection: importers | source readers | class-map ids.
        NOTE: module_importers.json is a FIRST-LOADER map (one importer per
        module), not exhaustive. Do NOT use this as a safe stub fallback."""
        out = set(self.module_importers.get(rel, []))
        out.update(self.source_readers.get(rel, []))
        prefix = rel + "::"
        for key, ids in self.class_uses.items():
            if key.startswith(prefix):
                out.update(ids)
        return list(out)

    def all_node_ids(self) -> list:
        """Every node id in id_order (the full test suite). Used only as a
        safe stub-mode fallback when line_coverage.json is empty."""
        return list(self.id_order)
