"""Command line entry point: `python -m oregraph <command>`."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

#: Upstream bug behind the PYTHONHASHSEED relaunch in main(). graphify's
#: build_from_json drops edges depending on string-hash iteration order. If you
#: are here to remove the relaunch, check this issue is fixed in the pinned
#: graphify version first - and re-run the two-build comparison in
#: docs/RELABELLING.md before trusting the result.
UPSTREAM_ISSUE = "https://github.com/Graphify-Labs/graphify/issues/2817"

from . import chunks as chunkmod
from . import config as configmod
from .chunks import ALL_CHUNKS, BY_NAME, CODE_CHUNKS, SEMANTIC


def _cfg(args):
    try:
        cfg = configmod.load(engine=getattr(args, "engine", None),
                             out=getattr(args, "out", None))
    except configmod.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
    warn = configmod.warn_if_synced(cfg.out)
    if warn:
        print(warn, file=sys.stderr)
    return cfg


def _require_graphify(cfg):
    if not configmod.check_graphify_importable(cfg.python):
        print("error: graphify is not importable by this interpreter.\n"
              f"  interpreter: {cfg.python}\n"
              "  fix: pip install graphifyy", file=sys.stderr)
        raise SystemExit(2)


# ---------------------------------------------------------------------------


def cmd_info(args):
    cfg = _cfg(args)
    print(f"Engine repo : {cfg.engine}")
    print(f"Graph output: {cfg.out}")
    print(f"Interpreter : {cfg.python}")
    # Only shown when it resolves. Nothing depends on the console script any
    # more - the MCP config binds to this interpreter via `-m graphify.serve` -
    # so printing "(not on PATH)" reported a failure that wasn't one, in the
    # first command a new user runs.
    if cfg.graphify_cli:
        print(f"graphify CLI: {cfg.graphify_cli}")
    print(f"graphify lib: {'importable' if configmod.check_graphify_importable(cfg.python) else 'NOT INSTALLED - pip install graphifyy'}")
    print(f"\nChunks: {len(CODE_CHUNKS)} code, {len(SEMANTIC)} semantic")
    for c in ALL_CHUNKS:
        built = "built" if cfg.module_graph(c.name).exists() else "-"
        lab = "labelled" if cfg.labels_for(c.name) else "unlabelled"
        print(f"  {c.name:34s} {c.kind:9s} {lab:10s} {built}")


def cmd_coverage(args):
    from .coverage import audit, format_report
    cfg = _cfg(args)
    print(format_report(audit(cfg.engine)))


def cmd_build(args):
    from .build_ast import build as build_code
    from .build_semantic import build as build_sem
    cfg = _cfg(args)
    _require_graphify(cfg)

    selected = [BY_NAME[n] for n in args.only] if args.only else list(ALL_CHUNKS)
    if args.skip_added:
        selected = [c for c in selected if c.labelled or c.kind == "semantic"]

    results = {}
    for c in selected:
        t0 = time.time()
        print(f"[{c.name}]")
        try:
            if c.kind == "code":
                targets = c.resolve(cfg.engine)
                if not targets:
                    print("  no targets present in this checkout - skipping")
                    continue
                results[c.name] = build_code(
                    cfg.engine / c.root, cfg.module_out(c.name), targets,
                    engine=cfg.engine)
            else:
                chunk_dir = cfg.semantic_chunks / _semantic_dir(c.name)
                if not chunk_dir.exists():
                    print(f"  no committed extraction at {chunk_dir} - skipping "
                          "(run `oregraph semantic` to create it)")
                    continue
                results[c.name] = build_sem(
                    chunk_dir, cfg.module_out(c.name), c.root)
        except Exception as exc:  # keep going; one bad chunk shouldn't stop a build
            print(f"  FAILED: {exc}", file=sys.stderr)
            results[c.name] = {"error": str(exc)}
            continue
        print(f"  done in {time.time() - t0:.1f}s")

    if not args.no_merge:
        cmd_merge(args)
    return results


def _semantic_dir(name: str) -> str:
    return {"OREDocs": "docs", "OREXsd": "xsd",
            "OREExamplesConfig": "examples"}.get(name, name.lower())


def cmd_merge(args):
    from .merge import merge
    cfg = _cfg(args)
    print("[merge]")
    paths = {c.name: cfg.module_graph(c.name) for c in ALL_CHUNKS}
    stats = merge(cfg.engine, list(ALL_CHUNKS), paths, cfg.labels_dir,
                  cfg.merged_graph)
    print(f"\nMerged graph: {cfg.merged_graph}")
    print(json.dumps({k: v for k, v in stats.items() if k != "labels"}, indent=2))


def _gitignore_covers(repo: Path, rel_paths: list[str]) -> list[bool]:
    """Whether each repo-relative path is git-ignored. Ask git, don't parse.

    `git check-ignore` implements the full ignore semantics (negations,
    directory rules, nested .gitignore, core.excludesFile); a hand-rolled scan
    of .gitignore gets those wrong and would warn spuriously.
    """
    try:
        # Bytes, not text=True: on Windows, text mode rewrites the "\n"
        # joining these paths to "\r\n" on the way into the child's stdin, so
        # every path but the last one arrives with a trailing "\r" git's
        # matcher doesn't strip - silently failing to match a real .gitignore
        # rule and reporting a covered file as unguarded.
        r = subprocess.run(["git", "-C", str(repo), "check-ignore", "--stdin"],
                           input="\n".join(rel_paths).encode("utf-8"),
                           capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return [False] * len(rel_paths)   # can't tell - warn rather than stay quiet
    ignored = {line.strip().replace("\\", "/")
              for line in r.stdout.decode("utf-8").splitlines()}
    return [p in ignored for p in rel_paths]


def cmd_mcp(args):
    """Write MCP config for Claude Code and/or VS Code into the Engine repo."""
    cfg = _cfg(args)
    graph = str(cfg.merged_graph)

    # Bind the server to *this* interpreter rather than writing a bare
    # `graphify-mcp`. A bare name resolves through PATH, and `pip install --user`
    # on Windows drops the console script in %APPDATA%\Python\PythonXY\Scripts,
    # which is not on PATH by default - so the config was written successfully
    # and then failed to start, with no indication of why. The module entry
    # point exists (`python -m graphify.serve`) and needs no console script.
    command, pre_args = sys.executable, ["-m", "graphify.serve"]

    def _existing_graph(p: Path) -> str | None:
        """The graph path an existing config points at, or None."""
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        for section in ("mcpServers", "servers"):
            entry = (d.get(section) or {}).get("graphify-ore")
            if entry and entry.get("args"):
                return str(entry["args"][-1])
        return None

    planned: list[tuple[Path, dict]] = []
    if args.host in ("claude", "both"):
        planned.append((cfg.engine / ".mcp.json",
                        {"mcpServers": {"graphify-ore": {
                            "type": "stdio", "command": command,
                            "args": pre_args + [graph]}}}))
    if args.host in ("vscode", "both"):
        planned.append((cfg.engine / ".vscode" / "mcp.json",
                        {"servers": {"graphify-ore": {
                            "type": "stdio", "command": command,
                            "args": pre_args + [graph]}}}))

    # Refuse to silently replace a working config. These files live in the
    # shared Engine repo and point at a machine-specific graph, so overwriting
    # one repoints somebody's working setup at a graph they may not have built.
    conflicts = []
    for p, payload in planned:
        if not p.exists():
            continue
        if p.read_text(encoding="utf-8") == json.dumps(payload, indent=2):
            continue
        conflicts.append((p, _existing_graph(p)))
    if conflicts and not args.force:
        print("refusing to overwrite an existing MCP config:\n")
        for p, old in conflicts:
            print(f"  {p}")
            print(f"    currently points at: {old or '(unrecognised format)'}")
            print(f"    would be changed to: {graph}")
        print("\nRe-run with --force to replace it.")
        return 1

    wrote = []
    for p, payload in planned:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        wrote.append(p)
    for p in wrote:
        print(f"wrote {p}")

    # These files contain an absolute interpreter path and an absolute graph
    # path - valid only on the machine that generated them - and they land in
    # the shared Engine repo. Committing one breaks the server for everyone
    # else. We do not edit the Engine repo's .gitignore: it isn't ours.
    ignored = _gitignore_covers(cfg.engine, [p.relative_to(cfg.engine).as_posix()
                                             for p in wrote])
    unguarded = [p for p, ok in zip(wrote, ignored) if not ok]
    if unguarded:
        print("\nwarning: these files are NOT covered by the Engine repo's .gitignore:")
        for p in unguarded:
            print(f"  {p.relative_to(cfg.engine).as_posix()}")
        print("They are per-machine (absolute interpreter and graph paths) and\n"
              "must not be committed. Each person runs `oregraph mcp` themselves.")
    if not cfg.merged_graph.exists():
        print("\nnote: the merged graph does not exist yet - run "
              "`python -m oregraph build` first.")


def cmd_semantic(args):
    from .semantic_prep import prepare, validate, format_report, CORPORA
    cfg = _cfg(args)
    out_dir = cfg.semantic_chunks / args.corpus
    if args.validate:
        print(format_report(validate(out_dir)))
    else:
        print(format_report(prepare(cfg.engine, args.corpus, out_dir)))
        print(f"\nNext: have your agent extract each chunk into {out_dir}.\n"
              "See docs/COPILOT.md (phase 3) for the exact prompt.")


def cmd_relabel(args):
    from .relabel import (propose, format_proposal, write_anchors, digest,
                          audit, format_audit, sync)
    cfg = _cfg(args)

    if args.sync:
        if not cfg.merged_graph.exists():
            print(f"error: {cfg.merged_graph} not found - run `build` or "
                  "`merge` first", file=sys.stderr)
            return 1
        targets = args.only or [c.name for c in ALL_CHUNKS
                                if (cfg.labels_dir / f"{c.name}.anchors.json").exists()]
        written = sync(cfg.merged_graph, cfg.labels_dir, targets)
        for name in targets:
            n = written.get(name)
            if n is None:
                print(f"{name}: no attached curated names in the merged graph "
                      "- left {name}.json untouched")
            else:
                print(f"{name}: {n} name(s) -> {cfg.labels_dir / f'{name}.json'}")
        return

    if args.audit:
        targets = args.only or [c.name for c in ALL_CHUNKS if cfg.labels_for(c.name)]
        dirty = 0
        stale = []
        for name in targets:
            gp, lp = cfg.module_graph(name), cfg.labels_for(name)
            if not gp.exists() or not lp:
                continue
            res = audit(gp, lp)
            print(format_audit(res))
            if res["stale"]:
                stale.append(name)
            else:
                dirty += res["mismatched"]
        if stale:
            print(f"\n{len(stale)} chunk(s) look stale relative to this build - "
                  f"run `oregraph relabel --sync` first: {', '.join(stale)}")
        elif dirty:
            print(f"\n{dirty} name(s) look misfiled - fix before pinning")
        else:
            print("\nCLEAN - safe to --write-anchors")
        return

    if args.digest:
        targets = args.only or [c.name for c in ALL_CHUNKS
                                if cfg.module_graph(c.name).exists()]
        for name in targets:
            gp = cfg.module_graph(name)
            if not gp.exists():
                print(f"{name}: not built - skipping")
                continue
            stats = digest(gp, cfg.module_out(name) / "RELABEL_BRIEF.md",
                           top=args.top)
            print(f"{name}: {stats['communities_briefed']}/"
                  f"{stats['communities_total']} communities -> "
                  f"{stats['path']} ({stats['bytes']:,} bytes)")
        return

    targets = args.only or [c.name for c in ALL_CHUNKS if cfg.labels_for(c.name)]

    for name in targets:
        analysis = cfg.module_out(name) / ".graphify_analysis.json"
        labels = cfg.labels_dir / f"{name}.json"
        if not analysis.exists():
            print(f"{name}: not built - skipping")
            continue
        if not labels.exists():
            print(f"{name}: no curated labels - skipping")
            continue

        if args.write_anchors:
            mapping = json.loads(labels.read_text(encoding="utf-8"))
            stats = write_anchors(cfg.module_graph(name), mapping,
                                  cfg.labels_dir / f"{name}.anchors.json")
            print(f"{name}: {stats}")
        else:
            print(format_proposal(name, propose(analysis, labels)))
            print()

    if not args.write_anchors:
        print("\nThis is a proposal, not a result. Review it, correct "
              f"{cfg.labels_dir}/<chunk>.json, then re-run with --write-anchors "
              "to pin the names so they survive future re-clustering.")


def cmd_verify(args):
    from .verify import verify, format_report
    cfg = _cfg(args)
    result = verify(cfg)
    print(format_report(result))
    # Exit non-zero on failure so CI and the post-merge hook can gate on it.
    # Printing "FAILED" while exiting 0 made every check advisory.
    return 1 if any(not c["ok"] for c in result["checks"]) else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="oregraph",
        description="Build and maintain the ORE knowledge graph.")
    ap.add_argument("--engine", help="path to the ORE Engine repo")
    ap.add_argument("--out", help="graph output directory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="show resolved paths and chunk status")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("coverage", help="report repo files no chunk claims")
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("build", help="build all chunks, then merge")
    p.add_argument("--only", nargs="+", metavar="CHUNK",
                   choices=[c.name for c in ALL_CHUNKS])
    p.add_argument("--skip-added", action="store_true",
                   help="build only the originally-labelled chunks")
    p.add_argument("--no-merge", action="store_true")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("merge", help="re-merge already-built chunks")
    p.set_defaults(func=cmd_merge)

    p = sub.add_parser("mcp", help="write MCP config into the Engine repo")
    p.add_argument("--host", choices=["claude", "vscode", "both"], default="both")
    p.add_argument("--force", action="store_true",
                   help="replace an existing MCP config that points elsewhere")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("semantic",
                       help="prepare or validate an LLM extraction corpus")
    p.add_argument("--corpus", default="examples",
                   choices=["examples", "docs", "xsd"])
    p.add_argument("--validate", action="store_true",
                   help="check which chunks came back and whether they parse")
    p.set_defaults(func=cmd_semantic)

    p = sub.add_parser("relabel",
                       help="check curated names against the current clustering")
    p.add_argument("--only", nargs="+", metavar="CHUNK",
                   choices=[c.name for c in ALL_CHUNKS])
    p.add_argument("--write-anchors", action="store_true",
                   help="pin the current mapping as anchors (do this only after "
                        "confirming the labels are correct)")
    p.add_argument("--sync", action="store_true",
                   help="regenerate labels/<chunk>.json from what the merged "
                        "graph currently attaches; run this before --audit "
                        "whenever a chunk is already anchored")
    p.add_argument("--audit", action="store_true",
                   help="check each curated name against its community's actual "
                        "contents; the gate to pass before --write-anchors")
    p.add_argument("--digest", action="store_true",
                   help="write a compact naming brief per chunk (files and key "
                        "symbols per community) instead of proposing a mapping")
    p.add_argument("--top", type=int, default=40,
                   help="communities to include in --digest (default 40)")
    p.set_defaults(func=cmd_relabel)

    p = sub.add_parser("verify", help="sanity-check the built graph")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)

    # Reproducible builds need PYTHONHASHSEED pinned, and it can only be set
    # before the interpreter starts - so relaunch once, for the two commands
    # that construct or cluster a graph.
    #
    # Why: graphify's build_from_json has a set- or dict-keyed step whose
    # iteration order varies with Python's per-process string hash
    # randomisation. Given byte-identical extraction input, three runs produced
    # 7,517 / 7,518 / 7,511 edges and 220 / 205 / 216 communities; with
    # PYTHONHASHSEED=0, three runs produced 7,522 edges and 209 communities
    # every time. Every unpinned run loses edges relative to the pinned one, so
    # pinning does not fix the loss - it only makes it consistent, which is what
    # the clustering (and therefore the curated names) needs to be reproducible.
    # The underlying edge loss is an upstream bug: see UPSTREAM_ISSUE below.
    #
    # subprocess, not os.execve: Windows implements exec as spawn-and-exit, so
    # cmd.exe frequently returns to the prompt while the replacement is still
    # running.
    if args.cmd in ("build", "merge") and os.environ.get("PYTHONHASHSEED") != "0":
        env = {**os.environ, "PYTHONHASHSEED": "0"}
        # flush before spawning: stdout is block-buffered when piped or
        # redirected, so without this the notice lands *after* the child's
        # entire output and reads as if it belonged to the next command.
        print("Relaunching with PYTHONHASHSEED=0 for a reproducible build.",
              flush=True)
        r = subprocess.run([sys.executable, "-m", "oregraph", *sys.argv[1:]],
                           env=env)
        raise SystemExit(r.returncode)

    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
