"""Narrowing rules (selector/narrow.py): each fires only on its own edit kind."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector.narrow import Narrower

CORE = (
    "class Expression:\n"
    "    arg_types = {'this': True}\n"
    "class Func(Expression):\n"
    "    pass\n"
    "class Trigger(Expression):\n"
    "    arg_types = {'this': True, 'when': False}\n"
    "class Upper(Func):\n"
    "    arg_types = {'this': True, 'n': False}\n"
)
PARSER = (
    "import exp\n"
    "class Parser:\n"
    "    FUNCTIONS = {\n"
    "        'X': lambda args: exp.Upper(\n"
    "            this=args[0],\n"
    "        ),\n"
    "    }\n"
    "    LOCATIONS = {exp.Trigger: 1}\n"
    "    def parse_trigger(self):\n"
    "        return exp.Trigger(this=1)\n"
)
DIALECT = (
    "class Dialect:\n"
    "    WEEK_OFFSET = 0\n"
    "    def trunc(self):\n"
    "        return self.WEEK_OFFSET + 1\n"
    "class Eager:\n"
    "    FLAG = True\n"
    "    DERIVED = FLAG\n"
)


def _n() -> Narrower:
    return Narrower({"sqlglot/core.py": CORE, "sqlglot/parser.py": PARSER,
                     "sqlglot/dialect.py": DIALECT,
                     "tests/test_trigger.py": "def test():\n    Trigger\n"})


def test_lambda_body_change_uses_body_lines_only():
    patched = PARSER.replace("this=args[0]", "this=args[1]")
    kind, lines, files = _n().narrow("sqlglot/parser.py", PARSER, patched)
    assert lines == [("sqlglot/parser.py", 5), ("sqlglot/parser.py", 6)] and not files


def test_lambda_header_change_is_not_narrowed():
    patched = PARSER.replace("exp.Upper(", "exp.Lower(")
    assert _n().narrow("sqlglot/parser.py", PARSER, patched) is None


def test_class_constant_read_in_function_body():
    patched = DIALECT.replace("WEEK_OFFSET = 0", "WEEK_OFFSET = -1")
    kind, lines, files = _n().narrow("sqlglot/dialect.py", DIALECT, patched)
    assert lines == [("sqlglot/dialect.py", 4)]


def test_class_constant_read_at_import_time_falls_back():
    patched = DIALECT.replace("FLAG = True", "FLAG = False")
    assert _n().narrow("sqlglot/dialect.py", DIALECT, patched) is None


def test_arg_types_flip_selects_references_and_test_files():
    patched = CORE.replace("'when': False", "'when': True")
    kind, lines, files = _n().narrow("sqlglot/core.py", CORE, patched)
    assert ("sqlglot/parser.py", 10) in lines          # function-body reference
    assert ("sqlglot/parser.py", 8) not in lines       # dict key only names it
    assert files == {"tests/test_trigger.py"}


def test_arg_types_flip_on_func_class_falls_back():
    patched = CORE.replace("'n': False", "'n': True")
    assert _n().narrow("sqlglot/core.py", CORE, patched) is None


def test_arg_types_key_change_falls_back():
    patched = CORE.replace("'when': False", "'when': False, 'extra': False")
    assert _n().narrow("sqlglot/core.py", CORE, patched) is None
