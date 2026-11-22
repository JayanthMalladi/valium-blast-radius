"""Record, per test, the expression classes whose required args were checked.

Usage: python tools/record_validated.py <sqlglot checkout> <out.json>

The class recorded is the one that owns the arg_types dict used. Validation
in class or module fixtures is recorded under "CLASS:<id>" / "MODULE:<id>";
validation outside any test (imports, lazily built module state, teardown)
under "<import>". Worker processes the tests spawn record into
<out.json>.children/, credited to the scope active in the parent at the time
of the call (the parent writes it to <out.json>.children/ctx).
"""
import unittest  # before sqlglot
import json
import os
import sys

current = ["<import>"]
seen = {}
_child_dir = os.environ.get("REC_CHILD_DIR")
_child_seen = set()


_ctx_cache = [None, "<import>"]


def _ctx_path():
    # Kept off the output directory: a bind mount can serve stale mtimes.
    return os.environ.get("REC_CTX_FILE") or os.path.join(_child_dir, "ctx")


def _set(ctx):
    current[0] = ctx
    if _child_dir is not None:
        tmp = _ctx_path() + ".tmp"
        with open(tmp, "w") as f:
            f.write(ctx or "<import>")
        os.replace(tmp, _ctx_path())


def _parent_ctx():
    path = _ctx_path()
    try:
        st = os.stat(path)
        mtime = (st.st_ino, st.st_mtime_ns)
    except OSError:
        return "<import>"
    if mtime != _ctx_cache[0]:
        try:
            _ctx_cache[1] = open(path).read() or "<import>"
        except OSError:
            pass
        _ctx_cache[0] = mtime
    return _ctx_cache[1]


def owner(cls):
    for k in cls.__mro__:
        if "arg_types" in k.__dict__:
            return k.__name__
    return cls.__name__


def _note(name):
    if _child_dir is not None and __name__ != "__main__":
        key = (_parent_ctx(), name)
        if key not in _child_seen:
            _child_seen.add(key)
            with open(os.path.join(_child_dir, f"{os.getpid()}.jsonl"), "a") as f:
                f.write(json.dumps(key) + "\n")
    else:
        seen.setdefault(current[0] or "<import>", set()).add(name)


def _wrap_init(cls):
    orig = cls.__dict__.get("__init__")
    if orig is None or getattr(orig, "_recorded", False):
        return

    def __init__(self, *a, **k):
        for c in type(self).__mro__:
            if c.__module__.startswith("sqlglot"):
                _note("I:" + c.__module__ + "." + c.__qualname__)
        return orig(self, *a, **k)

    __init__._recorded = True
    cls.__init__ = __init__


def _patch_instances():
    # Record the classes of every Dialect, Tokenizer, Parser and Generator
    # instance created ("I:<module>.<qualname>" for each sqlglot class in its
    # MRO), so a class constant read through self can be bounded by type.
    import sqlglot.dialects  # noqa: F401  (registers every dialect)
    from sqlglot.dialects.dialect import Dialect
    from sqlglot.generator import Generator
    from sqlglot.parser import Parser
    from sqlglot.tokens import Tokenizer

    for name in list(getattr(sqlglot.dialects, "__all__", [])):
        try:
            getattr(sqlglot.dialects, name)
        except Exception:
            pass
    todo = [Dialect, Generator, Parser, Tokenizer]
    while todo:
        cls = todo.pop()
        _wrap_init(cls)
        todo.extend(cls.__subclasses__())


def _patch():
    from sqlglot.expressions import core

    orig = core.Expression.error_messages

    def error_messages(self, args=None):
        _note(owner(type(self)))
        return orig(self, args)

    core.Expression.error_messages = error_messages
    _patch_instances()


def node_id(test):
    mod, cls, meth = test.id().rsplit(".", 2)
    return mod.replace(".", "/") + ".py::" + cls + "::" + meth.split(" ")[0]


if __name__ != "__main__" and _child_dir is not None:
    # A spawned worker re-imports this file as __mp_main__: record, don't run.
    _patch()


def main():
    global _child_dir
    root, out = os.path.abspath(sys.argv[1]), sys.argv[2]
    _child_dir = os.path.abspath(out) + ".children"
    os.makedirs(_child_dir, exist_ok=True)
    for f in os.listdir(_child_dir):
        os.remove(os.path.join(_child_dir, f))
    os.environ["REC_CHILD_DIR"] = _child_dir
    import tempfile
    os.environ["REC_CTX_FILE"] = os.path.join(tempfile.mkdtemp(prefix="rec_ctx_"), "ctx")
    os.chdir(root)
    sys.path.insert(0, root)
    os.environ["PYTHONPATH"] = root + os.pathsep + os.environ.get("PYTHONPATH", "")
    os.environ.setdefault("SKIP_INTEGRATION", "0")
    _patch()
    _set("<import>")

    class Result(unittest.TextTestResult):
        def startTest(self, test):
            _set(node_id(test))
            super().startTest(test)

        def stopTest(self, test):
            super().stopTest(test)
            _set(None)

    class_setup = unittest.suite.TestSuite._handleClassSetUp
    module_fixture = unittest.suite.TestSuite._handleModuleFixture

    def handle_class(self, test, result):
        prev = current[0]
        _set("CLASS:" + node_id(test).rsplit("::", 1)[0])
        try:
            return class_setup(self, test, result)
        finally:
            _set(prev)

    def handle_module(self, test, result):
        prev = current[0]
        _set("MODULE:" + node_id(test).split("::", 1)[0])
        try:
            return module_fixture(self, test, result)
        finally:
            _set(prev)

    unittest.suite.TestSuite._handleClassSetUp = handle_class
    unittest.suite.TestSuite._handleModuleFixture = handle_module

    suite = unittest.defaultTestLoader.discover("tests", top_level_dir=root)
    _set(None)
    runner = unittest.TextTestRunner(resultclass=Result, verbosity=0,
                                     stream=open(os.devnull, "w"))
    r = runner.run(suite)
    children = 0
    for f in os.listdir(_child_dir):
        if not f.endswith(".jsonl"):
            continue
        for line in open(os.path.join(_child_dir, f)):
            ctx, name = json.loads(line)
            seen.setdefault(ctx, set()).add(name)
            children += 1
    with open(out, "w") as f:
        json.dump({k: sorted(v) for k, v in sorted(seen.items())}, f, indent=0)
    print("tests", r.testsRun, "fail", len(r.failures), "err", len(r.errors),
          "recorded", len(seen), "child records", children, file=sys.stderr)


if __name__ == "__main__":
    main()
