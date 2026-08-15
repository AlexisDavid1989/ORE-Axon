"""Merge every chunk into one graph - namespaced, labelled and cross-linked.

This replaces `graphify merge-graphs`, which had three problems for a corpus
split the way ORE is:

1. **Community ids were concatenated, not namespaced.** Each chunk numbers its
   communities from 0, so after merging, "community 0" was a union of unrelated
   groups from every chunk at once - in the previous build, 1,259 nodes drawn
   from 12 modules with no edges between them. Any community-level query
   returned nonsense.
2. **Curated labels were dropped.** Every community in the merged graph came
   out as "Community N", so the 272 hand-written names were invisible to the
   MCP server - the one place they were most useful.
3. **No cross-chunk edges.** See link.py.

Here communities are namespaced as "<chunk>:<local id>", labels are carried
through, and cross-chunk include edges are added.
"""
from __future__ import annotations

import json
from pathlib import Path

from .chunks import Chunk
from .labels import attach_labels
from .link import link


def load_graph(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def merge(engine: Path, chunks: list[Chunk], graph_paths: dict[str, Path],
          labels_dir: Path, out_path: Path, quiet: bool = False) -> dict:
    log = (lambda *a: None) if quiet else print

    graphs: dict[str, dict] = {}
    for name, p in graph_paths.items():
        if not p.exists():
            log(f"  skip {name}: {p} not built")
            continue
        graphs[name] = load_graph(p)

    if not graphs:
        raise RuntimeError("no chunk graphs found - run `build` first")

    engine_roots = {c.name: c.root for c in chunks}

    # ---- per-chunk labelling, then namespacing -----------------------------
    merged_nodes: list[dict] = []
    merged_links: list[dict] = []
    hyperedges: list[dict] = []
    label_stats: dict[str, dict] = {}

    for name, g in graphs.items():
        names, stats = attach_labels(name, g, labels_dir)
        label_stats[name] = stats

        for n in g["nodes"]:
            local = n["id"]
            n["local_id"] = local
            n["id"] = f"{name}::{local}"
            n["repo"] = name
            cid = n.get("community")
            if cid is not None:
                n["community"] = f"{name}:{cid}"
                n["community_name"] = names.get(int(cid), f"{name} / Community {cid}")
            merged_nodes.append(n)

        for e in g.get("links", g.get("edges", [])):
            e["source"] = f"{name}::{e['source']}"
            e["target"] = f"{name}::{e['target']}"
            merged_links.append(e)

        for he in (g.get("graph") or {}).get("hyperedges", []) or []:
            he = dict(he)
            he["nodes"] = [f"{name}::{x}" for x in he.get("nodes", [])]
            he["id"] = f"{name}::{he.get('id')}"
            hyperedges.append(he)

    # ---- cross-chunk edges -------------------------------------------------
    code_chunks = [c for c in chunks if c.kind == "code" and c.name in graphs]
    # link() needs pre-namespaced ids, so rebuild a view keyed on local ids
    local_view = {
        name: {"nodes": [{**n, "id": n["local_id"]} for n in g["nodes"]]}
        for name, g in graphs.items()
    }
    cross, link_stats = link(engine, code_chunks, local_view, engine_roots)

    # The linker works in local-id space; map each endpoint back to its chunk.
    id_owner: dict[str, str] = {}
    for name, g in graphs.items():
        for n in g["nodes"]:
            id_owner.setdefault(n["local_id"], name)
    fixed_cross = []
    for e in cross:
        s, t = e["source"], e["target"]
        so, to = id_owner.get(s), id_owner.get(t)
        if not so or not to:
            continue
        e["source"], e["target"] = f"{so}::{s}", f"{to}::{t}"
        fixed_cross.append(e)
    merged_links.extend(fixed_cross)
    link_stats["cross_module_edges"] = len(fixed_cross)
    log(f"  cross-module links: {link_stats}")

    out = {
        "directed": False,
        "multigraph": False,
        "graph": {"hyperedges": hyperedges,
                  "chunks": sorted(graphs),
                  "cross_module_edges": len(fixed_cross)},
        "nodes": merged_nodes,
        "links": merged_links,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out), encoding="utf-8")

    labelled = sum(s["matched"] for s in label_stats.values())
    log(f"  merged: {len(merged_nodes):,} nodes, {len(merged_links):,} edges, "
        f"{labelled} labelled communities")
    return {
        "nodes": len(merged_nodes),
        "edges": len(merged_links),
        "cross_module_edges": len(fixed_cross),
        "labelled_communities": labelled,
        "labels": label_stats,
        "link": link_stats,
    }
