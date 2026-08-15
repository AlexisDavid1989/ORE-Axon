"""AST (structural) extraction for one code chunk.

Deterministic, no LLM, no API key. graphify caches per-file results, so a
rebuild after `git pull` only re-extracts what actually changed.

Derived from the original graphify_build.py, with machine-specific paths and
the sys.path hack removed.
"""
from __future__ import annotations

import json
from pathlib import Path

from graphify.detect import detect, save_manifest
from graphify.extract import collect_files, extract
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from graphify.export import to_json
from graphify.diagnostics import diagnose_extraction, format_diagnostic_report

from .fix_ids import fix_graph_json


def add_repo_paths(graph_path: Path, cache_root: Path, engine: Path) -> dict:
    """Stamp every node with `repo_path`: its path relative to the Engine root.

    graphify records `source_file` relative to the extraction cache root, so as
    soon as the output directory lives outside the source tree - the recommended
    setup, since builds write hundreds of MB - paths come out as
    `../../Engine/QuantLib/ql/instruments/swap.hpp`. That form differs per
    machine and cannot be compared against an `#include` target, which is what
    the cross-module linker needs.

    `repo_path` is that comparison key: one stable, machine-independent path per
    node, resolved once here rather than re-derived by every consumer.
    """
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    engine = engine.resolve()
    stamped = outside = missing = 0
    for n in g["nodes"]:
        sf = n.get("source_file")
        if not sf:
            missing += 1
            continue
        try:
            abs_path = (cache_root / sf).resolve()
            n["repo_path"] = abs_path.relative_to(engine).as_posix()
            stamped += 1
        except ValueError:      # resolved outside the Engine tree
            outside += 1
    graph_path.write_text(json.dumps(g), encoding="utf-8")
    return {"stamped": stamped, "outside_engine": outside, "no_source_file": missing}


def merge_detect(detections: list[dict]) -> dict:
    merged: dict = {"total_files": 0, "total_words": 0, "files": {}, "skipped_sensitive": []}
    for det in detections:
        merged["total_files"] += det.get("total_files", 0)
        merged["total_words"] += det.get("total_words", 0)
        merged["skipped_sensitive"] += det.get("skipped_sensitive", [])
        for k, v in det.get("files", {}).items():
            merged["files"].setdefault(k, []).extend(v)
    return merged


CODE_EXTS = {".hpp", ".h", ".hxx", ".hh", ".inl", ".ipp", ".cpp", ".cc",
             ".cxx", ".c", ".py", ".ipynb", ".i", ".java", ".cs", ".ts", ".js"}


def _detect_files(files: list[Path]) -> dict:
    """A detect()-shaped record for individually named files.

    graphify's detect() only walks directories - handed a file path it raises
    NotADirectoryError and silently contributes nothing. Chunks that target
    individual files (QuantLib-00-core globs the top-level ql/*.hpp) therefore
    need their record built here.
    """
    code = [str(f) for f in files if f.suffix.lower() in CODE_EXTS]
    words = 0
    for f in files:
        try:
            words += len(f.read_text(encoding="utf-8", errors="ignore").split())
        except OSError:
            pass
    return {"total_files": len(code), "total_words": words,
            "files": {"code": code}, "skipped_sensitive": []}


def build(root: Path, out_dir: Path, targets: list[Path], engine: Path,
          quiet: bool = False) -> dict:
    """Extract, build, cluster and export one chunk. Returns a summary dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    log = (lambda *a: None) if quiet else print

    dirs = [t for t in targets if t.is_dir()]
    files = [t for t in targets if t.is_file()]
    detections = [detect(t) for t in dirs]
    if files:
        detections.append(_detect_files(files))
    det = merge_detect(detections)
    (out_dir / ".graphify_detect.json").write_text(
        json.dumps(det, ensure_ascii=False), encoding="utf-8")
    counts = {k: len(v) for k, v in det.get("files", {}).items()}
    log(f"  corpus: {det.get('total_files', 0)} files, "
        f"{det.get('total_words', 0):,} words -> {counts}")

    code_files: list[Path] = []
    for f in det.get("files", {}).get("code", []):
        p = Path(f)
        code_files.extend(collect_files(p) if p.is_dir() else [p])

    # graphify reuses cache_root as its id-relativization root. Pointing it
    # outside the source tree keeps the cache out of the repo but makes every
    # AST node id fall back to an absolute-path form - repaired by fix_graph_json
    # below, which uses source_file (relativized correctly) as ground truth.
    cache_root = out_dir.parent
    if code_files:
        ast_result = extract(code_files, cache_root=cache_root)
    else:
        ast_result = {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    log(f"  AST: {len(ast_result['nodes'])} nodes, {len(ast_result['edges'])} edges")

    # No semantic pass here: code is fully covered structurally. Written anyway
    # so the artifact set is uniform across chunks.
    sem: dict = {"nodes": [], "edges": [], "hyperedges": [],
                 "input_tokens": 0, "output_tokens": 0}
    (out_dir / ".graphify_semantic.json").write_text(
        json.dumps(sem, ensure_ascii=False), encoding="utf-8")

    extraction = {
        "nodes": ast_result["nodes"],
        "edges": ast_result["edges"],
        "hyperedges": [],
        "input_tokens": 0,
        "output_tokens": 0,
    }
    (out_dir / ".graphify_extract.json").write_text(
        json.dumps(extraction, ensure_ascii=False), encoding="utf-8")

    G = build_from_json(extraction, root=str(root), directed=False)
    if G.number_of_nodes() == 0:
        raise RuntimeError(f"extraction produced no nodes for {out_dir.parent.name}")

    communities = cluster(G)
    cohesion = score_all(G, communities)
    gods = god_nodes(G)
    surprises = surprising_connections(G, communities)
    labels = {cid: f"Community {cid}" for cid in communities}
    questions = suggest_questions(G, communities, labels)

    graph_path = out_dir / "graph.json"
    if not to_json(G, communities, str(graph_path), force=True):
        raise RuntimeError(f"refused to write {graph_path}")

    fix_stats = fix_graph_json(str(graph_path))
    log(f"  id repair: {fix_stats}")

    path_stats = add_repo_paths(graph_path, cache_root, engine)
    log(f"  repo paths: {path_stats}")

    report = generate(G, communities, cohesion, labels, gods, surprises, det,
                      {"input": 0, "output": 0}, str(root),
                      suggested_questions=questions)
    (out_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")
    (out_dir / ".graphify_analysis.json").write_text(json.dumps({
        "communities": {str(k): v for k, v in communities.items()},
        "cohesion": {str(k): v for k, v in cohesion.items()},
        "gods": gods, "surprises": surprises, "questions": questions,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    summary = diagnose_extraction(extraction, directed=False, root=str(root))
    log("  " + format_diagnostic_report(summary).replace("\n", "\n  "))
    flags = [f"{summary[k]} {lbl}" for k, lbl in (
        ("dangling_endpoint_edges", "dangling-endpoint edges"),
        ("missing_endpoint_edges", "missing-endpoint edges"),
        ("self_loop_edges", "self-loop edges"),
        ("directed_same_endpoint_collapsed_edges", "collapsed (directed) edges"),
        ("undirected_same_endpoint_collapsed_edges", "collapsed (undirected) edges"),
    ) if summary.get(k, 0)]
    if flags:
        log("  GRAPH HEALTH WARNING: " + "; ".join(flags))

    save_manifest(det.get("all_files") or det.get("files", {}),
                  manifest_path=str(out_dir / "manifest.json"), root=root)

    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "communities": len(communities),
        "files": det.get("total_files", 0),
        "health": flags,
    }
