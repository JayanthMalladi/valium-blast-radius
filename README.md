# Blast Radius submission

## Approach

The selector reads the patch and classifies what changed, using maps built
from the pinned sqlglot commit (never from sample answers or test labels):

1. **Line coverage map** — per-test line coverage via `coverage.py
   --cov-context=test` on the pinned commit. Each changed line maps to the
   tests that executed it.
2. **Import map** — module-level code and class-body edits: tests that first
   import that module.
3. **Fixture map** — `tests/fixtures/**` .sql/.json files → the tests that
   read them (audit hook on `open`).
4. **Source-reader tests** — tests that read module source text (doctests in
   `test_docs.py`, etc.), needed when a docstring change is the only diff.
5. **Import-break fallback** — `ast.parse` the patched file; on failure,
   select every test that loads the module.
6. **LPT packing** — try k=1..8 workers, longest-processing-time first, keep
   the minimum of (busiest worker + 2s·k).

All maps are plain JSON committed in the repo; the Dockerfile rebuilds them
during the build step from the pinned commit. The runtime selector is
stdlib-only, reads maps once at startup, and keeps total CPU under 1 s.

## Build

The Dockerfile:
1. Installs `requirements.lock` (the exact labeled environment)
2. Clones sqlglot at `eb11aec4be8cb2122afe713a4816662c3f0fb2fa`
3. Runs the full suite once with the audit plugin + line coverage
4. Compacts the JSON maps and keeps them
5. The run image ships: selector package, maps, pristine sqlglot source

## Run

`python -m selector.main` reads `/data`, writes one JSON line per commit
to stdout, logs to stderr. The whole batch completes well under the 3-minute
limit on 2 cores.

## Rebuilding maps

The maps are built by `tools/build_maps.py` and can be regenerated from
the pinned commit in one command. They do not depend on any sample data.

## Compliance

- No patch→test or edit-kind→test lookup tables
- No sample commit ids in the selector code
- Maps built from the pinned commit only
- All versions pinned in `requirements.lock`
- Dockerfile at repo top, no submodules, no Git LFS
- Repo well under 20 MB
