"""Cross-chunk edge recovery.

Why this exists
---------------
Each chunk is extracted in isolation, so when `OREData/ored/portfolio/swap.cpp`
does `#include <qle/pricingengines/discountingswapengine.hpp>`, graphify has no
node for that header in scope and drops the relationship. It is not recorded as
a dangling edge - it simply never exists.

The consequence is severe and easy to miss: the merged graph looks large but is
a set of disconnected islands. A query like "what in QuantExt does OREData's
swap builder depend on?" cannot be answered by traversal, because there is no
path between the two.

This module recovers those relationships by reading `#include` directives
straight from the source tree - deterministic, cheap, and exactly the ground
truth for C++. Includes are resolved against the chunk map's INCLUDE_ROOTS, so
only intra-ORE includes are linked; system and Boost headers are ignored.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .chunks import INCLUDE_ROOTS, Chunk

INCLUDE_RE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]', re.M)

SOURCE_EXTS = {".hpp", ".h", ".hxx", ".hh", ".inl", ".ipp",
               ".cpp", ".cc", ".cxx", ".c"}


def _iter_sources(paths: list[Path]):
    # Sorted throughout: rglob order is filesystem-dependent, and anything that
    # varies here varies in the edge list downstream.
    for p in sorted(paths):
        if p.is_file():
            if p.suffix.lower() in SOURCE_EXTS:
                yield p
        else:
            for f in sorted(p.rglob("*")):
                if f.is_file() and f.suffix.lower() in SOURCE_EXTS:
                    yield f


def scan_includes(engine: Path, chunks: list[Chunk]) -> dict[str, set[str]]:
    """repo-relative source path -> set of repo-relative include targets.

    Both sides are normalised to POSIX paths relative to the Engine root, which
    is the same key space `build_index` uses.
    """
    edges: dict[str, set[str]] = defaultdict(set)
    for chunk in chunks:
        for f in _iter_sources(chunk.resolve(engine)):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            src_rel = f.relative_to(engine).as_posix()
            for inc in INCLUDE_RE.findall(text):
                inc = inc.replace("\\", "/").lstrip("./")
                for prefix, root in INCLUDE_ROOTS.items():
                    if inc.startswith(prefix):
                        edges[src_rel].add(f"{root}/{inc[len(prefix):]}")
                        break
    return edges


def build_index(graphs: dict[str, dict], engine_roots: dict[str, str]) -> dict[str, str]:
    """repo-relative source file -> node id of that file's file-level node.

    Keys come from `repo_path`, stamped at build time by build_ast.add_repo_paths,
    which is the one path form guaranteed comparable with an `#include` target.
    Chunks built before repo_path existed fall back to chunk-root + source_file.
    """
    index: dict[str, str] = {}
    for name, g in graphs.items():
        root = engine_roots.get(name, "").rstrip("/")
        for n in g["nodes"]:
            key = n.get("repo_path")
            if not key:
                sf = n.get("source_file")
                if not sf or ".." in str(sf):
                    continue
                sf = str(sf).replace("\\", "/")
                key = f"{root}/{sf}" if root not in ("", ".") else sf
            # File-level nodes carry no symbol suffix, so for a given path the
            # shortest id is the file node rather than one of its members.
            # Compare (length, id) rather than length alone: two ids of equal
            # length would otherwise resolve by iteration order, so the same
            # corpus could index a different node between runs.
            prev = index.get(key)
            if prev is None or (len(n["id"]), n["id"]) < (len(prev), prev):
                index[key] = n["id"]
    return index


def link(engine: Path, chunks: list[Chunk], graphs: dict[str, dict],
         engine_roots: dict[str, str]) -> tuple[list[dict], dict]:
    """Return (cross-chunk edges, stats)."""
    index = build_index(graphs, engine_roots)
    includes = scan_includes(engine, chunks)

    node_repo = {}
    for name, g in graphs.items():
        for n in g["nodes"]:
            node_repo[n["id"]] = name

    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    unresolved = 0
    intra = 0
    # Iterate in sorted order throughout. `includes` maps to sets of strings, and
    # Python randomises string hashing per process (PYTHONHASHSEED), so set and
    # dict iteration order varies between runs. That fed straight into edge
    # order, and through it into the clustering - two builds of an unchanged
    # corpus produced different partitions and dropped curated names.
    for src_rel in sorted(includes):
        targets = includes[src_rel]
        src_id = index.get(src_rel)
        if src_id is None:
            continue
        for tgt_rel in sorted(targets):
            tgt_id = index.get(tgt_rel)
            if tgt_id is None:
                unresolved += 1
                continue
            if node_repo.get(src_id) == node_repo.get(tgt_id):
                intra += 1          # already covered inside that chunk
                continue
            key = (src_id, tgt_id)
            if key in seen:
                continue
            seen.add(key)
            edges.append({
                "source": src_id,
                "target": tgt_id,
                "relation": "includes",
                "context": "cross_module_include",
                "confidence": "EXTRACTED",
                "confidence_score": 1.0,
                "weight": 1.0,
                "source_file": src_rel,
                "_origin": "cross_link",
            })
    edges.sort(key=lambda e: (e["source"], e["target"]))
    return edges, {
        "files_scanned": len(includes),
        "cross_module_edges": len(edges),
        "intra_module_includes_skipped": intra,
        "unresolved_includes": unresolved,
        "indexed_files": len(index),
    }
