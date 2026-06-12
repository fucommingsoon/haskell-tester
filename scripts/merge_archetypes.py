"""Merge 20 batch proposals into canonical archetype taxonomy.

Embedded proposals come from 20 subagents that read distill_out/batches/batch_NN.jsonl
and proposed local archetype labels. This script normalizes labels to canonical names
and produces final taxonomy + per-task assignments.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


# Canonical archetype taxonomy (after manual review of 20 batch proposals).
CANONICAL = {
    "ByteExactGolden": "stdout.eq or other.eq dominates; tests compare full bytes against golden fixtures; docstrings cite 'Golden files' / 'EXPECT' / 'byte-for-byte'.",
    "CliSurfaceAndExitCode": "returncode.eq leads + stdout/stderr.contains on help/usage/flag tokens and error grammar; binary judged by exit semantics + diagnostic substrings, not byte output.",
    "FilesystemSideEffect": "other.truthy/contains/eq dominates on file artifacts, generated outputs, dir state; grader inspects produced filesystem state rather than stdout.",
    "TuiScreenSnapshot": "Interactive TUI where assertions check captured screen state via 'other' target + golden screens; returncode.eq is unusually low.",
    "LinterDiagnostic": "Static analyzer / linter: assertions check that specific diagnostic codes/messages fire on prepared inputs; expected literals are rule IDs.",
    "NumericTolerance": "other.gt/ge/lt/le bounds dominate; non-deterministic or numeric output validated by inequality windows rather than byte-exact equality.",
    "OrchestrationDrivenWatcher": "Tool needs multi-step orchestration via popen + sleep + file/state mutation to drive the watcher; popen_calls > 0.",
    "MassiveFixtureSuite": "Single task overwhelms with thousands of parameterized fixture tests sharing a template docstring (parser regressions etc.)",
}


# Per-task canonical assignment derived from 20 batch proposals.
# task_id: archetype
ASSIGNMENTS = {
    # batch 00
    "google__brotli.b3dc9cc": "ByteExactGolden",
    "astro__deadnix.d590041": "FilesystemSideEffect",
    "y2z__monolith.8702e66": "FilesystemSideEffect",
    "sharkdp__bat.f822bd0": "ByteExactGolden",
    "stathissideris__ditaa.f2286c4": "ByteExactGolden",
    "cheat__cheat.b8098dc": "CliSurfaceAndExitCode",
    "antonmedv__walk.bf802ef": "TuiScreenSnapshot",
    "universal-ctags__ctags.243595e": "MassiveFixtureSuite",
    "trasta298__keifu.3331426": "TuiScreenSnapshot",
    "esubaalew__run.0fb9dec": "ByteExactGolden",
    # batch 01
    "miserlou__loop.209927c": "CliSurfaceAndExitCode",
    "rochacbruno__marmite.7d4bc2d": "FilesystemSideEffect",
    "ariga__atlas.6d81150": "CliSurfaceAndExitCode",
    "lz4__lz4.1519f46": "ByteExactGolden",
    "sstadick__hck.b66c751": "ByteExactGolden",
    "tukaani-project__xz.1007bf0": "ByteExactGolden",
    "jesseduffield__lazygit.1d0db51": "FilesystemSideEffect",
    "bellard__quickjs.d7ae12a": "ByteExactGolden",
    "cweill__gotests.2a672c5": "CliSurfaceAndExitCode",
    "brocode__fblog.3b54330": "CliSurfaceAndExitCode",
    # batch 02
    "chirlu__sox.42b3557": "CliSurfaceAndExitCode",
    "stacked-git__stgit.430027d": "CliSurfaceAndExitCode",
    "cslarsen__jp2a.61d205f": "CliSurfaceAndExitCode",
    "rs__curlie.5dfcbb1": "CliSurfaceAndExitCode",
    "zk-org__zk.10d93d5": "CliSurfaceAndExitCode",
    "ecumene__rust-sloth.051c559": "CliSurfaceAndExitCode",
    "skeema__skeema.6a76243": "CliSurfaceAndExitCode",
    "anordal__shellharden.6a6ffd4": "ByteExactGolden",
    "osgeo__proj.75d455c": "NumericTolerance",
    "lua__lua.c6b4848": "ByteExactGolden",
    # batch 03
    "jhspetersson__fselect.c3559ca": "ByteExactGolden",
    "incu6us__goimports-reviser.81bd549": "ByteExactGolden",
    "lh3__seqtk.94e7070": "ByteExactGolden",
    "noborus__trdsql.d8c5ff6": "ByteExactGolden",
    "kisielk__errcheck.dacab89": "ByteExactGolden",
    "antonmedv__fx.86d0d34": "ByteExactGolden",
    "mookid__diffr.2152742": "CliSurfaceAndExitCode",
    "sheepla__pingu.926d475": "CliSurfaceAndExitCode",
    "clog-tool__clog-cli.7066cba": "CliSurfaceAndExitCode",
    "jonas__tig.8334123": "CliSurfaceAndExitCode",
    # batch 04
    "ast-grep__ast-grep.dde0fe0": "ByteExactGolden",
    "orf__gping.26eb5b9": "CliSurfaceAndExitCode",
    "mgdm__htmlq.6e31bc8": "ByteExactGolden",
    "nachoparker__dutree.44e877d": "FilesystemSideEffect",
    "bensadeh__tailspin.6278437": "CliSurfaceAndExitCode",
    "parcel-bundler__lightningcss.aa2ed1e": "ByteExactGolden",
    "jrnxf__thokr.09375ef": "CliSurfaceAndExitCode",
    "hush-shell__hush.560c33a": "ByteExactGolden",
    "unhappychoice__gittype.34b72d0": "TuiScreenSnapshot",
    "mikefarah__yq.602586d": "ByteExactGolden",
    # batch 05
    "nikoladucak__caps-log.2cf2d1e": "CliSurfaceAndExitCode",
    "blacknon__hwatch.edfcb62": "OrchestrationDrivenWatcher",
    "stranger6667__jsonschema.d52e881": "CliSurfaceAndExitCode",
    "rhysd__kiro-editor.4157485": "TuiScreenSnapshot",
    "sqlite__sqlite.839433d": "ByteExactGolden",
    "cmatsuoka__figlet.202a0a8": "ByteExactGolden",
    "dalance__amber.69a0f52": "ByteExactGolden",
    "danmar__cppcheck.0a5b103": "LinterDiagnostic",
    "o2sh__onefetch.e5958ce": "CliSurfaceAndExitCode",
    "samtools__samtools.aa823b5": "CliSurfaceAndExitCode",
    # batch 06
    "kyoh86__richgo.313114f": "ByteExactGolden",
    "duckdb__duckdb.bdb65ec": "ByteExactGolden",
    "mfridman__tparse.2416b4b": "ByteExactGolden",
    "astaxie__bat.17d1080": "CliSurfaceAndExitCode",
    "nuta__nsh.bdd0702": "ByteExactGolden",
    "zevv__duc.a58fa4e": "CliSurfaceAndExitCode",
    "johanneskaufmann__html-to-markdown.3006818": "ByteExactGolden",
    "blake3-team__blake3.15e83a5": "ByteExactGolden",
    "agourlay__zip-password-finder.704700d": "CliSurfaceAndExitCode",
    "boyter__scc.515f91c": "ByteExactGolden",
    # batch 07
    "ajeetdsouza__zoxide.67ca1bc": "CliSurfaceAndExitCode",
    "altdesktop__i3-style.f93821b": "CliSurfaceAndExitCode",
    "thezoraiz__ascii-image-converter.d05a757": "ByteExactGolden",
    "svenstaro__miniserve.8449e8b": "CliSurfaceAndExitCode",
    "kyoheiu__felix.95df390": "CliSurfaceAndExitCode",
    "hatoo__oha.8dc6349": "CliSurfaceAndExitCode",
    "rbakbashev__elfcat.52f8cc7": "CliSurfaceAndExitCode",
    "ivanceras__svgbob.6d00ad9": "ByteExactGolden",
    "php__php-src.c891263": "ByteExactGolden",
    "epistates__treemd.825c6dd": "ByteExactGolden",
    # batch 08
    "drew-alleman__datasurgeon.d257cee": "CliSurfaceAndExitCode",
    "multiprocessio__dsq.c3ae0ba": "ByteExactGolden",
    "rust-embedded__svd2rust.1760b5e": "CliSurfaceAndExitCode",
    "rcoh__angle-grinder.9c2fc88": "ByteExactGolden",
    "ggreer__the_silver_searcher.a61f178": "CliSurfaceAndExitCode",
    "sclevine__yj.8016400": "ByteExactGolden",
    "junegunn__fzf.b56d614": "ByteExactGolden",
    "chmln__handlr.90e78ba": "CliSurfaceAndExitCode",
    "rvben__rumdl.2d75c4d": "LinterDiagnostic",
    "svenstaro__genact.16f96e3": "NumericTolerance",
    # batch 09
    "git-bahn__git-graph.87b4473": "CliSurfaceAndExitCode",
    "simeg__eureka.df3796c": "CliSurfaceAndExitCode",
    "ksxgithub__parallel-disk-usage.96978ed": "CliSurfaceAndExitCode",
    "naggie__dstask.ff57396": "CliSurfaceAndExitCode",
    "byron__dua-cli.8570c15": "CliSurfaceAndExitCode",
    "cordx56__rustowl.655bc5c": "ByteExactGolden",
    "elkowar__pipr.fae0b17": "FilesystemSideEffect",
    "jgm__pandoc.5caad90": "ByteExactGolden",
    "noborus__ov.b96c2ba": "ByteExactGolden",
    "quinn-rs__quinn.bb359cc": "FilesystemSideEffect",
    # batch 10
    "dandavison__delta.acd758f": "ByteExactGolden",
    "wgunderwood__tex-fmt.3f1aef6": "ByteExactGolden",
    "sharkdp__hyperfine.327d5f4": "ByteExactGolden",
    "go-critic__go-critic.9aea378": "LinterDiagnostic",
    "tomarrell__wrapcheck.c058da1": "LinterDiagnostic",
    "oppiliappan__statix.e9df54c": "LinterDiagnostic",
    "foriequal0__git-trim.07c2f50": "CliSurfaceAndExitCode",
    "lymphatus__caesium-clt.a529b2e": "FilesystemSideEffect",
    "eudoxia0__hashcards.48aa136": "CliSurfaceAndExitCode",
    "ninja-build__ninja.cc60300": "FilesystemSideEffect",
    # batch 11
    "xampprocky__tokei.505d648": "FilesystemSideEffect",
    "arthursonzogni__json-tui.17a22b6": "TuiScreenSnapshot",
    "hpjansson__chafa.dd4d4c1": "ByteExactGolden",
    "sharkdp__pastel.b60e899": "ByteExactGolden",
    "madler__pigz.fe4894f": "CliSurfaceAndExitCode",
    "dundee__gdu.ede21d2": "CliSurfaceAndExitCode",
    "konradsz__igrep.aa75630": "TuiScreenSnapshot",
    "arq5x__bedtools2.dd57059": "ByteExactGolden",
    "mibk__dupl.1bf052b": "ByteExactGolden",
    "codesnap-rs__codesnap.f81e4f3": "FilesystemSideEffect",
    # batch 12
    "pls-rs__pls.4e1ae50": "ByteExactGolden",
    "hairyhenderson__gomplate.05eb3aa": "ByteExactGolden",
    "psampaz__go-mod-outdated.bb79367": "ByteExactGolden",
    "wfxr__csview.8ac4de0": "ByteExactGolden",
    "direnv__direnv.02040c7": "CliSurfaceAndExitCode",
    "tinycc__tinycc.9b8765d": "CliSurfaceAndExitCode",
    "nikolassv__bartib.6b9b5ce": "CliSurfaceAndExitCode",
    "facebook__zstd.1168da0": "CliSurfaceAndExitCode",
    "mgechev__revive.201451e": "LinterDiagnostic",
    "gromacs__gromacs.665ea4c": "NumericTolerance",
    # batch 13
    "yassinebridi__serpl.c48a9d7": "CliSurfaceAndExitCode",
    "abishekvashok__cmatrix.5c082c6": "CliSurfaceAndExitCode",
    "ducaale__xh.4a6e44f": "CliSurfaceAndExitCode",
    "hooklift__gowsdl.2a06cec": "CliSurfaceAndExitCode",
    "rust-lang__mdbook.37273ba": "CliSurfaceAndExitCode",
    "gabotechs__dep-tree.60a95a2": "CliSurfaceAndExitCode",
    "riquito__tuc.16fb471": "ByteExactGolden",
    "sibprogrammer__xq.b89f681": "ByteExactGolden",
    "jqlang__jq.b33a763": "ByteExactGolden",
    "sitkevij__hex.61ae69b": "ByteExactGolden",
    # batch 14
    "wfxr__code-minimap.0ddeea5": "CliSurfaceAndExitCode",
    "sayanarijit__xplr.1751065": "CliSurfaceAndExitCode",
    "xorg62__tty-clock.f2f847c": "CliSurfaceAndExitCode",
    "pier-cli__pier.5e1bde9": "CliSurfaceAndExitCode",
    "canop__broot.d6c798e": "CliSurfaceAndExitCode",
    "sharkdp__fd.40d8eb3": "CliSurfaceAndExitCode",
    "ekzhang__bore.8e059cd": "CliSurfaceAndExitCode",
    "rust-ethereum__ethabi.b1710ad": "ByteExactGolden",
    "kaushiksrini__parqeye.8072121": "FilesystemSideEffect",
    "halitechallenge__halite.822cfb6": "FilesystemSideEffect",
    # batch 15
    "doxygen__doxygen.966d98e": "CliSurfaceAndExitCode",
    "crowdagger__crowbook.ea214d7": "CliSurfaceAndExitCode",
    "axodotdev__oranda.27d60c7": "CliSurfaceAndExitCode",
    "ogham__dog.721440b": "CliSurfaceAndExitCode",
    "robertdavidgraham__masscan.b99d433": "CliSurfaceAndExitCode",
    "wintermute-cell__ngrrram.8ea13c3": "CliSurfaceAndExitCode",
    "burntsushi__xsv.f430466": "ByteExactGolden",
    "burntsushi__ripgrep.3b7fd44": "ByteExactGolden",
    "typst__typst.88356d0": "ByteExactGolden",
    "peco__peco.4e58dad": "TuiScreenSnapshot",
    # batch 16
    "nukesor__pueue.8b9d6fe": "CliSurfaceAndExitCode",
    "eradman__entr.8e2e8b4": "OrchestrationDrivenWatcher",
    "tomnomnom__gron.88a6234": "ByteExactGolden",
    "isona__dirble.e2dea9f": "CliSurfaceAndExitCode",
    "ismaelgv__rnr.fc0733b": "CliSurfaceAndExitCode",
    "mkj__dropbear.75f699b": "CliSurfaceAndExitCode",
    "guumaster__hostctl.d6d9699": "CliSurfaceAndExitCode",
    "lfos__calcurse.49180d5": "CliSurfaceAndExitCode",
    "ammarabouzor__tui-journal.2b4540d": "CliSurfaceAndExitCode",
    "ys-l__flamelens.0b4dc33": "TuiScreenSnapshot",
    # batch 17
    "tarka__xcp.5e5b448": "CliSurfaceAndExitCode",
    "chmln__sd.87d1ba5": "ByteExactGolden",
    "raviqqe__muffet.a882908": "CliSurfaceAndExitCode",
    "eliukblau__pixterm.1a93fd5": "CliSurfaceAndExitCode",
    "bootandy__dust.62bf1e1": "CliSurfaceAndExitCode",
    "rs__jplot.2a54bcc": "CliSurfaceAndExitCode",
    "tree-sitter__tree-sitter.5e23cca": "CliSurfaceAndExitCode",
    "luajit__luajit.a553b3d": "ByteExactGolden",
    "segmentio__chamber.5f93f5f": "CliSurfaceAndExitCode",
    "canop__rhit.ae90bcb": "CliSurfaceAndExitCode",
    # batch 18
    "alecthomas__chroma.8d04def": "ByteExactGolden",
    "shashwatah__jot.a92aad8": "FilesystemSideEffect",
    "yaa110__nomino.f892499": "FilesystemSideEffect",
    "oppiliappan__eva.41ae245": "CliSurfaceAndExitCode",
    "sirwart__ripsecrets.34c9e03": "CliSurfaceAndExitCode",
    "jarun__nnn.cb2c535": "TuiScreenSnapshot",
    "htop-dev__htop.523600b": "NumericTolerance",
    "yoav-lavi__melody.f4af9b4": "ByteExactGolden",
    "paradigmxyz__solar.5190d0e": "LinterDiagnostic",
    "sigoden__argc.04a08f1": "ByteExactGolden",
    # batch 19
    "filosottile__age.706dfc1": "ByteExactGolden",
    "alexpovel__srgn.89f943b": "ByteExactGolden",
    "johnkerl__miller.8d85b46": "ByteExactGolden",
    "ffmpeg__ffmpeg.360a402": "ByteExactGolden",
    "sharkdp__hexyl.2e26437": "CliSurfaceAndExitCode",
    "pemistahl__grex.fa3e8ed": "CliSurfaceAndExitCode",
    "facebookresearch__fasttext.1142dc4": "CliSurfaceAndExitCode",
    "osgeo__gdal.0847f12": "FilesystemSideEffect",
    "ip7z__7zip.839151e": "FilesystemSideEffect",
}


def main():
    out_dir = Path("distill_out")
    out_dir.mkdir(exist_ok=True)

    # Sanity check: assignments cover the summaries.
    summaries = [json.loads(l) for l in (out_dir / "summaries.jsonl").open()]
    task_ids = {s["task_id"] for s in summaries}
    assigned = set(ASSIGNMENTS)
    missing_in_assignment = task_ids - assigned
    missing_in_taxonomy = assigned - task_ids

    if missing_in_assignment:
        print(f"WARN: {len(missing_in_assignment)} tasks in summaries.jsonl not assigned:")
        for t in sorted(missing_in_assignment):
            print(f"  {t}")
    if missing_in_taxonomy:
        print(f"WARN: {len(missing_in_taxonomy)} assigned tasks not in summaries.jsonl:")
        for t in sorted(missing_in_taxonomy):
            print(f"  {t}")

    # Aggregate
    by_archetype = defaultdict(list)
    for task, arch in ASSIGNMENTS.items():
        by_archetype[arch].append(task)

    # Write taxonomy JSON
    taxonomy = {
        arch: {
            "definition": CANONICAL[arch],
            "n_tasks": len(tasks),
            "tasks": sorted(tasks),
        }
        for arch, tasks in by_archetype.items()
    }
    # Sort by member count desc
    taxonomy_sorted = dict(
        sorted(taxonomy.items(), key=lambda kv: -kv[1]["n_tasks"])
    )
    (out_dir / "archetype_taxonomy.json").write_text(
        json.dumps(taxonomy_sorted, indent=2, ensure_ascii=False)
    )

    # Write per-task assignment jsonl
    with (out_dir / "task_archetypes.jsonl").open("w") as fh:
        for task in sorted(ASSIGNMENTS):
            fh.write(json.dumps({"task_id": task, "archetype": ASSIGNMENTS[task]}) + "\n")

    # Write human-readable taxonomy markdown
    md_lines = ["# Canonical Archetype Taxonomy", "", f"Source: 20-batch subagent proposals merged.", f"Total tasks classified: {len(ASSIGNMENTS)}", ""]
    md_lines.append("| Archetype | Tasks | % |")
    md_lines.append("|---|---|---|")
    total = len(ASSIGNMENTS)
    for arch, info in taxonomy_sorted.items():
        n = info["n_tasks"]
        md_lines.append(f"| {arch} | {n} | {100*n/total:.1f}% |")
    md_lines.append("")
    for arch, info in taxonomy_sorted.items():
        md_lines.append(f"## {arch} ({info['n_tasks']} tasks)")
        md_lines.append(f"{info['definition']}")
        md_lines.append("")
        for t in info["tasks"]:
            md_lines.append(f"- {t}")
        md_lines.append("")
    (out_dir / "archetype_taxonomy.md").write_text("\n".join(md_lines))

    # Report
    print(f"taxonomy written: {len(taxonomy_sorted)} archetypes, {total} tasks")
    print()
    for arch, info in taxonomy_sorted.items():
        print(f"  {arch:32s} {info['n_tasks']:3d}  ({100*info['n_tasks']/total:5.1f}%)")


if __name__ == "__main__":
    main()
