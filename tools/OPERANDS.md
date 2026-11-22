The operand profile is derived from the complete pristine test suite at
`eb11aec4be8cb2122afe713a4816662c3f0fb2fa`. It contains source hashes, comparison
coordinates and observed operand type pairs, with no patch inputs or outcomes.

Regenerate from the repository root:

```
docker build -f tools/Dockerfile.operands -t br-operand-builder .
docker run --rm --cpus 1 --memory 2g -v /absolute/output:/profileout br-operand-builder
```

Copy `operand_profiles.json.gz` into `maps/`. Use a fresh output directory for
each complete run. The generator rejects a failed suite or any instrumented
process that started recording but did not flush its records. Spawn workers use
the same pristine compile hook and register multiprocessing exit finalizers.
Original source files remain unchanged, including for source-reading tests.

The runtime rule defaults on; `BR_OPERANDS=0` disables it. A missing or incomplete
map retains ordinary selection. Only one nonchained same-polarity comparison
swap in a single-file patch is accepted, with exact surrounding AST and original source
hash. A second semantic change anywhere in that file prevents the rule.

Every observed pair must establish applicability and identity/equality agreement.
Allowed cases are None versus exact builtin or identity-only classes, and members
of the same normal Enum class with standard object/str/int comparison methods.
Every canonical Enum member pair is also checked. Custom rich comparisons and
builtin subclasses are excluded. Unobserved or unsafe sites retain selection.
Source readers, unknown loaders and process-wide heap observers always retain
their existing selection signals.

The corrected builder imports unittest and pytest before every SQLGlot import,
including generated sitecustomize in spawn workers. Every instrumented process
asserts actual expressions.core.UNITTEST is True and emits a validated PID
marker. Merging fails if any recording process lacks that marker. Old profiles
without verification_context metadata are conservatively ignored at runtime.
