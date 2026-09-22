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
from datetime import datetime, timezone
from pathlib import Path

from . import config as configmod
from .chunks import Chunk
from .fieldmap import FieldmapSnapshot
from .fieldmap_link import link_fieldmap
from .labels import attach_labels
from .link import link
from .link_schema import link_schema
from .symbol_links import link_symbols
from .xsd_link import link_xsd


def load_graph(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def merge(engine: Path, chunks: list[Chunk], graph_paths: dict[str, Path],
          labels_dir: Path, out_path: Path, quiet: bool = False,
          fieldmap: FieldmapSnapshot | None = None) -> dict:
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

    # link_schema() needs pre-namespaced (local-id) nodes AND each chunk's own
    # "links" - both are still in that form here, before the namespacing loop
    # below mutates `graphs` in place. Its own edges are collected now and
    # remapped onto namespaced ids later, alongside link()'s cross-module ones.
    schema_edges_local, schema_stats = link_schema(engine, list(chunks), graphs, engine_roots)

    # ---- per-chunk labelling, then namespacing -----------------------------
    merged_nodes: list[dict] = []
    merged_links: list[dict] = []
    hyperedges: list[dict] = []
    label_stats: dict[str, dict] = {}

    # Community ids must stay globally unique across chunks - every chunk numbers
    # its own communities from 0 - but they must also remain *integers*: graphify's
    # MCP server does int(cid) when it reconstructs communities from the graph, and
    # a namespaced string crashes it on startup. So the id is offset by the chunk's
    # position and the readable form is kept beside it in `community_key`.
    #
    # These integer ids are EPHEMERAL. They depend on chunk_index, which is the
    # position of a chunk in this merge, so adding or removing a chunk renumbers
    # every community after it - and Louvain itself repartitions on every build
    # anyway. Never persist one, and never treat it as stable across builds.
    # Nothing does today: anchors reference node ids, which derive from source
    # paths. The temptation to key something off a community id will arise; don't.
    COMMUNITY_STRIDE = 1_000_000
    chunk_index = {name: i for i, name in enumerate(graphs)}

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
                n["community"] = chunk_index[name] * COMMUNITY_STRIDE + int(cid)
                n["community_key"] = f"{name}:{cid}"
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

    # link_schema()'s edges were collected before namespacing too; remap them
    # onto the merged graph the same way.
    fixed_schema = []
    for e in schema_edges_local:
        s, t = e["source"], e["target"]
        so, to = id_owner.get(s), id_owner.get(t)
        if not so or not to:
            continue
        e["source"], e["target"] = f"{so}::{s}", f"{to}::{t}"
        fixed_schema.append(e)
    merged_links.extend(fixed_schema)
    schema_stats["schema_for_edges"] = len(fixed_schema)
    log(f"  schema links: {len(fixed_schema)} schema_for edges "
        f"(tiers: {schema_stats.get('tier_counts')}); "
        f"{len(schema_stats.get('xsd_orphans', []))} xsd types with no code match, "
        f"{len(schema_stats.get('code_trade_gaps', []))} trade types with no xsd match")
    log(f"  cross-module links: {link_stats}")
    total_inc = link_stats["total_includes"]
    resolved = link_stats["resolved_includes"]
    log(f"  include recall: {resolved:,}/{total_inc:,} directives resolved to a "
        f"node ({resolved / total_inc:.0%})" if total_inc else "  include recall: no includes scanned")
    if link_stats["unresolved_includes"]:
        log(f"    unresolved (ORE prefix matched, no indexed node): "
            f"{link_stats['unresolved_includes']} - by root: {link_stats['unresolved_by_root']}")
    if link_stats["ignored_non_ore_prefix"]:
        log(f"    ignored (no INCLUDE_ROOTS prefix matched): "
            f"{link_stats['ignored_non_ore_prefix']} - top prefixes: {link_stats['ignored_by_prefix']}")

    # Explicit construction, qualified-call and registration evidence is
    # recovered after namespacing so it can connect symbols across chunks.
    symbol_edges, symbol_stats = link_symbols(engine, merged_nodes)
    existing = {(edge["source"], edge["target"], edge.get("relation"))
                for edge in merged_links}
    symbol_edges = [edge for edge in symbol_edges
                    if (edge["source"], edge["target"], edge["relation"]) not in existing]
    merged_links.extend(symbol_edges)
    symbol_stats["symbol_edges"] = len(symbol_edges)
    log(f"  symbol links: {symbol_stats}")

    # XSD schema <-> C++ class name matching (see xsd_link.py for why this is
    # a separate, narrower-scoped pass rather than folded into symbol_links).
    xsd_edges, xsd_stats = link_xsd(merged_nodes, engine)
    xsd_edges = [edge for edge in xsd_edges
                 if (edge["source"], edge["target"], edge["relation"]) not in existing]
    merged_links.extend(xsd_edges)
    td, cd = xsd_stats["trade_dispatch"], xsd_stats["convention_dispatch"]
    rd = xsd_stats["reference_data_dispatch"]
    log(f"  xsd links: {xsd_stats['xsd_edges']} edges total; "
        f"legacy name-match {xsd_stats['matched_exact']} exact + "
        f"{xsd_stats['matched_via_stripped_data_suffix']} via stripped 'Data' suffix "
        f"({xsd_stats['unmatched']}/{xsd_stats['instruments_xsd_type_names']} unmatched); "
        f"trade dispatch {td.get('matched_exact', 0)}+{td.get('matched_normalized', 0)} "
        f"({len(td.get('unmatched_names', []))}/{td.get('attempted', 0)} unmatched); "
        f"convention dispatch {cd.get('matched_exact', 0)}+{cd.get('matched_normalized', 0)} "
        f"({len(cd.get('unmatched_names', []))}/{cd.get('attempted', 0)} unmatched); "
        f"reference-datum dispatch {rd.get('matched_exact', 0)}+{rd.get('matched_normalized', 0)} "
        f"({len(rd.get('unmatched_names', []))}/{rd.get('attempted', 0)} unmatched)")

    # ORE_Forge's field mapping (all four domains), from the cached snapshot -
    # merge never calls ORE_Forge itself. Optional: without a snapshot the
    # graph is exactly what it was before this pass existed. Runs last so it
    # sees every namespaced node and every registration edge above; its
    # communities start past the last chunk's range (ephemeral, like the rest).
    fieldmap_stats = None
    if fieldmap is not None:
        fm_nodes, fm_edges, fieldmap_stats = link_fieldmap(
            fieldmap, merged_nodes, merged_links, engine,
            community_base=len(graphs) * COMMUNITY_STRIDE)
        merged_nodes.extend(fm_nodes)
        merged_links.extend(fm_edges)
        per = fieldmap_stats["domains"]
        log(f"  fieldmap: {len(fm_nodes):,} nodes, {len(fm_edges):,} edges from "
            f"ORE_Forge @ {(fieldmap.version.get('commit') or '?')[:9]} - "
            + ", ".join(f"{d} {per[d]['entries']} entries/{per[d]['fields']:,} fields "
                        f"({per[d]['class_linked']} class, {per[d]['schema_linked']} schema)"
                        for d in per))

    ore = configmod.ore_version(engine)
    ore["graphify_version"] = configmod.graphify_version()
    ore["built_at"] = datetime.now(timezone.utc).isoformat()

    out = {
        "directed": False,
        "multigraph": False,
        "graph": {"hyperedges": hyperedges,
                  "chunks": sorted(graphs),
                  "cross_module_edges": len(fixed_cross),
                  "link_stats": link_stats,
                  "symbol_link_stats": symbol_stats,
                  "xsd_link_stats": xsd_stats,
                  "schema_link_stats": schema_stats,
                  **({"fieldmap": fieldmap_stats} if fieldmap_stats else {}),
                  "ore": ore},
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
        "symbol_edges": len(symbol_edges),
        "labelled_communities": labelled,
        "labels": label_stats,
        "link": link_stats,
        "schema": schema_stats,
        "fieldmap": ({"nodes": fieldmap_stats["nodes"], "edges": fieldmap_stats["edges"],
                      "relations": fieldmap_stats["relations"]}
                     if fieldmap_stats else None),
    }
