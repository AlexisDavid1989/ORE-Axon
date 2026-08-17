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

#: Above this share of mismatched names, `audit()` stops trusting its own
#: per-name verdicts. See `audit()` for why.
STALE_THRESHOLD = 0.25


def _tokens(text: str) -> list[str]:
    # Length >= 3, not > 3: the domain is full of three-letter terms that carry
    # all the meaning in a name — cbo, xva, cva, dim, irs, cds, fx. An earlier
    # cutoff of 4 dropped them and reported correct names as mismatches.
    return [t for t in re.split(r"[^a-z0-9]+", text.lower())
            if len(t) >= 3 and t not in STOPWORDS]


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


def audit(graph_path: Path, labels_path: Path) -> dict:
    """Check each curated name against the contents of the community it sits on.

    The acceptance gate for relabelling. A name should share vocabulary with the
    files and symbols in its own community: "SIMM CRIF record definitions"
    belongs on members whose paths contain `simm` and `crif`. When it doesn't,
    the name is almost certainly on the wrong group — which is exactly the
    failure that went unnoticed in the original build.

    Matching is deliberately generous: one shared token is enough. It is a trap
    detector, not a quality score, and a clean audit means "nothing is obviously
    misfiled", not "these are good names".

    This only works while `labels_path`'s ids match the clustering in
    `graph_path`. Once a chunk is anchored, the id file is a derived view (see
    `labels.py`) that goes stale the moment the corpus reclusters, and a stale
    id file makes *every* name look misfiled at once - not because the names
    are wrong, but because id 7 just isn't the same community it was. A check
    that cannot tell "these names are wrong" from "these ids are wrong" is
    worse than no check, so above STALE_THRESHOLD mismatched this is reported
    as staleness, not as misfiling - see the `stale` field.
    """
    g = json.loads(graph_path.read_text(encoding="utf-8"))
    labels = json.loads(labels_path.read_text(encoding="utf-8"))

    members: dict[int, list[dict]] = collections.defaultdict(list)
    for n in g["nodes"]:
        cid = n.get("community")
        if cid is not None:
            members[int(cid)].append(n)

    matched, mismatched = [], []
    for cid_str, name in labels.items():
        group = members.get(int(cid_str), [])
        blob = " ".join(
            [str(n.get("repo_path") or n.get("source_file") or "") for n in group]
            + [str(n.get("label") or "") for n in group]
        ).lower()
        name_tokens = _tokens(name)
        hit = [t for t in name_tokens if t in blob]
        entry = {
            "id": int(cid_str), "name": name, "size": len(group),
            "matched_tokens": hit,
            "files": sorted({str(n.get("repo_path") or n.get("source_file") or "")
                             for n in group if n.get("repo_path") or n.get("source_file")})[:4],
        }
        if not group:
            entry["note"] = "community id not present in this build"
            mismatched.append(entry)
        elif hit:
            matched.append(entry)
        else:
            mismatched.append(entry)

    total = len(labels)
    stale = total > 0 and (len(mismatched) / total) > STALE_THRESHOLD

    return {"chunk": labels_path.stem, "total": total,
            "matched": len(matched), "mismatched": len(mismatched),
            "detail": mismatched, "clean": not mismatched, "stale": stale}


def format_audit(result: dict) -> str:
    if result["stale"]:
        return (f"{result['chunk']:36s} STALE  {result['mismatched']}/{result['total']} "
                f"ids don't match their community's content - this looks like the id "
                f"mapping, not the names. Run `oregraph relabel --sync` first.")
    lines = [f"{result['chunk']:36s} match={result['matched']:3d}  "
             f"MISMATCH={result['mismatched']:3d}  (of {result['total']})"]
    for e in result["detail"]:
        note = f"  [{e['note']}]" if e.get("note") else ""
        lines.append(f"    id {e['id']:>4}  \"{e['name']}\"{note}")
        if e["files"]:
            lines.append(f"           files: {', '.join(e['files'])}")
    return "\n".join(lines)


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


def sync(merged_graph_path: Path, labels_dir: Path, chunks: list[str]) -> dict[str, int | None]:
    """Regenerate labels/<chunk>.json from what the merged graph actually attached.

    Once a chunk is anchored, attachment happens by anchor overlap in
    labels.py, not by the id file - so the id file drifts out of date every
    time Louvain renumbers, and nothing notices. This makes it a derived
    artifact again: read the current `community_name`/`community_key` off
    each node in the already-merged graph, group back to per-chunk ids, and
    overwrite the id file with that. Name strings are copied verbatim, never
    reworded - this fixes *which id* a name sits under, not the name itself.

    A name that failed to attach this build (below MATCH_THRESHOLD, or its
    community merged away) simply does not appear in the result - `--sync`
    cannot rescue a name that lost its community, only stop misreporting the
    ones that kept theirs. See relabel --digest to find where lost names went.

    Returns {chunk: names_written}; a chunk is None if the merged graph has no
    attached names for it at all, in which case its id file is left untouched
    rather than overwritten with an empty mapping.
    """
    g = json.loads(merged_graph_path.read_text(encoding="utf-8"))

    by_chunk: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for n in g["nodes"]:
        name, key = n.get("community_name"), n.get("community_key")
        if not name or not key or "Community " in str(name):
            continue
        chunk, local_cid = key.split(":", 1)
        by_chunk[chunk][local_cid] = name

    result: dict[str, int | None] = {}
    for chunk in chunks:
        mapping = by_chunk.get(chunk)
        if not mapping:
            result[chunk] = None
            continue
        ordered = {cid: mapping[cid] for cid in sorted(mapping, key=int)}
        (labels_dir / f"{chunk}.json").write_text(
            json.dumps(ordered, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        result[chunk] = len(ordered)
    return result


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
