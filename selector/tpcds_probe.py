"""Staged digest of what tests/test_executor.py::TestExecutor::test_execute_tpcds
computes before it touches data.

For every TPC-DS fixture query the test executes, the digest records: the
parsed expression the parent sends to the worker, the DuckDB SQL the expected
result is computed from, the optimized expression execute() plans from
(with types), the plan's steps, and the Python source the executor compiles
for each step and each subquery plan (driven with empty tables). When the
digest of a patched tree equals the pristine one and no changed file holds
code the executor runs on the data itself, the test sees identical inputs and
identical code, so it cannot change outcome.

Usage:
  python -m selector.tpcds_probe <sqlglot root> <out.json>   (writes digest)
The selector runs it in a subprocess with the patched tree first on sys.path.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _queries(root: str):
    ns: dict = {}
    helpers = os.path.join(root, "tests", "helpers.py")
    with open(helpers, encoding="utf-8") as f:
        code = f.read()
    ns["__file__"] = helpers
    exec(compile(code, helpers, "exec"), ns)
    return ns["TPCDS_SCHEMA"], list(ns["load_sql_fixture_pairs"]("optimizer/tpc-ds/tpc-ds.sql"))


def digest(root: str) -> dict:
    import unittest  # noqa: F401  (sqlglot checks for it at import, as the tests do)

    from sqlglot import parse_one, transpile
    from sqlglot.executor import python as py
    from sqlglot.executor.table import Table, ensure_tables
    from sqlglot.optimizer import optimize
    from sqlglot.planner import Plan
    from sqlglot.schema import ensure_schema

    schema_dict, pairs = _queries(root)
    schema = ensure_schema(schema_dict)
    out: dict = {"schema": _sha(repr(schema.mapping))}
    tables = {name: Table(columns=list(cols)) for name, cols in schema_dict.items()}

    sources: list = []
    orig_generate = py.PythonExecutor.generate

    def generate(self, expression):
        if expression:
            replaced = self._replace_subqueries(expression)
            sources.append(self.generator.generate(replaced))
        return orig_generate(self, expression)

    py.PythonExecutor.generate = generate
    try:
        for i, (meta, sql, _) in enumerate(pairs):
            if not meta.get("execute"):
                continue
            parts = []
            try:
                import pickle
                # The test pickles the parsed expression to a worker process.
                expression = pickle.loads(pickle.dumps(parse_one(sql)))
                parts.append(repr(expression))
                parts.append(transpile(sql, write="duckdb")[0])
                optimized = optimize(expression.copy(), schema, leave_tables_isolated=True)
                parts.append(repr(optimized))
                parts.append(repr([str(n.type) if n.type else "" for n in optimized.walk()]))
                plan = Plan(optimized)
                steps, todo, seen = [], [plan.root], set()
                while todo:
                    node = todo.pop()
                    if id(node) in seen:
                        continue
                    seen.add(id(node))
                    steps.append(f"{type(node).__name__}|{node.name}|"
                                 f"{sorted(d.name for d in node.dependencies)}")
                    todo.extend(node.dependencies)
                parts.append(repr(sorted(steps)))
                sources.clear()
                executor = py.PythonExecutor(tables=ensure_tables(dict(tables)))
                try:
                    executor.execute(plan)
                except Exception as exc:
                    parts.append("exec:" + type(exc).__name__)
                for name in sorted(getattr(executor, "_subquery_plans", {}) or {}, key=str):
                    try:
                        executor.execute(executor._subquery_plans[name])
                    except Exception as exc:
                        parts.append("sub:" + type(exc).__name__)
                parts.append(repr(sorted(sources)))
            except Exception as exc:
                parts.append("error:" + type(exc).__name__ + ":" + str(exc)[:200])
            out[str(i)] = _sha("\n\x00".join(parts))
    finally:
        py.PythonExecutor.generate = orig_generate
    return out


def main() -> None:
    root, out = sys.argv[1], sys.argv[2]
    d = digest(root)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(d, f, sort_keys=True)


if __name__ == "__main__":
    main()
