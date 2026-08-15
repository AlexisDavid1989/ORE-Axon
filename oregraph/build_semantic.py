"""Build a chunk graph from committed semantic extraction JSON.

Docs and XSDs cannot be read structurally - there is no AST for a LaTeX manual.
They were extracted once by an LLM, and the resulting node/edge fragments live
in `semantic-chunks/`. Building from those committed fragments is deterministic
and free: **no API key is needed to build this repo.** Re-extraction is only
required when the underlying documents change (see `oregraph semantic`).
"""
from __future__ import annotations

import json
from pathlib import Path

from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from graphify.export import to_json
from graphify.diagnostics import diagnose_extraction, format_diagnostic_report


def build(chunk_dir: Path, out_dir: Path, label_root: str,
          quiet: bool = False) -> dict:
    log = (lambda *a: None) if quiet else print
    out_dir.mkdir(parents=True, exist_ok=True)

    chunk_paths = sorted(chunk_dir.glob("chunk_*.json"))
    if not chunk_paths:
        raise FileNotFoundError(f"no chunk_*.json in {chunk_dir}")
    log(f"  merging {len(chunk_paths)} semantic chunks")

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    hyper: dict[str, dict] = {}
    for cp in chunk_paths:
        d = json.loads(cp.read_text(encoding="utf-8"))
        for n in d.get("nodes", []):
            nodes.setdefault(n["id"], n)
        edges.extend(d.get("edges", []))
        for he in d.get("hyperedges") or []:
            hyper.setdefault(he["id"], he)

    extraction = {
        "nodes": list(nodes.values()),
        "edges": edges,
        "hyperedges": list(hyper.values()),
        "input_tokens": 0,
        "output_tokens": 0,
    }
    (out_dir / ".graphify_extract.json").write_text(
        json.dumps(extraction, ensure_ascii=False), encoding="utf-8")
    log(f"  merged: {len(extraction['nodes'])} nodes, {len(edges)} edges, "
        f"{len(hyper)} hyperedges")

    det = {
        "total_files": len(chunk_paths),
        "total_words": 0,
        "files": {"document": [f"chunk {i}" for i in range(len(chunk_paths))]},
        "skipped_sensitive": [],
    }

    G = build_from_json(extraction, root=None, directed=False)
    if G.number_of_nodes() == 0:
        raise RuntimeError(f"semantic build produced no nodes for {out_dir}")

    communities = cluster(G)
    cohesion = score_all(G, communities)
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    labels = {cid: f"Community {cid}" for cid in communities}
    questions = suggest_questions(G, communities, labels)

    if not to_json(G, communities, str(out_dir / "graph.json"), force=True):
        raise RuntimeError("refused to write graph.json")

    report = generate(G, communities, cohesion, labels, gods, surprises, det,
                      {"input": 0, "output": 0}, label_root,
                      suggested_questions=questions)
    (out_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    (out_dir / ".graphify_analysis.json").write_text(json.dumps({
        "communities": {str(k): v for k, v in communities.items()},
        "cohesion": {str(k): v for k, v in cohesion.items()},
        "gods": gods, "surprises": surprises, "questions": questions,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = diagnose_extraction(extraction, directed=False, root=None)
    log("  " + format_diagnostic_report(summary).replace("\n", "\n  "))

    return {"nodes": G.number_of_nodes(), "edges": G.number_of_edges(),
            "communities": len(communities)}
