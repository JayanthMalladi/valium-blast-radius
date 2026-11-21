"""pytest plugin: record, per test, which sqlglot modules it first loads and
which files under the repo it opens.

The audit hook is installed ONCE at session start (there is no
sys.unaudithook), so it is cheap and tags open() events to the currently
running test via a thread-local stack.

Each xdist worker appends JSON lines to $MAPOUT/worker_<id>.jsonl:
  {"type": "load", "test": "<nodeid>", "modules": ["sqlglot.x", ...]}
  {"type": "open", "test": "<nodeid>", "paths": ["tests/fixtures/..."]}

Open paths are normalized to the repo-relative form (tests/... , sqlglot/...)
so they match the paths used in the maps and the selector.

The nodeid (tests/...::Class::method) matches the "id" field of tests.json.
"""
from __future__ import annotations
import json
import os
import sys
import threading

import pytest

_MAPDIR = os.environ.get("MAPOUT", "./mapout")
_tls = threading.local()
_stack: list = []
_installed = False
_repo = ""
_item: dict = {}


def _worker_id() -> str:
    return os.environ.get("PYTEST_XDIST_WORKER", "master")


def _emit(rec: dict) -> None:
    try:
        os.makedirs(_MAPDIR, exist_ok=True)
        with open(os.path.join(_MAPDIR, f"worker_{_worker_id()}.jsonl"),
                  "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


def _rel(path_str: str) -> str:
    """Normalize an open() path to repo-relative form when possible."""
    norm = os.path.normpath(path_str).replace(os.sep, "/")
    if _repo:
        rp = _repo.replace(os.sep, "/")
        if norm.startswith(rp + "/"):
            return norm[len(rp) + 1:]
    return norm


def _audit_hook(event, args):
    if event == "open" and _stack:
        try:
            p = str(args[0])
            rel = _rel(p)
            # only record repo-internal files (tests or sqlglot source)
            if rel.startswith("tests/") or rel.startswith("sqlglot/"):
                _stack[-1].append(rel)
        except Exception:
            pass
    return None


def pytest_configure(config):
    global _installed, _repo
    # the suite runs from the repo root, so the cwd is the sqlglot checkout
    _repo = os.getcwd()
    if not _installed:
        try:
            sys.addaudithook(_audit_hook)
            _installed = True
        except Exception:
            pass


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    _item["nodeid"] = item.nodeid
    _item["opened"] = []
    _item["before_mods"] = set(sys.modules)
    _stack.append(_item["opened"])


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_teardown(item):
    opened = _item.pop("opened", None)
    before = _item.pop("before_mods", None)
    if _stack and _stack[-1] is opened:
        _stack.pop()
    if opened is None:
        return
    nodeid = item.nodeid
    if before is not None:
        new_mods = sorted(set(sys.modules) - before)
        new_mods = [m for m in new_mods if m.startswith("sqlglot")]
        if new_mods:
            _emit({"type": "load", "test": nodeid, "modules": new_mods})
    if opened:
        _emit({"type": "open", "test": nodeid, "paths": sorted(set(opened))})
