"""Deterministically enumerate instruments.xsd/referencedata.xsd complexTypes
and simpleTypes that OREXsd's committed LLM extraction has no node for, and
emit a semantic-chunk-shaped JSON fragment for the OREXsdSupplement chunk.

Why deterministic, not another LLM pass: xsd_link.py's own module docstring
already diagnosed that OREXsd's LLM extraction under-covers exactly this file
(instruments.xsd declares 241 complexTypes + 16 simpleTypes; the committed
extraction only produced nodes for 73 of them - spot-checked against the
merged graph). Finding a declared type name is mechanical, not a judgment
call, so no LLM is needed to do it correctly.

Why a separate chunk, not more nodes in OREXsd: OREXsd already has 19 curated
community names pinned in labels/OREXsd.json. Roughly doubling that chunk's
node count would reshuffle its Louvain community ids and silently repoint
those names onto the wrong groups (CLAUDE.md rule 1). A new chunk gets its
own independent community detection at build time, so OREXsd's existing
content and labels are untouched.

Re-run `python -m oregraph.xsd_coverage_extract` (or call `write()` directly)
whenever instruments.xsd/referencedata.xsd change - e.g. a new ORE release.
If OREXsd's own committed extraction later happens to cover a name this
script also covers, both chunks will carry a node for it; that's a duplicate
to spot-check for, not something this script resolves automatically.

No containment edges are emitted. `build_semantic.py` builds each semantic
chunk as its own isolated graph before merge, so an edge from one of these
nodes to OREXsd's schema-root/dispatch-group nodes (a different chunk) can
never resolve at that stage - confirmed live: an earlier version of this
script that emitted such edges saw all of them come back
`dangling_endpoint_edges` in the per-chunk build diagnostic. Edges add no
value here anyway: xsd_link.py's matching passes only ever look at a node's
`id`/`label`/`source_file`, never its edges.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .xsd_link import _slugify_xsd_name

_COMPLEX_TYPE_RE = re.compile(r'<xs:complexType\s+name="(\w+)"')
_SIMPLE_TYPE_RE = re.compile(r'<xs:simpleType\s+name="(\w+)"')

_XSD_FILES = ("instruments.xsd", "referencedata.xsd")


def _existing_local_ids(xsd_chunk_dir: Path) -> set[str]:
    ids: set[str] = set()
    for p in sorted(xsd_chunk_dir.glob("chunk_*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        ids.update(n["id"] for n in d.get("nodes", []))
    return ids


def extract_missing(engine: Path, semantic_chunks: Path) -> dict:
    """{"nodes": [...]} fragment, semantic-chunk-shaped, for every
    complexType/simpleType in _XSD_FILES with no existing OREXsd node."""
    covered = _existing_local_ids(semantic_chunks / "xsd")

    nodes: list[dict] = []
    seen_ids: set[str] = set()

    for xsd_file in _XSD_FILES:
        text = (engine / "xsd" / xsd_file).read_text(encoding="utf-8")
        stem = xsd_file.rsplit(".", 1)[0]

        for kind, pattern in (("complexType", _COMPLEX_TYPE_RE),
                              ("simpleType", _SIMPLE_TYPE_RE)):
            for m in pattern.finditer(text):
                name = m.group(1)
                local_id = f"xsd_{stem}_{_slugify_xsd_name(name)}"
                if local_id in covered or local_id in seen_ids:
                    continue
                seen_ids.add(local_id)
                nodes.append({
                    "id": local_id,
                    "label": f"{name} ({kind})",
                    "file_type": "code",
                    "source_file": f"xsd/{xsd_file}",
                    "rationale": (f"Deterministically enumerated from {xsd_file}; "
                                  "OREXsd's LLM extraction did not produce a node "
                                  "for this type."),
                })

    return {"nodes": nodes, "edges": [], "hyperedges": [],
            "input_tokens": 0, "output_tokens": 0}


def write(engine: Path, semantic_chunks: Path, quiet: bool = False) -> Path:
    log = (lambda *a: None) if quiet else print
    fragment = extract_missing(engine, semantic_chunks)
    out_dir = semantic_chunks / "xsd_coverage"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "chunk_01.json"
    out_path.write_text(json.dumps(fragment, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"  wrote {len(fragment['nodes'])} nodes, {len(fragment['edges'])} edges to {out_path}")
    return out_path


if __name__ == "__main__":
    from . import config
    cfg = config.load()
    write(cfg.engine, cfg.semantic_chunks)
