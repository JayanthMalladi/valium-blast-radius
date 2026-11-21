"""Parse unified diffs: files, hunks, new/deleted/binary, renames."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Hunk:
    """One hunk: (old_start, old_count, new_start, new_count, lines).
    lines is a list of (kind, text) where kind is one of ' ', '+', '-'.
    """
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class FilePatch:
    path: str
    old_path: str
    is_new: bool
    is_deleted: bool
    is_binary: bool
    is_renamed: bool
    hunks: list[Hunk] = field(default_factory=list)


def parse_patch(text: str) -> list[FilePatch]:
    """Parse a unified diff (one or more files) into FilePatch objects.
    Tolerant of malformed input: skips files that cannot be parsed,
    never raises on bad content.
    """
    files: list[FilePatch] = []
    cur: FilePatch | None = None
    cur_hunk: Hunk | None = None

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # new file section
        if line.startswith("diff --git"):
            if cur:
                files.append(cur)
                cur = None
                cur_hunk = None
            # diff --git a/path b/path
            parts = line.split()
            if len(parts) >= 4:
                old_path = parts[2].removeprefix("a/")
                new_path = parts[3].removeprefix("b/")
                cur = FilePatch(
                    path=new_path,
                    old_path=old_path,
                    is_new=False,
                    is_deleted=False,
                    is_binary=False,
                    is_renamed=(old_path != new_path),
                )
            i += 1
            continue

        if cur is None:
            i += 1
            continue

        if line.startswith("new file mode"):
            cur.is_new = True
            i += 1
        elif line.startswith("deleted file mode"):
            cur.is_deleted = True
            i += 1
        elif line.startswith("rename from"):
            cur.old_path = line.split()[-1].strip()
            cur.is_renamed = True
            i += 1
        elif line.startswith("rename to"):
            cur.path = line.split()[-1].strip()
            cur.is_renamed = True
            i += 1
        elif line.startswith("Binary files"):
            cur.is_binary = True
            i += 1
        elif line.startswith("---"):
            # --- a/path or /dev/null
            i += 1
        elif line.startswith("+++"):
            # +++ b/path or /dev/null
            i += 1
        elif line.startswith("@@"):
            # @@ -old_start,old_count +new_start,new_count @@
            import re
            m = re.match(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                cur_hunk = Hunk(
                    old_start=int(m.group(1)),
                    old_count=int(m.group(2) or 1),
                    new_start=int(m.group(3)),
                    new_count=int(m.group(4) or 1),
                )
                cur.hunks.append(cur_hunk)
            i += 1
        elif cur_hunk is not None:
            if line.startswith("+") or line.startswith("-") or (line and not line.startswith(" ")):
                # +/- line in hunk
                kind = line[0] if line[:1] in ("+", "-") else " "
                cur_hunk.lines.append((kind, line[1:] if len(line) > 1 else ""))
            elif line.startswith("\\"):
                # "\ No newline at end of file" marker
                i += 1
                continue
            elif line.startswith(" "):
                cur_hunk.lines.append((" ", line[1:] if len(line) > 1 else ""))
            i += 1
        else:
            i += 1

    if cur:
        files.append(cur)
    return files


def changed_line_numbers(fp: FilePatch) -> list[tuple[str, int]]:
    """Return [(path, new_line_number)] for every added or modified line."""
    result: list[tuple[str, int]] = []
    for hunk in fp.hunks:
        new_line = hunk.new_start
        for kind, _text in hunk.lines:
            if kind in ("+", " "):
                new_line += 1
            if kind == "+":
                result.append((fp.path, new_line))
    return result
