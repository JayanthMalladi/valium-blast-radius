"""Scaled replica of tests/test_parser.py::TestParser::test_max_nodes.

Runs the test's assertions on the patched tree with a 300-wide statement
(instead of 10,000) and limits scaled to match. Exit 0 only on a clean pass.
Usage: python -m selector.maxnodes_probe   (patched tree first on sys.path)
"""
import sys
import unittest  # noqa: F401  (sqlglot checks for it at import, as the tests do)


def main() -> None:
    from sqlglot import exp, parse_one
    from sqlglot.errors import ParseError

    assert isinstance(parse_one("SELECT 1", max_nodes=1_000_000), exp.Select)
    cols = [f"col{i}" for i in range(500)]
    assert isinstance(parse_one(f"SELECT {','.join(cols)} FROM t", max_nodes=1_000_000), exp.Select)

    width, depth = 300, 100
    expr = "x" + "=x" * depth
    sql = "SELECT " + ",".join(expr for _ in range(width))
    # Unbounded parse succeeds; the full test's 10,000-wide statement exceeds
    # 1,000,000 nodes, this one exceeds 30,000 (and 1,500).
    assert isinstance(parse_one(sql), exp.Select)
    for limit in (30_000, 1_500):
        try:
            parse_one(sql, max_nodes=limit)
        except ParseError as e:
            assert "Maximum number of AST nodes" in str(e), str(e)
            assert f"({limit})" in str(e), str(e)
        else:
            raise AssertionError(f"no ParseError at {limit}")
    try:
        parse_one("SELECT " + ",".join(f"x={i}" for i in range(100)), max_nodes=5)
    except ParseError:
        pass
    else:
        raise AssertionError("no ParseError at 5")
    assert isinstance(parse_one("SELECT 1, 2, 3"), exp.Select)


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        sys.exit(1)
    sys.exit(0)
