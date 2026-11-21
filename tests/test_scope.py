"""Unit tests for scope classification."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from selector.scope import classify_file_change


def test_comment_only():
    old = "x = 1\n"
    new = "x = 1  # a comment\n"
    cat, regions = classify_file_change(old, new, set())
    assert cat == "comment_only"
    assert regions == []


def test_deleted_file():
    cat, regions = classify_file_change("x=1", None)
    assert cat == "code_change"


def test_new_file():
    cat, regions = classify_file_change(None, "x = 1\n")
    assert cat == "code_change"


def test_function_change():
    old = "def f():\n    return 1\n"
    new = "def f():\n    return 2\n"
    cat, regions = classify_file_change(old, new, {2})
    assert cat == "code_change"
    assert any(r["kind"] == "function" and r["name"] == "f" for r in regions)


def test_module_level_change():
    old = "import os\n"
    new = "import sys\n"
    cat, regions = classify_file_change(old, new, {1})
    assert cat == "code_change"
    assert any(r["kind"] == "module" for r in regions)


def test_import_break():
    old = "x = 1\n"
    new = "x = 1\ndef f(:\n    pass\n"
    cat, regions = classify_file_change(old, new, None)
    assert cat == "import_break"
