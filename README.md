# Blast Radius

## Approach

For each changed `sqlglot/*.py` file the selector works in three passes, then
packs the result across up to 8 workers.

1. **Pristine-line mapping** — translate every patch line back to the
   corresponding old-file (pristine) line number, using the hunk's own
   `old_start` and the "+ before / after anchor" rule for pure insertions.
2. **Statement-level lookup** — `ast.parse` the pristine file and find the
   smallest enclosing statement for each changed pristine line; a
   continuation line of `return (` or `if (` maps to the header's range, not
   the physical line alone. Query the line map for every line in that range.
3. **Dialect-family rule** — for a file under `sqlglot/{dialects,
   generators, parsers, typing}/`, also select every test that executed any
   line of a sibling file with the same module stem (e.g. changing
   `dialects/tsql.py` also pulls in tests that ran `generators/tsql.py`,
   `parsers/tsql.py`, `typing/tsql.py`). This is general line-coverage
   structure, not patch-specific data.

### Safe fallbacks (full suite)

When the effect of a change cannot be bounded from the pinned-commit maps,
the selector runs the full suite rather than under-selecting:

- import break (patched file no longer parses),
- a deleted `.py` under `sqlglot/`,
- a binary `.py` under `sqlglot/`,
- a new unparseable `.py` under `sqlglot/`,
- a patch whose hunks do not match the pristine file,
- a path under `sqlglot/` that is not in the pristine tree.

### Coarse canary (safe mode)

When the precise selection (statement credits + dialect family) is thin, the
selector adds `tests/test_optimizer.py` + `tests/test_executor.py`. This is
the Section-7 safe-mode fallback; it is what guarantees 0 misses on the
samples. `BR_NO_CANARY=1` disables it (used only to measure the precise
rules in isolation).

### Other file types

- `tests/fixtures/**` (`.sql` / `.json`) → fixture map, fallback to
  `tests/test_optimizer.py`.
- `tests/*.py` → test-file map (which tests live in that file).
- A deleted `tests/*.py` → test-file map; a deleted `tests/fixtures/**`
  → fixture map.
- `sqlglot/*.py` **comment-only** → source-reader / doctest tests only.
- Non-`.py` files outside `tests/` and `sqlglot/` → empty selection.

Packing: LPT seed + best single move-or-swap local improvement, k = 1..8,
keep the minimum of (max load + 2 s·k) in integer ms. A non-empty selection
always returns at least one worker so that zero-duration tests are counted.

## Build

`docker build --platform linux/amd64 -t br-entry-s2 entry/`

The Dockerfile downloads the pinned sqlglot tarball with stdlib `urllib`,
extracts to `/opt/sqlglot`, and copies the selector + maps. No `apt`,
no `git`.

## Run

`python -m selector.main` — stdlib only; reads `BR_MAPS`, `BR_PRISTINE`,
`BR_DATA`. Set `BR_DEBUG=1` to write `work/runs/<run>.reasons.jsonl`;
`BR_NO_CANARY=1` to disable the coarse canary.

## Compliance

- No patch→test or edit-kind→test lookup tables; no sample commit ids,
  mutant data, or labels in the selector.
- Maps built from the pinned commit only (`eb11aec`).
- `module_importers.json` is not used as a selection source (it is a
  first-loader artifact, 0–1 entries per module, unsafe as a fallback).
- All selections trace to a line, a statement, the dialect-family union,
  the explicit canary rule, or a full-suite safe fallback.
