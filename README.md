# Blast Radius

## Approach

The selector runs in three passes per changed `sqlglot/*.py` file:

1. **Pristine-line mapping** — translate every patch line back to the
   corresponding old-file (pristine) line number, using the hunk's own
   `old_start` and the "+ before / after anchor" rule for pure insertions.
2. **Statement-level lookup** — for each pristine line, `ast.parse` the
   pristine file and find the smallest enclosing statement; a continuation
   line of `return (` or `if (` maps to the header's range, not the
   physical line alone. Then query the line map for every line in that
   statement range and union the results.
3. **Coarse canary (safe mode)** — when the line map is absent or the
   code-change selection falls below a small threshold, the canary adds
   the whole `tests/test_optimizer.py` + `tests/test_executor.py` suites,
   guaranteeing 0 misses by construction.

Other file types use small, non-overselecting rules:

- `tests/fixtures/**` (`.sql` / `.json`) → fixture map, fallback to
  `tests/test_optimizer.py`.
- `tests/*.py` → test-file map (which tests live in that file).
- `sqlglot/*.py` **new / unparseable** → `tests/test_dialect.py`.
- `sqlglot/*.py` **import-break** → module-level selection (importers
  + source readers + class-uses union).
- `sqlglot/*.py` **comment-only** → source-reader / doctest tests only.
- `sqlglot/*.py` **deleted / binary** → module + test-file union.
- Non-`.py` outside `tests/` and `sqlglot/` → empty selection.

Packing: LPT + local improvement, k = 1..8, keep the minimum of
(max load + 2 s·k) in integer ms.

## Build

`docker build --platform linux/amd64 -t br-entry-s2 entry/`

The Dockerfile downloads the pinned sqlglot tarball with stdlib `urllib`,
extracts to `/opt/sqlglot`, and copies the selector + maps. No `apt`,
no `git`.

## Run

`python -m selector.main` — stdlib only; reads `BR_MAPS`, `BR_PRISTINE`,
`BR_DATA`. Set `BR_DEBUG=1` to write `work/runs/<run>.reasons.jsonl`.

## Compliance

- No patch→test or edit-kind→test lookup tables.
- No sample commit ids, mutant data, or labels in the selector.
- Maps built from the pinned commit only (`eb11aec`).
- No `module_importers.json` as a selection source (it is a first-loader
  artifact, 0–1 entries per module, unsafe as a stub fallback).
- All selections trace to the line, statement, or explicit canary rule.
