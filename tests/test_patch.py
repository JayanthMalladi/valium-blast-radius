"""Unit tests for the unified-diff parser."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from selector import patch as P


def test_basic_add():
    text = """diff --git a/sqlglot/helper.py b/sqlglot/helper.py
--- a/sqlglot/helper.py
+++ b/sqlglot/helper.py
@@ -1,2 +1,3 @@
 x = 1
+y = 2
 z = 3
"""
    files = P.parse_patch(text)
    assert len(files) == 1
    fp = files[0]
    assert fp.path == "sqlglot/helper.py"
    assert not fp.is_new and not fp.is_deleted
    assert len(fp.hunks) == 1
    assert fp.hunks[0].new_start == 1
    plus_lines = [t for k, t in fp.hunks[0].lines if k == "+"]
    assert plus_lines == ["y = 2"]


def test_new_file():
    text = """diff --git a/sqlglot/newmod.py b/sqlglot/newmod.py
new file mode 100644
--- /dev/null
+++ b/sqlglot/newmod.py
@@ -0,0 +1,3 @@
+A = 1
+
+def f():
"""
    files = P.parse_patch(text)
    fp = files[0]
    assert fp.is_new
    assert fp.path == "sqlglot/newmod.py"
    assert [t for k, t in fp.hunks[0].lines if k == "+"] == ["A = 1", "", "def f():"]


def test_deleted_file():
    text = """diff --git a/sqlglot/old.py b/sqlglot/old.py
deleted file mode 100644
--- a/sqlglot/old.py
+++ /dev/null
@@ -1,2 +0,0 @@
-x = 1
-y = 2
"""
    files = P.parse_patch(text)
    fp = files[0]
    assert fp.is_deleted


def test_renamed():
    text = """diff --git a/sqlglot/old_name.py b/sqlglot/new_name.py
rename from sqlglot/old_name.py
rename to sqlglot/new_name.py
--- a/sqlglot/old_name.py
+++ b/sqlglot/new_name.py
@@ -1 +1 @@
-foo
+bar
"""
    files = P.parse_patch(text)
    fp = files[0]
    assert fp.is_renamed
    assert fp.path == "sqlglot/new_name.py"


def test_no_newline_marker():
    text = """diff --git a/x.py b/x.py
--- a/x.py
+++ b/x.py
@@ -1 +1 @@
-a
+b
\\ No newline at end of file
"""
    files = P.parse_patch(text)
    assert len(files) == 1
    plus = [t for k, t in files[0].hunks[0].lines if k == "+"]
    assert plus == ["b"]


def test_malformed_does_not_crash():
    files = P.parse_patch("this is not a patch at all\njust some text\n")
    assert isinstance(files, list)


def test_binary_file():
    text = """diff --git a/img.png b/img.png
new file mode 100644
Binary files /dev/null and b/img.png differ
"""
    files = P.parse_patch(text)
    assert files[0].is_binary
    assert files[0].path == "img.png"
