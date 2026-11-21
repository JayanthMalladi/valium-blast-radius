"""Map patch hunks onto PRISTINE (old-file) line numbers.

Each hunk is walked independently from its own old_start, so one hunk never
shifts another. The old-file position advances on " " and "-" lines only:

- A "-" line at old position `old_pos` changed or removed that pristine
  line; `old_pos` is recorded.
- A "+" line:
  * after a "-" in the same hunk: a modification/replacement; record
    `old_pos - 1` (the old line it replaced);
  * otherwise a pure insertion between old lines `old_pos - 1` and
    `old_pos`; record both (guards keep the result sane at the top of
    the file).
- A hunk whose old side is empty (`old_count == 0`) inserts between old
  lines `old_start` and `old_start + 1` (git convention).
"""
from __future__ import annotations

from . import patch as P


def changed_pristine_lines(fp: P.FilePatch) -> list[int]:
    """Old-file (pristine) line numbers affected by every hunk in `fp`."""
    out: set[int] = set()
    for h in fp.hunks:
        out.update(_hunk(h))
    return sorted(out)


def _hunk(h: P.Hunk) -> set[int]:
    res: set[int] = set()
    if h.old_count == 0:
        if h.old_start >= 1:
            res.add(h.old_start)
        res.add(h.old_start + 1)
        return res
    old_pos = h.old_start
    last: str | None = None
    for kind, _text in h.lines:
        if kind == " ":
            old_pos += 1
        elif kind == "-":
            res.add(old_pos)
            old_pos += 1
        else:  # "+"
            if last == "-":
                res.add(old_pos - 1)
            elif last != "+":
                if old_pos - 1 >= 1:
                    res.add(old_pos - 1)
                res.add(old_pos)
        last = kind
    return res
