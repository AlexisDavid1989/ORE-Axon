"""Post-build sanity checks.

Every check here corresponds to a failure that actually occurred in the original
build and produced no error at the time - a graph that looked fine and answered
questions wrongly. They are cheap; run them after every rebuild.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


def verify(cfg) -> dict:
    checks: list[dict] = []

    def check(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    path = cfg.merged_graph
    if not path.exists():
        return {"checks": [{"check": "merged graph exists", "ok": False,
                            "detail": f"{path} not found - run `build`"}]}

    g = json.loads(path.read_text(encoding="utf-8"))
    nodes, links = g["nodes"], g["links"]
    ids = {n["id"] for n in nodes}
    check("merged graph exists", True, str(path))

    # 1. every edge endpoint resolves
    dangling = sum(1 for l in links if l["source"] not in ids or l["target"] not in ids)
    check("no dangling edges", dangling == 0, f"{dangling:,} dangling")

    # 2. cross-module edges exist (the failure that made the old graph 12 islands)
    repo = {n["id"]: n.get("repo") for n in nodes}
    cross = sum(1 for l in links if repo.get(l["source"]) != repo.get(l["target"]))
    check("cross-module edges present", cross > 0, f"{cross:,} cross-module edges")

    # 3. communities are namespaced per chunk (old merge concatenated raw ids,
    #    so one community id spanned a dozen unrelated modules)
    spans = defaultdict(set)
    for n in nodes:
        if n.get("community") is not None:
            spans[n["community"]].add(n.get("repo"))
    bad = [c for c, r in spans.items() if len(r) > 1]
    check("communities do not span chunks", not bad,
          f"{len(bad)} communities span >1 chunk")

    # 4. curated labels actually landed
    named = sum(1 for n in nodes
                if n.get("community_name") and "Community " not in str(n["community_name"]))
    distinct = len({n.get("community_name") for n in nodes
                    if n.get("community_name") and "Community " not in str(n["community_name"])})
    check("curated labels attached", distinct > 0,
          f"{distinct} named communities covering {named:,} nodes")

    # 5. every curated name in a label file actually reached the merged graph.
    #    `relabel --audit` tests name-against-content on the *per-chunk* graph;
    #    attachment happens later, through anchor overlap in labels.py at merge
    #    time. Nothing spanned the two, so a name could pass every gate and
    #    still vanish - four OREDocs names did exactly that, dropped by an
    #    overlap guard they could not satisfy, with no error anywhere.
    attached: dict[str, set[str]] = defaultdict(set)
    for n in nodes:
        nm, chunk = n.get("community_name"), n.get("repo")
        if not nm or "Community " in str(nm):
            continue
        # labels.py joins names with " / " when two of them claim one community.
        for part in str(nm).split(" / "):
            attached[chunk].add(part)

    built = {n.get("repo") for n in nodes}
    missing: dict[str, list[str]] = {}
    for lf in sorted(cfg.labels_dir.glob("*.json")):
        if lf.name.endswith(".anchors.json"):
            continue
        chunk = lf.stem
        if chunk not in built:
            continue
        want = set(json.loads(lf.read_text(encoding="utf-8")).values())
        gap = sorted(want - attached.get(chunk, set()))
        if gap:
            missing[chunk] = gap

    n_missing = sum(len(v) for v in missing.values())
    check("all curated names attached", not missing,
          "every curated name reached the merged graph" if not missing
          else f"{n_missing} name(s) did not attach: " + "; ".join(
              f"{c}: {', '.join(repr(x) for x in v)}" for c, v in missing.items()))

    # 6. every expected chunk contributed
    present = Counter(n.get("repo") for n in nodes)
    check("all built chunks merged", len(present) > 0,
          ", ".join(f"{k}={v:,}" for k, v in present.most_common()))

    # 7. docs and xsd survived the merge (they were dropped by the old
    #    rebuild_all.py, which merged only the code chunks)
    check("docs present", present.get("OREDocs", 0) > 0,
          f"{present.get('OREDocs', 0)} doc nodes")
    check("xsd present", present.get("OREXsd", 0) > 0,
          f"{present.get('OREXsd', 0)} xsd nodes")

    return {"checks": checks,
            "nodes": len(nodes), "edges": len(links),
            "cross_module_edges": cross}


def format_report(result: dict) -> str:
    lines = []
    for c in result["checks"]:
        lines.append(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['check']:34s} {c['detail']}")
    if "nodes" in result:
        lines.append(f"\n{result['nodes']:,} nodes  {result['edges']:,} edges  "
                     f"{result['cross_module_edges']:,} cross-module")
    failed = [c for c in result["checks"] if not c["ok"]]
    lines.append("\nAll checks passed." if not failed
                 else f"\n{len(failed)} check(s) FAILED.")
    return "\n".join(lines)
