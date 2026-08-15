"""Re-attach community names to the clustering they actually describe.

The problem this exists to fix
------------------------------
`labels/<chunk>.json` maps community id -> name. Those ids are Louvain output,
and every build re-runs Louvain. In the original setup the label files were
written against one build and then `rebuild_all.py` re-clustered on later runs
without touching them, so the names drifted onto the wrong groups. It fails
silently: the report still renders, the names are just attached to the wrong
communities. Spot-checking the last build, `QuantLib-01-foundations` community 2
was named "Linear Interpolation" while containing the error-function code, and
community 3 was named "Error Function (erf)" while containing currency
definitions.

The durable fix has two halves:

* `propose()` scores each curated name against every community in the *current*
  clustering by token overlap with member node ids, producing a suggested
  mapping. It is a heuristic - good on distinctive names ("Adaptive Runge-Kutta
  ODE Solver" lands exactly), weak where several names share vocabulary (three
  different interpolation names all score highest on the same community). Treat
  it as a first draft for review, never as truth.

* `write_anchors()` takes a mapping you have confirmed and records, per name,
  the highest-degree member node ids. `labels.py` then re-attaches by anchor
  overlap on future builds, so the names survive re-clustering and ordinary
  code drift without a human in the loop again.

The intended flow is: verify once (`propose` + review, or relabel from scratch
following graphify's Step 5), then `write_anchors` so it never rots again.
"""
from __future__ import annotations

import collections
import json
import math
import re
from pathlib import Path

STOPWORDS = {
    "the", "a", "of", "and", "for", "to", "in", "with", "on", "from",
    "class", "classes", "variants", "core", "implementation", "declarations",
    "pattern", "module", "support", "management", "handling", "generation",
}

#: Anchors recorded per community. Enough that partial code churn still leaves
#: a clear majority, small enough to stay legible in a diff.
ANCHOR_COUNT = 15


def _tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", text.lower())
            if len(t) > 2 and t not in STOPWORDS]


def propose(analysis_path: Path, labels_path: Path) -> dict:
    """Suggest community id for each curated name. Review before trusting."""
    analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    comms = {int(k): v for k, v in analysis["communities"].items()}

    bags: dict[int, collections.Counter] = {}
    for cid, members in comms.items():
        bag: collections.Counter = collections.Counter()
        for nid in members:
            bag.update(_tokens(nid))
        bags[cid] = bag

    doc_freq: collections.Counter = collections.Counter()
    for bag in bags.values():
        for tok in bag:
            doc_freq[tok] += 1
    n_comms = max(len(bags), 1)

    out = {}
    for cid_str, name in labels.items():
        name_tokens = _tokens(name)
        best_cid, best_score = None, 0.0
        for cid, bag in bags.items():
            total = sum(bag.values())
            if not total:
                continue
            score = sum((bag[t] / total) * math.log(n_comms / (1 + doc_freq[t]))
                        for t in name_tokens if bag[t])
            if score > best_score:
                best_cid, best_score = cid, score
        out[name] = {
            "original_id": int(cid_str),
            "proposed_id": best_cid,
            "score": round(best_score, 4),
            "changed": best_cid != int(cid_str),
            "sample": [m.split("_")[-1] for m in comms.get(best_cid, [])[:5]],
        }

    collisions = collections.Counter(v["proposed_id"] for v in out.values()
                                     if v["proposed_id"] is not None)
    for name, v in out.items():
        v["ambiguous"] = collisions[v["proposed_id"]] > 1 if v["proposed_id"] else True
    return out


def digest(graph_path: Path, out_path: Path, top: int = 40,
           files_per: int = 10, symbols_per: int = 12) -> dict:
    """Write a compact, readable brief for naming a chunk's communities.

    Naming communities means looking at what is in them, and the raw material
    for that — `.graphify_analysis.json` — is up to a megabyte of mangled node
    ids per chunk. Handing that to an agent is slow, expensive, and produces
    worse names than it should, because the ids obscure the thing that actually
    identifies a community: which source files it covers.

    This distils each community to its source files and its most connected
    symbols, which is what the naming decision turns on. Roughly 50x smaller
    and considerably easier to read.
    """
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    degree: collections.Counter = collections.Counter()
    for link in g.get("links", g.get("edges", [])):
        degree[link["source"]] += 1
        degree[link["target"]] += 1

    members: dict[int, list[dict]] = collections.defaultdict(list)
    for n in g["nodes"]:
        cid = n.get("community")
        if cid is not None:
            members[int(cid)].append(n)

    ranked = sorted(members.items(), key=lambda kv: -len(kv[1]))[:top]

    lines = [f"# Community brief — {graph_path.parent.parent.name}", "",
             f"{len(members)} communities total; the {len(ranked)} largest are below.",
             "Name each one in 2-5 plain words describing what that group of code does.",
             ""]
    for cid, group in ranked:
        files = collections.Counter()
        for n in group:
            p = n.get("repo_path") or n.get("source_file") or ""
            if p:
                files[str(p).replace("\\", "/")] += 1
        syms = [n["label"] for n in
                sorted(group, key=lambda n: -degree[n["id"]])[:symbols_per]
                if n.get("label")]

        lines.append(f"## community {cid}  ({len(group)} nodes)")
        if files:
            lines.append("files: " + ", ".join(
                f"{f}" for f, _ in files.most_common(files_per)))
        if syms:
            lines.append("symbols: " + ", ".join(syms))
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return {"communities_total": len(members), "communities_briefed": len(ranked),
            "path": str(out_path), "bytes": out_path.stat().st_size}


def write_anchors(graph_path: Path, mapping: dict[str, str], out_path: Path,
                  anchor_count: int = ANCHOR_COUNT) -> dict:
    """Record anchor node ids for a *confirmed* {community id: name} mapping."""
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    degree: collections.Counter = collections.Counter()
    for link in g.get("links", g.get("edges", [])):
        degree[link["source"]] += 1
        degree[link["target"]] += 1

    members: dict[int, list[dict]] = collections.defaultdict(list)
    for n in g["nodes"]:
        cid = n.get("community")
        if cid is not None:
            members[int(cid)].append(n)

    entries = []
    for cid_str, name in mapping.items():
        cid = int(cid_str)
        group = members.get(cid, [])
        if not group:
            continue
        top = sorted(group, key=lambda n: (-degree[n["id"]], n["id"]))[:anchor_count]
        entries.append({"label": name, "size": len(group),
                        "anchors": [n["id"] for n in top]})

    payload = {"anchor_count": anchor_count, "communities": entries}
    out_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    return {"communities_anchored": len(entries), "path": str(out_path)}


def format_proposal(name: str, proposal: dict) -> str:
    lines = [f"# {name}", ""]
    changed = sum(1 for v in proposal.values() if v["changed"])
    ambiguous = sum(1 for v in proposal.values() if v["ambiguous"])
    lines.append(f"{len(proposal)} names | {changed} would move | "
                 f"{ambiguous} ambiguous (several names share a best match)")
    lines.append("")
    for label, v in sorted(proposal.items(), key=lambda x: -x[1]["score"]):
        flag = "AMBIG" if v["ambiguous"] else ("MOVE " if v["changed"] else "same ")
        lines.append(f"[{flag}] {label[:46]:46s} {v['original_id']:>4} -> "
                     f"{str(v['proposed_id']):>5}  score={v['score']:.3f}")
        lines.append(f"          members: {v['sample']}")
    return "\n".join(lines)
