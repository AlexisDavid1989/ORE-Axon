"""Which passing rubric entries survive a change that should change nothing.

A rubric entry that passes is only as good as its stability. `bench --fragility`
rebuilds the merged graph in memory in a way that alters no fact in it and asks
the whole suite again:

  shuffle  the same nodes, edges and attributes, inserted in a different order.
           Anything that iterates adjacency or node order - a BFS tie, a stable
           sort - can see the difference; a graph rebuilt with another chunk
           order or another `PYTHONHASHSEED` differs in exactly this way.
  inert    ~1% extra nodes with no edges and labels no question uses. The
           retrieval has no reason to notice them, but graphify's term weights
           are global (CLAUDE.md rule 3), so it can.

An entry *crosses* the cut when it is delivered in the real run and not in a
perturbed one, or the other way round. How far from the cut it stood in the real
run is then a measurement of how far a harmless change can push a node, and the
farthest such crossing sets the margin inside which a delivered entry counts as
fragile (`bench.FRAGILE_MARGIN`); this module says when that constant is stale.
"""
from __future__ import annotations

import random
import statistics

from .bench import (GraphAdapter, evaluate, rubric)

KINDS = ("shuffle", "inert")
INERT_FRACTION = 0.01


def _copy(G, rng: random.Random | None):
    """A structural copy of the graph; nodes and edges are inserted in the order
    `rng` shuffles them into, or in their original order when it is None."""
    H = G.__class__()
    # Drop our own memoised indexes so they are rebuilt for this copy.
    H.graph.update({k: v for k, v in G.graph.items()
                    if k not in ("_norm_index", "_source_index")})
    nodes = list(G.nodes(data=True))
    edges = (list(G.edges(keys=True, data=True)) if G.is_multigraph()
             else list(G.edges(data=True)))
    if rng is not None:
        rng.shuffle(nodes)
        rng.shuffle(edges)
    H.add_nodes_from(nodes)
    H.add_edges_from(edges)
    return H


def shuffled_copy(G, seed: int):
    """The same graph with nodes and edges inserted in a different order."""
    return _copy(G, random.Random(seed))


def with_inert_nodes(G, seed: int, fraction: float = INERT_FRACTION):
    """The same graph, in its original order, plus edgeless nodes that no
    question mentions."""
    H = _copy(G, None)
    for n in range(max(1, int(G.number_of_nodes() * fraction))):
        label = f"zzinert{seed}x{n}"
        H.add_node(f"__inert__::{seed}::{n}", label=label, norm_label=label,
                   file_type="code", source_file="", _origin="bench-inert")
    return H


def perturb(G, kind: str, seed: int):
    if kind == "shuffle":
        return shuffled_copy(G, seed)
    if kind == "inert":
        return with_inert_nodes(G, seed)
    raise ValueError(f"unknown perturbation {kind!r}; choose from {KINDS}")


def _snapshot(adapter: GraphAdapter, questions: list[dict], has_fieldmap: bool) -> dict:
    """{qid: {entry: (reached, rank, margin)}, "_nodes": served set} for the suite."""
    out = {}
    for q in questions:
        ev = evaluate(adapter, q, q["question"], has_fieldmap=has_fieldmap)
        if ev["status"] in (None, "skip"):
            continue
        out[q["id"]] = {
            "entries": {e: (e in ev["reached"], st["rank"], st["margin"])
                        for e, st in ev["standing"].items()},
            "served": {(l, s) for l, s in ev["served"]},
        }
    return out


def run_fragility(adapter: GraphAdapter, questions: list[dict], *,
                  kinds=KINDS, seeds: int = 3, log=print) -> dict:
    has_fieldmap = any(str(d.get("source_file", "")).startswith("fieldmap/")
                       for _n, d in adapter.G.nodes(data=True))
    log("[fragility] baseline")
    base = _snapshot(adapter, questions, has_fieldmap)
    kind_of = {}
    for q in questions:
        req, gaps = rubric(q)
        for e in req:
            kind_of[(q["id"], e)] = "required"
        for e in gaps:
            kind_of[(q["id"], e)] = "gap"

    per_entry: dict = {}
    runs = []
    for kind in kinds:
        # `inert`'s seed only renames the added nodes, so one run says it all.
        for seed in range(1, (seeds if kind == "shuffle" else 1) + 1):
            log(f"[fragility] {kind} seed {seed}")
            other = GraphAdapter.from_graph(perturb(adapter.G, kind, seed))
            snap = _snapshot(other, questions, has_fieldmap)
            flips, changed_answers, delta_nodes = [], 0, 0
            for qid, b in base.items():
                p = snap[qid]
                sym = len(b["served"] ^ p["served"])
                changed_answers += bool(sym)
                delta_nodes += sym
                for entry, (b_reached, b_rank, b_margin) in b["entries"].items():
                    p_reached, p_rank, p_margin = p["entries"][entry]
                    rec = per_entry.setdefault((qid, entry), {
                        "id": qid, "entry": entry, "kind": kind_of[(qid, entry)],
                        "reached": b_reached, "rank": b_rank, "margin": b_margin,
                        "flips": 0, "flip_runs": [], "max_drop": 0, "max_shift": 0})
                    if b_rank is not None and p_rank is not None:
                        rec["max_shift"] = max(rec["max_shift"], abs(p_rank - b_rank))
                    # How much nearer the cut it moved: a negative margin is a
                    # cut entry, and an entry no half reached is as far as it goes.
                    if b_margin is not None:
                        after = p_margin if p_margin is not None else -(10 ** 6)
                        rec["max_drop"] = max(rec["max_drop"], b_margin - after)
                    if b_reached != p_reached:
                        rec["flips"] += 1
                        rec["flip_runs"].append(f"{kind}#{seed}")
                        flips.append({"id": qid, "entry": entry,
                                      "from": b_reached, "to": p_reached})
            runs.append({"kind": kind, "seed": seed, "flips": flips,
                         "answers_changed": changed_answers,
                         "nodes_changed": delta_nodes})
    entries = sorted(per_entry.values(), key=lambda r: (r["id"], r["entry"]))
    return {"kinds": list(kinds), "seeds": seeds, "questions": len(base),
            "runs": runs, "entries": entries, "summary": summarise(entries)}


def summarise(entries: list[dict]) -> dict:
    """What the runs say about how near the cut is too near.

    A perturbation that moves an entry across the cut - in either direction - is
    a measurement of how far a harmless change can push a node, so the distance
    from the cut *in the real run* of every entry that crossed is what sets the
    margin: an entry closer to the cut than the farthest crossing seen is within
    reach of the same push. Entries that were in no half's answer at all have no
    distance; they are counted apart (`from_outside`)."""
    delivered_req = [e for e in entries if e["kind"] == "required" and e["reached"]]
    crossed = [e for e in entries if e["flips"]]
    distances = [abs(e["margin"]) for e in crossed if e["margin"] is not None]
    farthest = max(distances, default=None)
    lost_req = [e for e in delivered_req if e["flips"]]
    drops = [e["max_drop"] for e in delivered_req]
    suggested = 0 if farthest is None else -(-(farthest + 1) // 5) * 5
    return {
        "required_delivered": len(delivered_req),
        "required_lost": len(lost_req),
        "required_lost_entries": [f"{e['id']}:{e['entry']}" for e in lost_req],
        "crossed": len(crossed),
        "crossed_entries": [f"{e['id']}:{e['entry']}" for e in crossed],
        "from_outside": sum(e["margin"] is None for e in crossed),
        "farthest_crossing": farthest,
        "max_drop": max([d for d in drops if d < 10 ** 5] + [0]),
        "median_drop": statistics.median(drops) if drops else 0,
        "suggested_margin": suggested,
    }


def format_fragility(res: dict, margin: int) -> str:
    s = res["summary"]
    L = ["## Fragility under harmless perturbation\n",
         f"{res['questions']} graded questions re-asked on {len(res['runs'])} rebuilt graphs "
         f"({', '.join(res['kinds'])}). An entry *crosses* the cut when it is delivered in "
         f"one run and not in the other; `left` is a delivered entry dropping out, "
         f"`entered` a missing one getting in.\n",
         "| perturbation | answers changed | nodes changed | entered | left |",
         "|---|--:|--:|--:|--:|"]
    for r in res["runs"]:
        left = sum(1 for f in r["flips"] if f["from"] and not f["to"])
        L.append(f"| {r['kind']} #{r['seed']} | {r['answers_changed']} / {res['questions']} "
                 f"| {r['nodes_changed']} | {len(r['flips']) - left} | {left} |")
    L.append("")
    L.append(f"{s['required_lost']} of {s['required_delivered']} delivered required entries "
             f"dropped out in at least one run; {s['crossed']} entries crossed the cut "
             f"in all ({s['from_outside']} of them from outside both halves' answers).")
    if s["crossed_entries"]:
        L.append("")
        for e in s["crossed_entries"]:
            rec = next(r for r in res["entries"] if f"{r['id']}:{r['entry']}" == e)
            where = ("outside both halves" if rec["margin"] is None
                     else f"{abs(rec['margin'])} nodes "
                          f"{'inside' if rec['margin'] >= 0 else 'outside'} the cut")
            L.append(f"- {e}: {rec['kind']}, {where}; crossed in {', '.join(rec['flip_runs'])}")
    L.append("")
    far = s["farthest_crossing"]
    L.append(f"The farthest from the cut an entry was when a harmless change pushed it "
             f"across was {far if far is not None else 'n/a'} nodes. Suggested fragile "
             f"margin: {s['suggested_margin']} nodes (that distance plus one, rounded up to "
             f"a multiple of 5); `FRAGILE_MARGIN` is {margin}"
             + (" - STALE, raise it." if s["suggested_margin"] > margin else ".")
             + f" Delivered entries also moved by up to {s['max_drop']} nodes toward the "
             f"cut (median {s['median_drop']}), but that is mostly the head of the list "
             f"reordering, far from the cut.")
    return "\n".join(L)
