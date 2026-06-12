# OrchestrationDrivenWatcher

Long-running watchers reacting to external state. Verification needs popen +
sleep + mutate-then-observe, not a single capture.

## When this fires
- `popen_calls >= 5` (deterministic trigger).
- `args/stdin` pattern: binary reads file list (entr) or command (hwatch),
  stays alive until killed.
- Test names hint: `restart`, `signal`, `sighup`, `interval`, `logfile`,
  `clear`, `watch`.

## Probe layer
1. Spawn with `Popen` in background (do not `communicate` yet).
2. Feed stdin (entr: filenames, one per line, then close) or pass command via
   argv (hwatch: `-n 0.5 echo hi`).
3. Sleep 0.3-1.0s so the poll/kqueue/inotify loop registers.
4. Mutate: `Path('a.txt').write_text(...)`, `os.utime`, `os.unlink`, or let
   hwatch tick.
5. Collect via `communicate(timeout=...)` after SIGTERM or `-z` one-shot.

## Hypothesize patterns
- **entr**: filenames on stdin, runs utility on change. `-r` restart, `-n`
  non-interactive, `-z` one-shot, `-s` shell, `-c` clear, `-d` dir. Heavy on
  signal propagation (SIGHUP kills children) and TTY features (space, q).
- **hwatch**: runs command every `-n` seconds. `-b` batch, `-l` JSON logfile,
  `-d` diff, `--limit` history. More output-format and logfile checks.
- Both have pty-only paths; `-n` is the test-friendly escape.

## Verify layer
Oracle MUST orchestrate; single `run(args)` won't work:

```python
proc = Popen([exe, '-n', '-r', '/bin/sh', '-c', 'echo fired'],
             stdin=PIPE, stdout=PIPE, stderr=PIPE)
proc.stdin.write(b'a.txt\n'); proc.stdin.close()
time.sleep(0.5)
Path('a.txt').write_text('changed')
time.sleep(0.5)
proc.send_signal(signal.SIGTERM)
out, _ = proc.communicate(timeout=3)
assert b'fired' in out
```

hwatch logfile: start `-b -l f.log -n 0.1 echo x`, sleep past 2-3 intervals,
SIGTERM, parse JSON on disk.

## Stop conditions
Verified when: mutation triggers the utility, SIGHUP terminates children
(entr), exit codes propagate (`-s`), logfile contents materialize (hwatch).
Do not chase every TTY corner.

## Common pitfalls
- **Race**: sleep too short -> missed. Bump to 0.5-1.0s, retry once.
- **Hang**: not closing entr's stdin -> waits forever.
- **Leaks**: try/finally with `proc.kill()` + `proc.wait()`.
- **Buffering**: pipe stdout block-buffered; use `-n` or read incrementally
  before signal.
- **FS events**: `/dev/shm` drops kqueue/inotify; use temp dir under cwd.

## Reference tasks
- `eradman__entr`: popen=21, ~685 tests. Signals, restart, ANSI clear, shell
  exit-code.
- `blacknon__hwatch`: popen=8, ~1300 tests. JSON logfile, intervals, history
  limits, keymaps.

## Cross-archetype edges
- High `popen` from pure stdin-piping with no sleep/mutate -> not this; route
  to CliSurfaceAndExitCode.
- Most ~2000 tests in these repos are flat CLI surface. Only the
  orchestration subset belongs here; rest -> CliSurfaceAndExitCode.
- Pure TTY/pty tests -> InteractiveTtyDriver if defined; else skip.
