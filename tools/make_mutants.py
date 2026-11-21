"""Generate a realistic, diverse set of mutant patches against the pinned
sqlglot commit. Used for evaluation only — none of this ships in the entry repo.

Writes unified-diff files to <outdir>, one commit dir per patch. Patch style
matches the sample set: single unified diff per file batch, real hunk headers.
"""
from __future__ import annotations
import os
import random
import subprocess
import sys

random.seed(20261121)


def git(*args, cwd):
    return subprocess.run(["git"] + list(args), cwd=cwd,
                          capture_output=True, text=True)


def make_patch(workdir, changes, outdir, name, kind):
    """changes: list of (relpath, content_or_None_for_delete, binary_flag)."""
    # apply changes on a clean index
    git("checkout", "--", ".", cwd=workdir)
    git("reset", "--hard", cwd=workdir)
    for rel, content, binary in changes:
        p = os.path.join(workdir, rel)
        if content is None:
            os.remove(p) if os.path.exists(p) else None
            git("rm", "-f", rel, cwd=workdir)
        else:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb" if binary else "w",
                      encoding=None if binary else "utf-8") as f:
                f.write(content)
            git("add", "-A", rel, cwd=workdir)
    r = git("diff", "--cached", "--no-color", cwd=workdir)
    patch = r.stdout
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, f"{name}.patch"), "w", encoding="utf-8", newline="\n") as f:
        f.write(patch)
    with open(os.path.join(outdir, f"{name}.kind"), "w", encoding="utf-8") as f:
        f.write(kind + "\n")
    # revert
    git("checkout", "--", ".", cwd=workdir)
    git("reset", "--hard", cwd=workdir)
    git("clean", "-fd", cwd=workdir)
    return patch


def edit_line(text, line_no, replacement):
    lines = text.splitlines()
    lines[line_no - 1] = replacement
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def main():
    src = sys.argv[1]      # pristine sqlglot
    out = sys.argv[2]      # output dir for patches
    target = int(sys.argv[3]) if len(sys.argv) > 3 else 160

    py_files = []
    for root, dirs, files in os.walk(os.path.join(src, "sqlglot")):
        for f in files:
            if f.endswith(".py"):
                py_files.append(os.path.relpath(os.path.join(root, f), src))
    core = [f for f in py_files if any(f.startswith(p) for p in
            ["sqlglot/parser.py", "sqlglot/generator.py", "sqlglot/tokens.py",
             "sqlglot/expressions.py", "sqlglot/optimizer/", "sqlglot/executor/"])]
    dialects = [f for f in py_files if f.startswith("sqlglot/dialects/")]
    fixtures = []
    for root, dirs, files in os.walk(os.path.join(src, "tests", "fixtures")):
        for f in files:
            fixtures.append(os.path.relpath(os.path.join(root, f), src))
    test_files = []
    for root, dirs, files in os.walk(os.path.join(src, "tests")):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                test_files.append(os.path.relpath(os.path.join(root, f), src))

    manifest = []
    n = 0

    def gen_code_edit(flavor):
        nonlocal n
        pool = random.choice([core, dialects]) if flavor in ("core", "dialect") else core
        rel = random.choice(pool)
        text = open(os.path.join(src, rel), encoding="utf-8").read()
        lines = text.splitlines()
        if not lines:
            return
        # pick a random non-empty line that looks editable
        cand = [i for i, line in enumerate(lines, 1) if line.strip() and not line.startswith("#")]
        if not cand:
            return
        ln = random.choice(cand)
        orig = lines[ln - 1]
        flavor = random.choice(["const", "cond", "swap", "return", "delete"])
        if flavor == "const":
            # find a number on this line and mutate it
            import re
            m = re.search(r"\b\d+\b", orig)
            new = orig if not m else orig.replace(m.group(0), str(int(m.group(0)) + 7), 1)
            new = new if new != orig else orig.rstrip() + "  # pad"
        elif flavor == "cond":
            new = orig.replace(">", ">=") if ">" in orig else orig + "  # m"
        elif flavor == "swap":
            m = __import__("re").search(r"\(", orig)
            new = orig if not m else "mut" + orig
        elif flavor == "return":
            new = orig.rstrip() + "  # m"
        else:
            new = ""
        text2 = edit_line(text, ln, new)
        make_patch(src, [(rel, text2, False)], out, f"mut{n:03d}", "code-" + flavor)
        manifest.append({"name": f"mut{n:03d}", "kind": "code-" + flavor})
        n += 1

    def gen_class_table_edit():
        nonlocal n
        rel = random.choice(dialects)
        text = open(os.path.join(src, rel), encoding="utf-8").read()
        lines = text.splitlines()
        # find a line inside a dict/KEYWORDS/FUNCTIONS-style table: a line with '":'
        cand = [i for i, line in enumerate(lines, 1) if '":' in line]
        if not cand:
            return
        ln = random.choice(cand)
        new = lines[ln - 1] + "  # m" if random.random() < 0.5 else lines[ln - 1] + ","
        text2 = edit_line(text, ln, new)
        make_patch(src, [(rel, text2, False)], out, f"mut{n:03d}", "class-table")
        manifest.append({"name": f"mut{n:03d}", "kind": "class-table"})
        n += 1

    def gen_comment():
        nonlocal n
        rel = random.choice(core + dialects + test_files)
        text = open(os.path.join(src, rel), encoding="utf-8").read()
        lines = text.splitlines()
        cand = [i for i, line in enumerate(lines, 1) if line.strip() and not line.startswith("#")]
        ln = random.choice(cand)
        new = lines[ln - 1] + "  # mutant-note-" + str(n)
        make_patch(src, [(rel, edit_line(text, ln, new), False)], out, f"mut{n:03d}", "comment")
        manifest.append({"name": f"mut{n:03d}", "kind": "comment"})
        n += 1

    def gen_docstring():
        nonlocal n
        rel = random.choice(core)
        text = open(os.path.join(src, rel), encoding="utf-8").read()
        lines = text.splitlines()
        cand = [i for i, line in enumerate(lines, 1) if line.strip().startswith('"""')]
        if not cand:
            return gen_comment()
        ln = random.choice(cand)
        new = lines[ln - 1].rstrip() + " mutated"
        make_patch(src, [(rel, edit_line(text, ln, new), False)], out, f"mut{n:03d}", "docstring")
        manifest.append({"name": f"mut{n:03d}", "kind": "docstring"})
        n += 1

    def gen_import_break():
        nonlocal n
        rel = random.choice(core)
        text = open(os.path.join(src, rel), encoding="utf-8").read()
        lines = text.splitlines()
        cand = [i for i, line in enumerate(lines, 1) if line.startswith("def ") or line.startswith("class ")]
        if not cand:
            return
        ln = random.choice(cand)
        # delete the whole def line -> syntax error
        new_lines = lines[:ln - 1] + lines[ln:]
        make_patch(src, [(rel, "\n".join(new_lines) + "\n", False)], out, f"mut{n:03d}", "import-break")
        manifest.append({"name": f"mut{n:03d}", "kind": "import-break"})
        n += 1

    def gen_fixture():
        nonlocal n
        rel = random.choice(fixtures)
        text = open(os.path.join(src, rel), encoding="utf-8", errors="replace").read()
        new = text + "\nmutated;\n" if ";" in text else text + "mutated\n"
        make_patch(src, [(rel, new, False)], out, f"mut{n:03d}", "fixture")
        manifest.append({"name": f"mut{n:03d}", "kind": "fixture"})
        n += 1

    def gen_testfile():
        nonlocal n
        rel = random.choice(test_files)
        text = open(os.path.join(src, rel), encoding="utf-8").read()
        lines = text.splitlines()
        cand = [i for i, line in enumerate(lines, 1) if "def test_" in line]
        if not cand:
            return
        ln = random.choice(cand)
        new = lines[ln - 1] + "  # m"
        make_patch(src, [(rel, edit_line(text, ln, new), False)], out, f"mut{n:03d}", "testfile")
        manifest.append({"name": f"mut{n:03d}", "kind": "testfile"})
        n += 1

    def gen_newfile():
        nonlocal n
        content = "X = 1\n\n\ndef f():\n    return X + 1\n"
        make_patch(src, [("sqlglot/_mutnew.py", content, False)], out, f"mut{n:03d}", "new-file")
        manifest.append({"name": f"mut{n:03d}", "kind": "new-file"})
        n += 1

    def gen_newfile_break():
        nonlocal n
        content = "X = 1\ndef f(:\n    return 1\n"
        make_patch(src, [("sqlglot/_mutnew.py", content, False)], out, f"mut{n:03d}", "new-file-break")
        manifest.append({"name": f"mut{n:03d}", "kind": "new-file-break"})
        n += 1

    def gen_multifile():
        nonlocal n
        a = random.choice(core)
        b = random.choice(dialects)
        ta = open(os.path.join(src, a), encoding="utf-8").read()
        tb = open(os.path.join(src, b), encoding="utf-8").read()
        la = [i for i, line in enumerate(ta.splitlines(), 1) if line.strip()]
        lb = [i for i, line in enumerate(tb.splitlines(), 1) if line.strip()]
        if not la or not lb:
            return
        na, nb = random.choice(la), random.choice(lb)
        ma = edit_line(ta, na, ta.splitlines()[na - 1] + "  # m")
        mb = edit_line(tb, nb, tb.splitlines()[nb - 1] + "  # m")
        make_patch(src, [(a, ma, False), (b, mb, False)], out, f"mut{n:03d}", "multi")
        manifest.append({"name": f"mut{n:03d}", "kind": "multi"})
        n += 1

    def gen_delete():
        nonlocal n
        rel = random.choice(dialects)
        text = open(os.path.join(src, rel), encoding="utf-8").read()
        lines = text.splitlines()
        cand = [i for i, line in enumerate(lines, 1) if line.strip()]
        ln = random.choice(cand)
        new_lines = lines[:ln - 1] + lines[ln:]
        make_patch(src, [(rel, "\n".join(new_lines) + ("\n" if text.endswith("\n") else ""), False)],
                   out, f"mut{n:03d}", "delete-line")
        manifest.append({"name": f"mut{n:03d}", "kind": "delete-line"})
        n += 1

    kinds = [
        ("code-core", 25, lambda: gen_code_edit("core")),
        ("code-dialect", 25, lambda: gen_code_edit("dialect")),
        ("class-table", 15, gen_class_table_edit),
        ("comment", 15, gen_comment),
        ("docstring", 10, gen_docstring),
        ("import-break", 8, gen_import_break),
        ("fixture", 10, gen_fixture),
        ("testfile", 6, gen_testfile),
        ("new-file", 4, gen_newfile),
        ("new-file-break", 3, gen_newfile_break),
        ("multi", 7, gen_multifile),
        ("delete-line", 8, gen_delete),
    ]
    for kind, cnt, fn in kinds:
        for _ in range(cnt):
            fn()
            if n >= target:
                break
        if n >= target:
            break

    json = __import__("json")
    with open(os.path.join(out, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    print(f"[mutants] wrote {len(manifest)} patches to {out}")


if __name__ == "__main__":
    main()
