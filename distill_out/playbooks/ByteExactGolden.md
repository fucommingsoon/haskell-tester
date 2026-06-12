# ByteExactGolden Playbook

## When this fires (recognition signals)

Trigger when `stdout.eq` + `other.eq` dominate AND docstrings cite goldens / `.read_text()`.

Evidence (25 sampled tasks):
- `stdout.eq` OR `other.eq` >= 0.10: `esubaalew__run` 0.257, `blake3` 0.215, `hush-shell` 0.191 (stdout.eq); `ast-grep` 0.319, `xsv` 0.259, `yj` 0.259, `ffmpeg` 0.250 (other.eq).
- Docstrings cite `Golden files:` / `(RESOURCES / 'X.golden').read_text()`: `blake3` (`input_64k_len64.golden`), `tex-fmt` (`standalone_comment.golden`), `bat` (`multi_range_no_snip.golden`), `errcheck` (`simple_unchecked.golden`), `srgn` (`german_basic.golden`).
- Samples are payload bytes not flag tokens: `ethabi` `b'00...0f4240'`; `lz4` `b'hello world\n'`; `yj` `b'"inner_y"'`.

Distinguishing:
- **vs CliSurfaceAndExitCode**: that one has `stdout.contains`/`stderr.contains` dominant + flag-token samples. Borderline `chafa` stdout.eq 0.077 + `b'--help'` → CliSurface.
- **vs FilesystemSideEffect**: that one has `other.eq` over SUT-written files + `popen_calls` to `cat`/`ls`. All 25 here have `popen_calls: 0`; goldens are test fixtures.

## Probe layer (cheap exploration, seconds-scale)

1. Trivial input first:
   - Hash: `printf 'a' | ./executable` (blake3 1-byte).
   - Interpreter: `./executable -i '{{ math.AddInt 100 200 }}'` → `b'300'` (gomplate).
   - Converter: `echo '{"a":1}' | ./executable -jy` (yj).
   - Formatter: `echo '\item x' | ./executable --stdin --print` (tex-fmt).
2. Locate goldens: tests use `RESOURCES / 'NAME.golden'` under `eval/test_resources/` (`ast-grep`: `eval/test_resources/test_injection/bad_rule_error.golden`).
3. Canonical inputs from samples: lz4 `b'hello world\n'`, `b'ABCDEFGHIJKLMNOPQ'`; hush-shell `b'Hello World'`; ethabi uint256(1000000) → `0...0f4240`.

## Hypothesize patterns

Categories:
- Hashers: `blake3` (64-byte hex, XOF length/seek).
- Codecs: `lz4` (`.lz4` frame), `ffmpeg` (FATE refs).
- Interpreters: `php-src` (`.phpt --EXPECT--`), `duckdb`, `sqlite`, `hush-shell`, `esubaalew__run`, `melody`, `gomplate`.
- Formatters: `tex-fmt`, `goimports-reviser`, `srgn`.
- Converters: `yj`, `ethabi`, `ascii-image-converter`, `chafa`.
- CLI scanners: `bat`, `ripgrep`, `xsv`, `dupl`, `errcheck`, `go-mod-outdated`, `ast-grep`, `age`.

Determinism: byte-exact incl. whitespace + trailing newline. `hush-shell` literal `"4\n3\n3\n2\n"`; `xsv` `b'\r\n'`; ascii-image-converter PNG magic `b'\x89PNG\r\n\x1a\n'`.

Encoding: UTF-8 dominant (`bat` `b'\xe2\x90\x83'`; `srgn` `ae→ä`). BOM-aware (`ripgrep` `b'\xff\xfe'`). Locale shifts `ffmpeg` FATE / `duckdb` decimals — pin `LC_ALL=C`.

## Verify layer (agent's oracle templates)

MUST be byte-level diff, never regex/substring.

```
# stdin (hush-shell, yj, melody)
diff <(./executable < fixed_input.txt) expected.golden && echo PASS
# args (lz4, blake3, ethabi)
diff <(./executable --length 64 < input_64k) input_64k_len64.golden
# binary (PNG, .lz4 frame)
cmp ./out.bin expected.bin && echo PASS
# round-trip (lz4, age)
./executable input | ./executable -d | cmp - input
```

Whitespace/newline traps:
- Trailing `\n`: `xsv` `b'2\n'` vs `b'2'` — use `cmp`, no stripping.
- CRLF: `xsv` `b'\r\n'` — guard goldens from git autocrlf.
- Empty: `b''` in `melody`, `blake3`, `chafa` — assert exit code AND zero-length stdout.

## Stop conditions

Commit when:
1. Three independent short inputs reproduce byte-exact (`hello world\n`, `ABCDEFGHIJKLMNOP`, empty stdin for lz4).
2. One edge case verified: empty (`melody test_whitespace_only_input` → `b''`), binary boundary (`blake3 test_very_small_file_1_byte`), round-trip (`lz4 test_mixed_binary_text_data`).
3. Exit codes match alongside bytes — `errcheck` returns 1 with stdout byte-matching `simple_unchecked.golden`.

## Common pitfalls

- Substring/regex oracle silently passes byte-shifted output. Use `cmp`/`diff` only.
- Locale: `ffmpeg` FATE / `duckdb` decimals drift; pin `LC_ALL=C`.
- Trailing newline: `ethabi` uses `.read_text().strip()`; others compare unstripped — check per task.
- Binary text-mode: `blake3 test_binary_file_content`, ascii-image-converter PNG corrupt via text-mode pipes.
- Map order: `yj` asserts literal `zebra/apple/mango/banana` order — insertion order is contract.

## Reference tasks (anchors)

- `blake3.15e83a5` — hasher; XOF length/seek/threading byte-exact.
- `lz4.1519f46` — compressor; `.lz4` frame golden + round-trip.
- `yj.8016400` — converter; YAML/JSON/HCL/TOML map-order byte-exact.
- `tex-fmt.3f1aef6` — formatter; `tabsize2.golden`, `standalone_comment.golden`.
- `hush.560c33a` — interpreter; `nested_dict.golden`, `"4\n3\n3\n2\n"`.

## Cross-archetype edges

- `stdout.eq` 0.08–0.15 + flag-token samples (`--help`, `Usage:`) → CliSurfaceAndExitCode (`chafa.dd4d4c1` stdout.eq 0.077 + `b'--help'`).
- `other.eq` dominates + goldens are SUT-written paths → FilesystemSideEffect. None of 25 match (`popen_calls: 0`).
- `stdout.contains` >> `stdout.eq` + goldens are huge logs sampled by line (`php-src` 0.314 vs 0.095; `duckdb` 0.007) → hybrid; keep ByteExactGolden primary.
