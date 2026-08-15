"""Prepare and validate a semantic extraction corpus.

Semantic extraction is the one part of the pipeline an LLM has to do: there is
no AST for a LaTeX manual or an XML portfolio. The output is a set of chunk
JSON files under `semantic-chunks/<corpus>/`, which are then committed - so the
cost is paid once for the whole team, not once per clone.

This module handles the deterministic half: deciding which files go in which
chunk, and checking afterwards that what came back is usable. The extraction
itself is driven from the agent (see docs/COPILOT.md).
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

#: Files per chunk. graphify's own guidance is 20-25; XML portfolios are
#: verbose, so this sits at the low end to keep a chunk inside one context.
CHUNK_SIZE = 20

CORPORA = {
    "examples": {
        "root": "Examples",
        "patterns": ("**/*.xml", "**/*.csv"),
        "note": "ORE example portfolios, market data and pricing config",
    },
    "docs": {
        "root": "Docs",
        "patterns": ("**/*.tex",),
        "note": "LaTeX manuals - already extracted and committed",
    },
    "xsd": {
        "root": "xsd",
        "patterns": ("*.xsd",),
        "note": "input schemas - already extracted and committed",
    },
}

#: Skip files that carry no architectural signal. Expected-output fixtures are
#: the big one: Examples/ is full of megabyte result dumps that would burn an
#: entire chunk to yield nothing.
SKIP_PARTS = {"ExpectedOutput", "Output", "expected_output", "__pycache__"}
MAX_BYTES = 400_000


def collect(engine: Path, corpus: str) -> list[Path]:
    spec = CORPORA[corpus]
    base = engine / spec["root"]
    if not base.exists():
        return []
    files: list[Path] = []
    for pat in spec["patterns"]:
        for f in base.glob(pat):
            if not f.is_file():
                continue
            if set(f.relative_to(base).parts) & SKIP_PARTS:
                continue
            try:
                if f.stat().st_size > MAX_BYTES:
                    continue
            except OSError:
                continue
            files.append(f)
    return sorted(files)


def prepare(engine: Path, corpus: str, out_dir: Path,
            chunk_size: int = CHUNK_SIZE) -> dict:
    """Write a chunk manifest. Files from one directory stay together so
    cross-file relationships land inside a single chunk."""
    files = collect(engine, corpus)
    if not files:
        return {"corpus": corpus, "files": 0, "chunks": 0,
                "note": "nothing to extract"}

    by_dir: dict[Path, list[Path]] = defaultdict(list)
    for f in files:
        by_dir[f.parent].append(f)

    chunks: list[list[Path]] = []
    current: list[Path] = []
    for d in sorted(by_dir):
        for f in sorted(by_dir[d]):
            current.append(f)
            if len(current) >= chunk_size:
                chunks.append(current)
                current = []
    if current:
        chunks.append(current)

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for i, group in enumerate(chunks, 1):
        manifest.append({
            "chunk": i,
            "total": len(chunks),
            "output": str((out_dir / f"chunk_{i:02d}.json").resolve()),
            "files": [str(f.resolve()) for f in group],
        })
    (out_dir / "_manifest.json").write_text(
        json.dumps(manifest, indent=1), encoding="utf-8")

    return {"corpus": corpus, "files": len(files), "chunks": len(chunks),
            "manifest": str((out_dir / "_manifest.json").resolve()),
            "chunk_sizes": [len(c) for c in chunks]}


def validate(out_dir: Path) -> dict:
    """Check which chunks came back and whether they parse."""
    manifest_path = out_dir / "_manifest.json"
    if not manifest_path.exists():
        return {"error": f"no manifest at {manifest_path} - run --prepare first"}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    done, missing, broken = [], [], []
    nodes = edges = 0
    for entry in manifest:
        p = Path(entry["output"])
        if not p.exists():
            missing.append(entry["chunk"])
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(d.get("nodes"), list) or not isinstance(d.get("edges"), list):
                raise ValueError("missing nodes/edges")
            nodes += len(d["nodes"])
            edges += len(d["edges"])
            done.append(entry["chunk"])
        except Exception as exc:
            broken.append({"chunk": entry["chunk"], "error": str(exc)[:120]})

    return {"total": len(manifest), "complete": len(done),
            "missing": missing, "broken": broken,
            "nodes": nodes, "edges": edges,
            "ready": not missing and not broken}


def format_report(result: dict) -> str:
    if "error" in result:
        return f"error: {result['error']}"
    if "chunks" in result:      # prepare
        if not result["chunks"]:
            return f"{result['corpus']}: {result.get('note', 'nothing to do')}"
        return (f"{result['corpus']}: {result['files']} files -> "
                f"{result['chunks']} chunks\nmanifest: {result['manifest']}")
    lines = [f"chunks complete: {result['complete']}/{result['total']}  "
             f"({result['nodes']:,} nodes, {result['edges']:,} edges)"]
    if result["missing"]:
        shown = result["missing"][:20]
        lines.append(f"missing: {shown}{' ...' if len(result['missing']) > 20 else ''}")
    for b in result["broken"]:
        lines.append(f"broken chunk {b['chunk']}: {b['error']}")
    lines.append("READY - run `oregraph build --only OREExamplesConfig`"
                 if result["ready"] else "not ready yet")
    return "\n".join(lines)
