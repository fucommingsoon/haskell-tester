# LinterDiagnostic Playbook

Static analyzer / linter rebuild. Tests feed input and assert a
specific diagnostic code fires (or stays silent). Expected literals
are rule IDs.

## When this fires
- Test files: `test_lints.py`, `test_harvest_*`, `test_rules_*`,
  `test_checker*`, `test_*_gaps.py`, `test_formatters.py`.
- Rule-ID literals: `MD024/MD020/MD013` (rumdl); `rangeExprCopy`,
  `badCond`, `badCall`, `appendAssign`, `ruleguard`,
  `commentFormatting`, `dupOption` (go-critic); `memleak`,
  `severity=` (cppcheck); W18/W23 (statix). Test names embed rule:
  `test_md020_*`, `test_w18_*`.
- `other.contains`/`other.eq` dominate (0.16-0.43): asserts inspect a
  parsed `failures`/`output`, not raw stdout.
- `returncode.eq 0` heavy (0.16-0.28): clean exits 0; dirty often
  non-zero (1 rumdl, 3 wrapcheck).
- Heavy `args/no-stdin` (200-990); some stdin mode (statix `single
  --stdin`, solar `-`, rumdl).

## Probe layer
- Enumerate catalog: `--list` / `list` / `rule` / `--errorlist`
  (cppcheck) / `-list` (revive). Inspect IDs + ordering.
- Feed a known-bad fixture from `testdata/`/`.golden`; observe ID
  format, `file:line:col`, severity tag.
- Probe formatters: `-json`, `--output-format json`, rustc-json
  (solar), stylish, default. JSON tests assert `span.byte_start`,
  `confidence`, `severity`.
- Probe `--explain <RULE>` (statix).

## Hypothesize patterns
Tools: **go-critic, revive, wrapcheck** (Go AST), **rumdl** (Markdown
MD####), **statix** (Nix W##), **cppcheck** (C/C++ severity=+id=),
**solar** (Solidity rustc-style).
- IDs: `MD\d{3}`, `W\d{2}`, camelCase (Go), snake_case, word
  (`memleak`).
- Default formatter: `file:line:col: severity: msg [ruleId]`, one per
  line; stylish groups by file + summary.
- Exit codes: 0 clean, 1 findings, 2+ tool error
  (`unsupported flag value: -V=true`, `flag needs an argument`).
- Default ignore lists matter (wrapcheck ignores `errors.New`,
  `fmt.Errorf`; rumdl `--no-config`).
- Stdin: explicit flag (`--stdin`, `-`) + maybe `--position 1,4`.

## Verify layer
- Per-rule oracle: drop fixture triggering R, run
  `executable check fixture`, parse into `failures`, assert
  `rule_id` present (or absent for negative tests).
- Golden (`*.golden`, `*_err.txt`): `other.eq` of
  `(RESOURCES / '*.golden').read_text()` — exact parsed match.
- Negative (`stdout.not_contains MD051`) guards false positives.
- Test clean-vs-dirty exit codes separately from finding count.

## Stop conditions
- Targeted rule families implemented (rumdl ~40 MD rules,
  go-critic ~80).
- Exit codes: 0 clean, non-zero on findings; tool errors distinct.
- `--list`/`--errorlist` emits full catalog with stable order.
- JSON formatter matches schema (confidence, position, severity).

## Common pitfalls
- Don't auto-fix when test expects detection (rumdl `_fix_` in name
  = fix mode).
- Rule ID typos silently break — exact casing (`commentFormatting`).
- Default ignore lists apply with no config (wrapcheck).
- Recurse AST: detect at every depth (revive
  `ifelseif_branches_nested`).
- Nonexistent path: go-critic silently exits 0; symlinks to .go must
  be followed. Match upstream per task.
- Stdin without position flag may differ from file mode.
- JSON span consistency: `byte_start` agrees with `line_start/
  column_start` (solar rustc-json).

## Reference tasks
- `rvben__rumdl` (4781) — MD#### catalog, fix-vs-detect split.
- `danmar__cppcheck` (2550) — severity + XML/text, `--errorlist`.
- `paradigmxyz__solar` (2527) — rustc-json spans, stdin imports.
- `oppiliappan__statix` (983) — W## codes, `single --stdin`.
- `go-critic` (904) — camelCase IDs, symlink handling.

## Cross-archetype edges
- Asserts = `stdout.eq` of full golden bytes (not parsed substring):
  route to **ByteExactGolden**.
- Failures concentrate in `stderr.contains "Usage:"` /
  `unsupported flag value` / `flag needs an argument` with
  `returncode.ne 0` on invalid flags: route to **CliSurfaceAndExitCode**.
- JSON schema is load-bearing oracle (tests parse JSON, walk fields):
  consider **StructuredOutputContract**.
