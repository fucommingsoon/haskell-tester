# NumericTolerance Playbook

`other.gt/ge/lt/le` bounds dominate; non-deterministic or numeric output
validated by inequalities.

## When this fires
- Signal: `other.gt + other.ge + other.lt + other.le >= 0.20`
  - proj: ge+le = 0.372 (paired bands); htop: gt+ge = 0.438 (counters);
    genact: ge+gt = 0.351 (event counts); gromacs: gt 0.068 (mixed w/ contains).
- Splits: scientific (proj, gromacs); non-det sim (genact); monitor (htop).

## Probe layer
- Run deterministic input; observe output range across multiple runs.
- proj/gromacs: transform known reference point/structure, compare to docs.
- genact: count event/line types, check shape (variety, dedup).
- htop: snapshot at known time (`-n 2`), verify within plausible range.

## Hypothesize patterns
- Tolerances = inequalities: `value > 100`, `0 <= count <= 5`,
  `|out - expected| <= tol`.
- Paired `ge` + `le` (proj 0.186/0.186) = symmetric band around reference.
  proj uses `-f '%.12f'` then `delta >= 0 AND delta <= test.tolerance`.
- Often paired with `other.truthy` / `is_not None` (proj 0.376, genact
  0.186): "must produce output AND be in band".
- htop: `-n N` then `returncode==0` + counter `>= 0` or `> threshold`.
- genact: `count >= K` (K small: 1,2,3,5) for variety, not equality.

## Verify layer
- proj-like: parse `%.12f` columns, `|got - expected| <= tol` per row.
- gromacs-like: histogram bin count, normhisto `sum(probs)~=1`, file
  non-empty, returncode 0.
- genact-like: run >=10x, distinct outputs >5; per-run event counts
  `>= threshold`; verify dedup of consecutive lines.
- htop-like: snapshot fixed `-n`, counters non-negative and bounded.

## Stop conditions
- Tolerance windows hold across N independent inputs without drift.
- Variety/count thresholds met across reruns (genact).
- Snapshot bounds hold across 3+ runs (htop).

## Common pitfalls
- Hardcoding nominal values that pass once but vary on rerun.
- Forgetting to seed RNG (gromacs `-seed`, genact module).
- Locale number format (`1.5` vs `1,5`) — force `LC_ALL=C`.
- Mis-reading `other.le tolerance` as expected value — it's a *bound*.
- htop `-n 5.5` (float) should *reject* — bound != "accept any number".

## Reference tasks (all 4)
- **proj** (`osgeo__proj.75d455c`, 7160): coord projection; `test_gie_case`
  asserts `delta >= 0` + `delta <= test.tolerance` — canonical paired band.
- **gromacs** (`gromacs__gromacs.665ea4c`, 1382): MD; `other.gt 100` on
  histogram point counts; normhisto sum; XVG data counts.
- **genact** (`svenstaro__genact.16f96e3`, 237): fake-activity sim;
  `other.ge {2,3,5}` for variety / monotonic progress (`gt first_progress`).
- **htop** (`htop-dev__htop.523600b`, 1200): monitor; `other.gt 2000` for
  stress-iteration volume; `other.ge 0` non-negative counters.

## Cross-archetype edges
- Byte-exact numeric strings (`stdout.eq`/`contains` on a number, no
  inequality) → **ByteExactGolden**. proj has 0.007 `stdout.eq` slice.
- Dominant `other.contains` on structured fields (gromacs 0.216) →
  **StructuredOutput** overlay; tolerance stays secondary.
