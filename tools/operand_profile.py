"""Profile comparison operands on the pinned pristine suite; no patch inputs.

Usage: python tools/operand_profile.py SOURCE OUTPUT
Run with the pinned test dependencies installed. Child interpreters install the
same compile hook through a generated sitecustomize, including spawn workers.
"""
from __future__ import annotations

import ast
import atexit
import enum
import gzip
import hashlib
import importlib.abc
import importlib.machinery
import json
import operator
import os
import subprocess
import sys
import tempfile
import time
import unittest  # noqa: F401 - SQLGlot inspects sys.modules at import time
from pathlib import Path

import pytest  # noqa: F401 - profiling must preserve pytest validation context

OPS = {"Is": operator.is_, "IsNot": operator.is_not, "Eq": operator.eq, "NotEq": operator.ne}
BUILTINS = {type(None), bool, int, float, complex, str, bytes, bytearray,
            list, tuple, dict, set, frozenset, range, slice, type}
RECORDS = {}
ENUM_SAFE = {}
VALIDATED = False


def identity_type(t):
    return (type(t) is type and t.__eq__ is object.__eq__
            and t.__ne__ is object.__ne__)


def eligible(a, b):
    """Only None comparisons or normal Enum members can establish equivalence.

    Exact builtins prevent subclasses/wrappers from supplying rich comparisons.
    Identity-only classes must inherit BOTH object comparison methods.
    """
    ta, tb = type(a), type(b)
    if a is None or b is None:
        t = tb if a is None else ta
        return any(t is builtin for builtin in BUILTINS) or identity_type(t)
    if ta is not tb or type(ta) is not enum.EnumType or not issubclass(ta, enum.Enum):
        return False
    if ta not in ENUM_SAFE:
        comparisons = {(t.__eq__, t.__ne__) for t in (object, str, int)}
        safe = (ta.__eq__, ta.__ne__) in comparisons
        members = list(ta.__members__.values())
        if safe:
            safe = all(type(x) is ta and type(y) is ta
                       and type(x == y) is bool and type(x != y) is bool
                       and (x == y) == (x is y) and (x != y) == (x is not y)
                       for x in members for y in members)
        ENUM_SAFE[ta] = safe
    return ENUM_SAFE[ta]


def compare(site, op, a, b):
    # Execute the original operator once, preserving rich-comparison behavior
    # and non-bool result objects. Never probe custom equality/inequality.
    if not RECORDS and "BR_OPERAND_OUTPUT" in os.environ:
        output = Path(os.environ["BR_OPERAND_OUTPUT"])
        output.mkdir(exist_ok=True, parents=True)
        (output / f"started-{os.getpid()}").touch()
    row = RECORDS.setdefault(site, {"pairs": set(), "safe": True})
    if row["safe"]:
        types = tuple(f"{type(v).__module__}.{type(v).__qualname__}"
                      if type(type(v)) in (type, enum.EnumType) else "<custom-metaclass>"
                      for v in (a, b))
        row["pairs"].add(types)
        if not eligible(a, b):
            row["safe"] = False
        else:
            same = a is b
            eq, ne = a == b, a != b
            if type(eq) is not bool or type(ne) is not bool or eq != same or ne == same:
                row["safe"] = False
    return OPS[op](a, b)


class Transform(ast.NodeTransformer):
    def __init__(self, rel):
        self.rel = rel

    def visit_Compare(self, node):
        self.generic_visit(node)
        if len(node.ops) != 1 or type(node.ops[0]).__name__ not in OPS:
            return node
        site = f"{self.rel}:{node.lineno}:{node.col_offset}"
        return ast.copy_location(ast.Call(
            func=ast.Name(id="_br_operand_compare", ctx=ast.Load()),
            args=[ast.Constant(site), ast.Constant(type(node.ops[0]).__name__),
                  node.left, node.comparators[0]], keywords=[]), node)


class Loader(importlib.machinery.SourceFileLoader):
    def exec_module(self, module):
        if "unittest" not in sys.modules or "pytest" not in sys.modules:
            raise RuntimeError("verification frameworks must precede SQLGlot")
        source = self.get_source(module.__name__)
        rel = Path(self.path).relative_to(os.environ["BR_OPERAND_SOURCE"]).as_posix()
        tree = ast.fix_missing_locations(Transform(rel).visit(ast.parse(source, self.path)))
        module.__dict__["_br_operand_compare"] = compare
        exec(compile(tree, self.path, "exec"), module.__dict__)  # noqa: S102 - pinned source instrumentation
        if module.__name__ == "sqlglot.expressions.core":
            if module.UNITTEST is not True:
                raise RuntimeError("profile child imported SQLGlot outside unittest mode")
            global VALIDATED
            VALIDATED = True
            output = Path(os.environ["BR_OPERAND_OUTPUT"])
            output.mkdir(exist_ok=True, parents=True)
            (output / f"validated-{os.getpid()}.json").write_text(json.dumps(
                {"pid": os.getpid(), "unittest": True, "pytest": True,
                 "core_unittest": True, "core_file": self.path}), encoding="utf-8")


class Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname != "sqlglot" and not fullname.startswith("sqlglot."):
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and spec.origin and spec.origin.endswith(".py"):
            spec.loader = Loader(fullname, spec.origin)
        return spec


def flush():
    if RECORDS:
        output = Path(os.environ["BR_OPERAND_OUTPUT"])
        output.mkdir(exist_ok=True, parents=True)
        data = {site: {"safe": row["safe"], "pairs": sorted(row["pairs"])}
                for site, row in RECORDS.items()}
        (output / f"process-{os.getpid()}.json").write_text(json.dumps(data, sort_keys=True))


def install():
    if any(name == "sqlglot" or name.startswith("sqlglot.") for name in sys.modules):
        raise RuntimeError("cannot profile stale preloaded SQLGlot")
    sys.meta_path.insert(0, Finder())
    atexit.register(flush)
    # multiprocessing workers run registered finalizers even when terminating
    # with os._exit, which bypasses ordinary atexit callbacks.
    from multiprocessing.util import Finalize
    Finalize(None, flush, exitpriority=0)


def main():
    source, output = (Path(p).resolve() for p in sys.argv[1:])
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as startup:
        Path(startup, "sitecustomize.py").write_text("import unittest\nimport pytest\nimport operand_profile\noperand_profile.install()\n")
        env = dict(os.environ, BR_OPERAND_SOURCE=str(source), BR_OPERAND_OUTPUT=str(output),
                   SKIP_INTEGRATION="0", PYTHONPATH=os.pathsep.join([startup, str(Path(__file__).parent), str(source)]),
                   OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1")
        started = time.monotonic()
        run = subprocess.Popen([sys.executable, "-m", "pytest", "tests", "-q", "-p", "no:cacheprovider"],
                               cwd=source, env=env)
        while True:
            (output / "progress.json").write_text(json.dumps(
                {"pid": run.pid, "elapsed": time.monotonic() - started, "updated": time.time()}))
            try:
                status = run.wait(timeout=60)
                break
            except subprocess.TimeoutExpired:
                pass
    if status:
        raise SystemExit(status)
    missing = [p.name for p in output.glob("started-*")
               if not (output / p.name.replace("started-", "process-")).with_suffix(".json").exists()]
    if missing:
        raise SystemExit(f"Incomplete operand workers: {missing}")
    validated = []
    for path in output.glob("process-*.json"):
        marker = output / path.name.replace("process-", "validated-")
        if not marker.exists():
            raise SystemExit(f"Unvalidated SQLGlot context: {path.name}")
        row = json.loads(marker.read_text(encoding="utf-8"))
        if not all(row.get(key) is True for key in ("unittest", "pytest", "core_unittest")):
            raise SystemExit(f"Invalid SQLGlot context: {marker.name}")
        validated.append(row)
    if not validated:
        raise SystemExit("No validated profiling child")
    merged = {}
    for path in output.glob("process-*.json"):
        for site, row in json.loads(path.read_text()).items():
            entry = merged.setdefault(site, {"safe": True, "pairs": set()})
            entry["safe"] &= row["safe"]
            entry["pairs"].update(map(tuple, row["pairs"]))
    data = {site: {"pairs": sorted(row["pairs"])} for site, row in merged.items() if row["safe"]}
    hashes = {p.relative_to(source).as_posix(): hashlib.sha256(p.read_text().encode()).hexdigest()
              for p in (source / "sqlglot").rglob("*.py")}
    encoded = json.dumps({"version": 1, "complete": True, "source_sha256": hashes,
                          "verification_context": {"unittest": True, "pytest": True, "core_unittest": True},
                          "sites": data}, sort_keys=True).encode()
    (output / "operand_profiles.json").write_bytes(encoded)
    (output / "operand_profiles.json.gz").write_bytes(gzip.compress(encoded, mtime=0))
    print(f"Profiled {len(merged)} sites; {len(data)} eligible sites", flush=True)


if __name__ == "__main__":
    main()
