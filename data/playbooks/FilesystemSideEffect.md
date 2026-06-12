# FilesystemSideEffect Playbook

## When this fires
- `other.*` family dominates (truthy+contains+eq ≥ 0.45), stdout share low, and `_expr` payloads read disk: `output.read_text()` (pipr-fae0b17, monolith-8702e66), `outfile.read_text()` (pipr), sidecar `(RESOURCES/'X.golden').read_text()` (ninja-cc60300, dutree-44e877d, tokei-505d648).
- Invocations carry a write target: `-o`/`--output`/`--out-file`/output-dir (codesnap-f81e4f3, caesium-clt-a529b2e `-o out_dir`, 7zip `a -tzip archive src`).
- Two-stage `invs`: writes then reads (7zip `a` then `t`; lazygit-1d0db51 clone then open).
- Counts over produced files (tokei `report['code']/'comments'/'blanks'`; gdal-0847f12 `feat['properties']`; parqeye-8072121 parquet schema).

Distinguish from **CliSurfaceAndExitCode**: there `other.*` targets `help_text`/`stdout.lower()` with `--help`/`--version` invocations; here payloads read disk and invocations carry a write target.

## Probe layer
1. `WORK=$(mktemp -d)`; copy fixtures from `eval/test_resources/` into `$WORK/in`. `find $WORK -printf '%p %m %s %y\n' | sort > pre.snap`.
2. Run binary writing into `$WORK/out`; capture stdout/stderr/exitcode separately.
3. `post.snap` same way; `md5sum $(find $WORK/out -type f)`; `ls -la` for symlink targets.
4. Look for: new files under `out/`, in-place rewrites under `in/` (deadnix-d590041 edit mode, nomino-f892499 rename, jot-a92aad8 vault CRUD), exec bit on extracted archive members (7zip), symlink target preservation (dutree broken-symlink).

## Hypothesize patterns
Tool families:
- Archiver/compressor: 7zip-839151e, caesium-clt-a529b2e.
- Static-site/bundler: marmite-7d4bc2d (HTML+JSON feeds), monolith-8702e66 (single bundle).
- In-place mutator: nomino-f892499, deadnix-d590041, jot-a92aad8.
- Build: ninja-cc60300 (`.o`, deps log).
- Scientific/data: gdal-0847f12 (tif/geojson), tokei-505d648 (json report), halite-822cfb6 (`.hlt` replay), parqeye-8072121, codesnap-f81e4f3 (svg/png).
- Renderer+TUI mix: pipr-fae0b17, quinn-rs-bb359cc, lazygit-1d0db51.

Effects: new file at exact path, in-place rewrite, generated asset tree, archive members with mode bits, `.hlt/.log/.json` sidecars, git HEAD/ref movement.

## Verify layer
- Tree diff: `(cd $WORK && find out -type f | sort | xargs md5sum) > actual.md5; diff actual.md5 golden.md5`.
- Per-file match mirrors tests: `read_text()` vs `RESOURCES/*.golden` byte-exact (ninja, dutree `single_file.golden`, jot `set_editor_special_chars.golden`, halite `two_bots_quiet.golden`).
- Mode-aware: `stat -f '%Sp %z %N' $WORK/out/*` (7zip BCJ2 stripped exec → 14472 bytes + +x).
- In-place: `diff -r in.before/ in/`.
- Structured outputs: parse JSON, compare keys (tokei `-o json` → `code/comments/blanks/lines`; parqeye fields like `delta_byte_array`).

## Stop conditions
Commit when, per sampled test: (a) expected files exist at expected paths with matching md5 (or matching parsed structure for JSON), (b) mode bits and symlink targets match where the test reads them, (c) returncode matches. Secondary stdout/screen checks still must pass byte-exact.

## Common pitfalls
- Mode bits: 7zip preserves exec on extracts; caesium preserves source mtime.
- Symlinks: dutree `broken_symlink_color` needs an actually broken link — do not resolve.
- Hidden/tmp pollution: dutree `-H` excludes dotfiles; tokei honours `.gitignore`; marmite emits `.json`/`.xml` next to HTML.
- Tilde: pipr `--out-file ~/x` must hit `$HOME/x`, not literal `~`.
- Trailing newlines: pipr `state_infile_trailing_newlines.golden` is byte-exact.
- FS encoding: nomino unicode (`café_renamed`, `emoji_😀.txt`) — pass raw bytes to `rename(2)`.
- Overwrite policy: caesium `--overwrite all`, nomino `-w`, pipr `--out-file`; without flag, refuse or prepend (nomino `_` prefix).
- Timestamped output: monolith golden uses `normalize_timestamp(golden)` — replicate.
- Two-call state: 7zip create+test, lazygit clone+open — state must persist between calls.

## Reference tasks
- `ninja-build__ninja.cc60300` — build; `.o`/deps-log; implicit-dep rebuild asserts on `output.read_text()`.
- `ip7z__7zip.839151e` — archiver; two-stage `a`+`t`; exact archive size + extracted exec bit.
- `nachoparker__dutree.44e877d` — directory walk; golden tree exact-match incl. symlink color (`or=31`).
- `yaa110__nomino.f892499` — in-place rename; collision policy; unicode FS check.
- `rochacbruno__marmite.7d4bc2d` — static site; multi-file output tree (HTML+JSON feeds + duplicate-slug stderr).

## Cross-archetype edges
- If `_expr` reads are mostly `screen`/`pyte`/curses (pipr TUI, lazygit `initial_screen`/`after_screen`, parqeye TUI, codesnap `golden.svg`) with no new disk files → **TuiScreenSnapshot**.
- If `returncode.eq` ≥ 0.30 and `other.*` targets `help_text`/`stdout.lower()` (`Usage:`, `--help`) with no output-dir in invocations → **CliSurfaceAndExitCode** (pipr/quinn/jot/codesnap subpopulations — route per test).
- If asserts are mostly `stdout.eq` against a golden blob with no file artifact (much of dutree) → companion **GoldenStdoutMatch**; share the golden-loading mechanic.
