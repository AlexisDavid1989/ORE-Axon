"""Command line entry point: `python -m oregraph <command>`."""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

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
    print(f"graphify CLI: {cfg.graphify_cli or '(not on PATH)'}")
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


def cmd_mcp(args):
    """Write MCP config for Claude Code and/or VS Code into the Engine repo."""
    cfg = _cfg(args)
    graph = str(cfg.merged_graph)
    exe = "graphify-mcp"

    wrote = []
    if args.host in ("claude", "both"):
        p = cfg.engine / ".mcp.json"
        payload = {"mcpServers": {"graphify-ore": {
            "type": "stdio", "command": exe, "args": [graph]}}}
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        wrote.append(p)
    if args.host in ("vscode", "both"):
        d = cfg.engine / ".vscode"
        d.mkdir(exist_ok=True)
        p = d / "mcp.json"
        payload = {"servers": {"graphify-ore": {
            "type": "stdio", "command": exe, "args": [graph]}}}
        p.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        wrote.append(p)
    for p in wrote:
        print(f"wrote {p}")
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
    from .relabel import propose, format_proposal, write_anchors
    cfg = _cfg(args)
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
    print(format_report(verify(cfg)))


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
    p.set_defaults(func=cmd_relabel)

    p = sub.add_parser("verify", help="sanity-check the built graph")
    p.set_defaults(func=cmd_verify)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    main()
