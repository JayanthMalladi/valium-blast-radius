"""Apply a unified diff FilePatch onto pristine text, in memory.

Handles: normal edits, new files, deletions, renames, context offsets.
"""
from __future__ import annotations


def apply_file_patch(pristine_text: str | None, fp, allow_fuzzy: bool = True) -> str | None:
    """Return the patched text. None means 'file is deleted'.

    Uses a line-based splicer that tolerates small context offsets
    (searches for the context window around the hunk's old_start).
    """
    if fp.is_deleted:
        return None

    if fp.is_new or pristine_text is None:
        out: list[str] = []
        for hunk in fp.hunks:
            for kind, text in hunk.lines:
                if kind == "+":
                    out.append(text)
        return "\n".join(out) + "\n"

    lines = pristine_text.splitlines()
    # apply hunks from bottom to top so earlier line numbers stay valid
    for hunk in sorted(fp.hunks, key=lambda h: -h.old_start):
        lines = _splice(lines, hunk, allow_fuzzy)
    return "\n".join(lines) + ("\n" if lines else "")


def _splice(lines: list[str], hunk, allow_fuzzy: bool):
    """Splice one hunk into lines, searching for its context if needed."""
    old_ctx = [t for k, t in hunk.lines if k in (" ", "-")]
    # candidate start positions: expected first, then a small window
    expected = hunk.old_start - 1
    positions = [expected]
    if allow_fuzzy:
        for d in range(1, 41):
            positions += [expected + d, expected - d]
            if d > 20:
                break
    for start in positions:
        if start < 0 or start + len(old_ctx) > len(lines):
            continue
        ok = all(lines[start + i] == c for i, c in enumerate(old_ctx))
        if ok:
            new_seg: list[str] = []
            for kind, text in hunk.lines:
                if kind == " ":
                    new_seg.append(text)
                elif kind == "+":
                    new_seg.append(text)
            return lines[:start] + new_seg + lines[start + len(old_ctx):]
    # give up: leave the file unchanged except insert '+' lines at the expected spot
    new_seg = [t for k, t in hunk.lines if k in (" ", "+")]
    s = max(0, min(expected, len(lines)))
    return lines[:s] + new_seg + lines[s + len(old_ctx):]


def patch_applies(pristine_text: str | None, fp) -> bool:
    """True when every hunk's old-side lines are present in `pristine_text` at
    the hunk's own old_start (within the same fuzzy offset that _splice uses).

    A patch whose hunk does not match the pristine file cannot be applied, so
    its effect cannot be bounded from the maps; the caller must fall back to
    the full suite."""
    if fp.is_binary:
        return False
    if pristine_text is None:
        return fp.is_new      # new file: nothing to match on the old side
    lines = pristine_text.splitlines()
    for hunk in fp.hunks:
        old_ctx = [t for k, t in hunk.lines if k in (" ", "-")]
        if not old_ctx:
            continue
        expected = hunk.old_start - 1
        positions = [expected]
        for d in range(1, 41):
            positions += [expected + d, expected - d]
            if d > 20:
                break
        for start in positions:
            if 0 <= start and start + len(old_ctx) <= len(lines) and all(
                    lines[start + i] == c for i, c in enumerate(old_ctx)):
                break
        else:
            return False
    return True
