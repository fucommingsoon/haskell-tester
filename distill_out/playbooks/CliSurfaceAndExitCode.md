# Playbook — CliSurfaceAndExitCode

Binary judged by **exit codes + diagnostic substrings on help/usage/error**, not byte-exact stdout.

## When this fires

- `returncode.eq` top in 23/25, share 0.22–0.44 (`eva` 0.437, `calcurse` 0.434, `sox` 0.395).
- `stdout.contains`/`stderr.contains`/`other.contains` on flag tokens co-dominate.
- `stdout.eq` <0.10 (`pier` 0.037, `tig` 0.017); often empty `b''` on errors (`dep-tree test_explain_non_matching_glob_is_error`).
- Expected literals = flag tokens (`b'--help'`, `b'-V'`, `b'-a, --acc <0-100>'`, `b'--minPasswordLen'`) + headers (`b'Usage:'`, `b'USAGE:'`, `b'Options:'`, `b'Available Commands:'`, `b'Commands:'`, `b'Flags:'`, `b'Examples:'`).
- `no-args/no-stdin` in nearly every task (`hostctl test_no_subcommand_shows_help`: rc=0 + `b'Available Commands:'`).

**vs ByteExactGolden**: pivot if `stdout.eq` to `(RESOURCES/'*.golden')` >~25%. **vs FilesystemSideEffect**: pivot if asserts inspect files binary wrote (`output_file.exists()`, `read_bytes()` of `-o` target).

## Probe layer

- `./bin` — help+0 (`hostctl`) or usage+nonzero (`mdbook test_build_missing_book_toml`)?
- `./bin --help` — headers + flags (`thokr` `b'USAGE:'`; `zip-password-finder` `usage:`).
- `./bin -h` — short alias (`zip-password-finder test_short_help_flag_works`).
- `./bin --version`/`-V`/`-v` — `tig` `b'tig version'`; `eureka -V`.
- `./bin --invalid-flag` — `thokr`/`eureka` rc=2; `dep-tree` `b'unknown flag'`; `zstd` `b'Incorrect parameter'`.
- `./bin <sub> --help` — differs from main (`hostctl test_subcommand_help_differs_from_main_help`; `stgit test_help_short_is_summary_variant`).
- `./bin file.x --help` — position-independent (`jp2a test_help_accessible_anywhere`).

Record: rc, header casing, long+short pairs (`-G, --grep`), unknown-flag template.

## Hypothesize

Two shapes: (1) **Subcommand tree** — `hostctl`, `stgit`, `dep-tree`, `mdbook`, `samtools`, `pier`, `tig`; no-args → `Available Commands:`. (2) **Single-mode flag bag** — `jp2a`, `zstd`, `curlie`, `pigz`, `sox`, `oha`, `eva`, `muffet`, `bartib`, `tailspin`, `ngrrram`, `eureka`, `thokr`.

**Flags:** help/version; `-v`/`--verbose` (`pier test_verbose_flag_variants` both positions); I/O `-c` (`pigz`), `-o` (`oha`/`zstd`), `-i` (`zip-password-finder`), `-f` (`bartib`), `-D` (`calcurse`); bounded `-a, --acc <0-100>` (`ngrrram`), `--minPasswordLen` (`zip-password-finder`); format `--color=never` (`muffet`), `--json` (`dep-tree`).

**Errors:** `b'unknown flag'` (`dep-tree`); `b'Incorrect parameter: --fast=invalid'` (`zstd`); `b'cannot open'` (`samtools`); `b'abort: cannot provide files in GZIP environment variable'` (`pigz`); `b'Invalid argument for combi'`, `b'File not found'` (`ngrrram`); `b'does not match'` (`dep-tree`). `xplr`/`bartib` assert stderr **non-empty** on failure.

**Exit codes:** `0` help/version; `1` runtime (`pier test_config_file_not_found_with_path`, `muffet`); `2` clap (`thokr test_invalid_numeric_value`, `eureka test_invalid_flag`); sets `tailspin` `[0,1,2]`, `tig`/`zip-password-finder` `[0,1]`. **Default rc=1 if README silent.**

## Verify (own oracles)

- `./bin --help` rc=0 AND stdout matches `usage:|options:|commands:`.
- `./bin -h` == `./bin --help`.
- `./bin --not-a-flag`: rc≠0 AND stderr matches `unknown|invalid|unrecognized|incorrect`.
- Each `sub`: `./bin $sub --help` rc=0 AND output ≠ main.
- `./bin file.x --help` rc=0 (jp2a).
- Out-of-range bounded numeric: stderr matches `invalid|out of range`, rc≠0.

## Stop conditions

Submit when: (1) `--help` rc=0 lists every README flag with correct header; (2) `--version` rc=0 if documented; (3) ≥3 error paths rc≠0 + non-empty stderr matching grammar; (4) each subcommand `--help` rc=0, output ≠ main; (5) no-args matches README. Don't chase byte-exact help unless README ships a fixture (`ngrrram test_full_help_matches_fixture_exactly`).

## Pitfalls

- Don't optimize for `stdout.eq` (<10% share).
- Don't conflate rc 1 vs 2: clap → 2; cobra → 1.
- Don't drop short flags (`-h`/`-V`/`-v`/`-c`/`-o`/`-f` tested).
- Don't emit empty stderr on error (`xplr`, `bartib`).
- Don't emit ANSI to file (`oha test_output_to_file_text`; `--color=never`).
- Don't reject `--help` after positionals (`jp2a` `file.jpg --help` rc=0).
- Header casing literal: `Usage:` (`pier`/`zstd`/`stgit`) vs `USAGE:` (`thokr`) vs `Options:` (`tailspin`) vs `Available Commands:` (`hostctl`).
- Subcommand help differs from main (`hostctl`, `stgit`).

## Reference tasks

- `guumaster__hostctl.d6d9699` — cobra tree, subcommand-help differs.
- `agourlay__zip-password-finder.704700d` — clap, `-h` asserts `usage:`, min/max errors.
- `gabotechs__dep-tree.60a95a2` — cobra `b'unknown flag'`, rc=1+empty stdout on glob miss.
- `jrnxf__thokr.09375ef` — clap rc=2 invalid numeric, `b'USAGE:'`, `b'possible values'`.
- `wintermute-cell__ngrrram.8ea13c3` — bounded ranges + fixture-exact help.

## Cross-archetype edges

- → **ByteExactGolden** if `stdout.eq` to `(RESOURCES/'*.golden')` dominates (`rust-sloth`, `gotests union_constraints.golden`, `eva test_factorial_of_expression`, `tailspin multiple_regexes_output.golden`).
- → **FilesystemSideEffect** if asserts inspect files binary wrote (`output_file.exists()`, `--render-path` — `dep-tree test_entropy_custom_render_path`, `mdbook test_serve_static_css_assets`).
- **Stay** when fingerprint is `returncode.eq <0|1|2>` + `stdout.contains <flag|header>` + `stderr.contains <error-phrase>` + `other.contains <flag>`.
