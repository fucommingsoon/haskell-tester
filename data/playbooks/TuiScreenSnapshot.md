# TuiScreenSnapshot Playbook

Interactive TUI; tests drive a pty, capture grid, diff goldens.

## When this fires

- `returncode.eq` 0.05-0.24 (keifu 0.05, flamelens 0.06,
  nnn 0.09, kiro 0.10, json-tui 0.24).
- `other.contains+truthy+eq` > 0.50 (flamelens 0.71, keifu
  0.69, kiro 0.67, nnn 0.65).
- Files: `test_tui_*.py`, `test_interactive_tmux.py`,
  `test_tmux_tui.py`, `test_tui_navigation.py`.
- Docstrings cite goldens: flamelens `initial_state`,
  `after_arrow_down`; peco `state_empty`, `state_filter_*`;
  gittype `lang_initial`; keifu `initial_commit`;
  igrep `keymap_open`.
- Invocations: tmux new-session/send-keys/capture-pane (kiro)
  or pexpect/pyte (flamelens, peco).

Distinguish FSSideEffect: TUI expected values are screen text
via `(RES/'X.golden').read_text()`. If `other.*` checks
`Path.exists`/file bytes/mtimes -> FSSideEffect.

## Probe layer

Spawn in vt100 emulator at fixed grid. Observed harnesses:
- `tmux new-session -d -s S -x 80 -y 24 <bin> <file>` ->
  `tmux send-keys -t S 'j'` -> `tmux capture-pane -t S -p`
  (kiro `test_tui.py`, `test_tmux_syntax_highlighting.py`).
- `pexpect` + `pyte.Screen` (flamelens
  `test_interactive_tmux.py`, peco `test_tmux_tui.py`).

Send key sequence; read post-render grid as plain text.
Golden: UTF-8 grid dump, ANSI stripped, often
`rstrip('\n')`-normalized (peco `state_empty.golden`).

## Hypothesize patterns

Subtypes: file mgr nnn (`m` multi-select), tree walker walk
(hjkl, columns), viewers json-tui / flamelens flamegraph /
igrep popups / keifu commit graph, filter peco, editor kiro
(Ctrl-W del, Ctrl-Q twice to quit unsaved), trainer gittype.

Keymaps: quit `q`/`Ctrl-Q`/`Escape`; nav arrows/`hjkl`/`j-k`;
action `Space` (gittype save), `Enter`, `m` (nnn), `r/R` (keifu
refresh), `n` (flamelens next), `l` (igrep scroll); help
`?` -> `Escape` (keifu).

## Verify layer

Spawn -> wait-ready -> keys -> capture -> diff golden (mostly
`other.eq`/`other.contains`).

```python
import pexpect, pyte, time
scr = pyte.Screen(80, 24); st = pyte.Stream(scr)
p = pexpect.spawn(bin, [file], dimensions=(24, 80))
p.send('j'); time.sleep(0.2)
st.feed(p.read_nonblocking(65536, timeout=1).decode())
grid = '\n'.join(scr.display)
assert grid == (RES/'after_j.golden').read_text().rstrip('\n')
```

Tmux equivalent: `tmux capture-pane -p` returns same grid.

## Stop conditions

Stop when binary reproduces every golden in the per-task
fixture set AND remaining `returncode.eq`/`stdout.contains`
help/version checks pass; commit.

## Common pitfalls

- Grid size pinned: kiro `80x24`
  (`test_open_file_with_content`) and `120x40`
  (`test_word_deletion`, `test_plain_text_file`). Wrong dims
  shift wrap. igrep notes popup fits normal width so scroll is
  invisible -> match documented size.
- ANSI: strip SGR unless golden keeps it (peco SGR test keeps;
  most strip).
- Render race: capture too early loses first paint. Sleep
  100-300ms after `send-keys` or poll for stable marker
  (footer per keifu
  `test_tui_initial_screen_has_panes_and_footer`).
- Trailing newline: peco `.rstrip('\n')`; mismatch fails
  `other.eq`.
- Env: `TERM=xterm-256color`, `LANG=C.UTF-8`. Kill stale tmux
  sessions.

## Reference tasks

- `ys-l__flamelens.0b4dc33` - cleanest goldens
  (`initial_state`, `after_arrow_up`).
- `peco__peco.4e58dad` - filter-typing `state_*.golden`.
- `rhysd__kiro-editor.4157485` - explicit tmux harness, 80x24
  and 120x40, Ctrl-key editor commands.
- `jarun__nnn.cb2c535` - file-mgr nav, `screen1`/`screen2`
  diffs, highest `other.truthy` (0.39).
- `trasta298__keifu.3331426` - panes+footer screen check,
  Escape help-popup dismiss, `initial_commit.golden`.

## Cross-archetype edges

- High `returncode.eq` + `other.*` on `Path.exists`/file
  bytes/mtimes -> FSSideEffect.
- High `stdout.contains` of help/usage (json-tui, keifu, igrep,
  walk) is normal CLI surface; only TUI-named tests need pty.
  Run non-TUI subset with plain `subprocess.run`.
- gittype `test_theme_save_persists_to_config` = TUI key +
  config write: pty then verify file -> hybrid w/ FSSideEffect.
