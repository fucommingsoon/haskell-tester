# MassiveFixtureSuite

One task explodes into thousands of parameterized fixture tests
sharing a template docstring.

## When this fires
- `n_tests >= 1500` AND first 4-5 docstrings near-identical
  ("CATCHES: ... across N+ test cases ...").
- Currently only `universal-ctags__ctags.243595e`.

## Probe layer
- Parser-driven fixture suite, not logic.
- Locate fixture tree (e.g. `Units/`, `test_resources/<lang>/<case>/`).
- Each dir: input source + expected golden tag output.
- Assertions: `other.eq` 62% on `expected_normalized`,
  `returncode.eq 0` 25% — golden-file diff.

## Hypothesize patterns
- ctags = multi-language tag generator (C, Python, Ruby, JS, Make,
  dozens). Each fixture = (language, syntax-feature).
- Output: vi tag lines `name\tfile\taddr;"\tkind[\textfields]`
  or extended JSON.
- Few tests cover options (`--langmap`, `--print-language`, order).

## Verify layer
- Oracle: iterate fixture dirs, run binary, diff vs expected after
  normalization (line order, abs paths, version stamps).
- Sample:
  ```sh
  for d in Units/*.d; do
    ./ctags --options=NONE -o - "$d"/input.* > /tmp/out
    diff <(normalize /tmp/out) "$d/expected.tags" || echo FAIL $d
  done
  ```
- Smoke `--version`, `--list-languages`, `--print-language f.py`.

## Stop conditions
- C, C++, Python, JS, Ruby, Make pass + 10-20 tail fixtures green.
  Option-handling tests pass. Don't chase 100%.

## Common pitfalls
- Hardcoding one language family — coverage is wide.
- Must match vi byte-exactly post normalization; trailing tabs
  and `;"` matter.
- Missing `--options=NONE` lets host `~/.ctags` leak in.
- Template docstring is boilerplate — fixture path is the spec.

## Reference task
- `universal-ctags__ctags.243595e`: 2579 tests, 1665+ fixtures,
  via `test_harvest_units.py::test_units_case`.

## Cross-archetype edges
- `ByteExactGolden` scaled up — same per-fixture diff.
- `n_tests < 500`: use `ByteExactGolden`.
- TUI buffer golden: `TuiScreenSnapshot`.
- Mutates dir not stdout: `FilesystemSideEffect`.
