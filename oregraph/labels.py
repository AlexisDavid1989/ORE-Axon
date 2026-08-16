"""Re-attach curated community names to a freshly built graph.

The problem
-----------
`labels/<chunk>.json` maps a community id to a human-written name. Community ids
come out of Louvain clustering, which is only stable while the corpus is. Your
teammate builds from their own ORE checkout - a different commit, maybe a
different branch - the partition shifts, and every id-keyed label silently
repoints to the wrong group. Nothing errors; the names are just wrong.

The fix
-------
`labels/<chunk>.anchors.json` records, for each named community, the ~15
highest-degree members by local node id. On a fresh build each new community is
scored against every anchor set, and the best match above a threshold takes the
name. Node ids derive from source paths, so they survive ordinary code drift far
better than community numbering does.

Falls back to direct id lookup when no anchor file exists.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

#: Minimum share of a label's anchors that must land in one community.
MATCH_THRESHOLD = 0.40
#: Ceiling on the absolute number of anchors required in that community - not a
#: floor. Guards against a label attaching to a tiny community on the strength
#: of one or two hits, but a label can never be asked for more anchors than it
#: has: a community with three members yields three anchors, and requiring four
#: dropped it at merge however perfectly it matched. The requirement is
#: therefore min(MIN_OVERLAP, len(anchors)) - see attach_labels.
MIN_OVERLAP = 4
#: When two labels both best-match the same community, the corpus has merged
#: two previously separate groups; keep up to this many names for it rather
#: than displacing the loser onto a community it does not describe.
MAX_NAMES_PER_COMMUNITY = 2


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def attach_labels(chunk: str, graph: dict, labels_dir: Path) -> tuple[dict[int, str], dict]:
    """Return ({community id: name}, stats)."""
    plain = _load(labels_dir / f"{chunk}.json") or {}
    anchored = _load(labels_dir / f"{chunk}.anchors.json")

    members: dict[int, set[str]] = defaultdict(set)
    for n in graph["nodes"]:
        cid = n.get("community")
        if cid is None:
            continue
        members[int(cid)].add(n.get("local_id") or n["id"])

    if not anchored:
        # No anchor file: fall back to raw id lookup. This is the mode that
        # silently mislabelled the original build - the ids are only valid for
        # the clustering they were written against - so it is reported as
        # unverified rather than presented as a clean result.
        names = {cid: plain[str(cid)] for cid in members if str(cid) in plain}
        return names, {"mode": "id-unverified", "matched": len(names),
                       "available": len(plain), "warning":
                       "labels attached by raw community id; run "
                       "`oregraph relabel` to verify and anchor them"}

    # Each label goes to the community holding the most of its anchors - and
    # nowhere else. An earlier version assigned greedily with one name per
    # community, which meant that when clustering merged two previously
    # separate groups, the losing label was pushed onto its *second* choice: a
    # community it did not describe at all. A label that cannot win its own
    # argmax is dropped, not relocated.
    claims: dict[int, list[tuple[float, str]]] = defaultdict(list)
    dropped = 0
    for entry in anchored.get("communities", []):
        anchors = set(entry.get("anchors", []))
        if not anchors:
            continue
        best_cid, best_hit = None, 0
        for cid, mem in members.items():
            hit = len(anchors & mem)
            if hit > best_hit:
                best_cid, best_hit = cid, hit
        recall = best_hit / len(anchors)
        # Scale the overlap requirement to what this label can actually offer.
        # A small community contributes fewer anchors than MIN_OVERLAP, so a
        # fixed guard made it unattachable no matter how well it matched: four
        # OREDocs names each matched their community with recall 1.00 on three
        # anchors and were still dropped here, silently, at merge time.
        need = min(MIN_OVERLAP, len(anchors))
        if best_cid is None or recall < MATCH_THRESHOLD or best_hit < need:
            dropped += 1
            continue
        claims[best_cid].append((recall, entry["label"]))

    names: dict[int, str] = {}
    merged_groups = 0
    for cid, cands in claims.items():
        cands.sort(key=lambda x: -x[0])
        if len(cands) > 1:
            merged_groups += 1
        names[cid] = " / ".join(lbl for _, lbl in cands[:MAX_NAMES_PER_COMMUNITY])

    return names, {
        "mode": "anchor",
        "matched": len(names),
        "labels_placed": sum(len(c) for c in claims.values()),
        "labels_dropped": dropped,
        "merged_communities": merged_groups,
        "available": len(anchored.get("communities", [])),
        "threshold": MATCH_THRESHOLD,
    }
