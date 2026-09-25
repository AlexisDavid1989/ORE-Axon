"""`oregraph bench` and its modes, kept out of cli.py so the entry point stays thin.

    bench                       run the suite, write the report, gate on failures
    bench --baseline OLD.json   ...and diff against an earlier results.json
    bench --promote             ...and move reached known gaps into required_nodes
    bench --explain s01[#2]     rank of every rubric node in each half; no results written
    bench --fragility           re-ask the suite on perturbed graphs; no results written
"""
from __future__ import annotations

import json
from pathlib import Path

from . import bench
from .bench_compare import compare_results, format_comparison, load_results
from .bench_edit import promote_file


def promotable(rows: list[dict], *, allow_weak: bool = False
               ) -> tuple[dict[str, list[str]], list[tuple[str, str, str]]]:
    """Which reached known gaps to move into `required_nodes`.

    Returns ({question id: [entries]}, [(id, entry, reason it was held back)]).
    An entry that only just got in, that appears for unrelated questions, or that
    is satisfied by a source-less stub would be locked in with no more meaning
    than the s34 pass had, so those stay known gaps unless `allow_weak`."""
    moves: dict[str, list[str]] = {}
    held: list[tuple[str, str, str]] = []
    for r in rows:
        if r["answer_status"] != "xpass":
            continue
        for entry in r["closed_gaps"]:
            st = r["standing"].get(entry) or {}
            reason = None
            if entry in r["weak"]:
                reason = "weak: also in the answer to " + "; ".join(
                    f'"{c}"' for c in r["weak"][entry])
            elif bench.is_fragile(st):
                reason = (f"fragile: margin {st['margin']:+d}, inside "
                          f"{bench.FRAGILE_MARGIN} nodes of the cut")
            elif st.get("stub_only"):
                reason = "stub-only: satisfied by a node with no source file"
            if reason and not allow_weak:
                held.append((r["id"], entry, reason))
            else:
                moves.setdefault(r["id"], []).append(entry)
    return moves, held


def _explain(cfg, spath: Path, target: str) -> int:
    qid, _, variant = target.partition("#")
    suite = json.loads(spath.read_text(encoding="utf-8"))
    question = next((q for q in suite["questions"] if q["id"] == qid), None)
    if question is None:
        print(f"error: no question {qid!r} in {spath}")
        return 2
    n_variants = len(bench.phrasings(question)) - 1
    try:
        index = int(variant) if variant else 0
    except ValueError:
        index = -1
    if not 0 <= index <= n_variants:
        print(f"error: {qid} has {n_variants} variant(s); use {qid} or {qid}#1..{n_variants}")
        return 2
    adapter = bench.GraphAdapter(cfg.merged_graph)
    has_fieldmap = any(str(d.get("source_file", "")).startswith("fieldmap/")
                       for _n, d in adapter.G.nodes(data=True))
    info = bench.explain_question(adapter, question, variant=index,
                                  has_fieldmap=has_fieldmap)
    print(bench.format_explain(info))
    return 0


def _fragility(cfg, spath: Path, seeds: int, kinds: list[str]) -> int:
    from . import bench_fragility as frag
    unknown = [k for k in kinds if k not in frag.KINDS]
    if unknown or not kinds or seeds < 1:
        print(f"error: --perturb takes a comma-separated list from {', '.join(frag.KINDS)} "
              f"(got {unknown or 'nothing'}), and --seeds at least 1")
        return 2
    suite = json.loads(spath.read_text(encoding="utf-8"))
    adapter = bench.GraphAdapter(cfg.merged_graph)
    res = frag.run_fragility(adapter, suite["questions"], kinds=kinds, seeds=seeds)
    text = frag.format_fragility(res, bench.FRAGILE_MARGIN)
    print("\n" + text)
    cfg.bench_out.mkdir(parents=True, exist_ok=True)
    out = cfg.bench_out / "fragility.json"
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    (cfg.bench_out / "fragility.md").write_text(text, encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


def run_command(cfg, args) -> int:
    spath = Path(args.questions) if args.questions else cfg.bench_dir / "source_questions.json"
    if args.explain:
        return _explain(cfg, spath, args.explain)
    if args.fragility:
        kinds = [k.strip() for k in args.perturb.split(",") if k.strip()]
        return _fragility(cfg, spath, args.seeds, kinds)

    # Read the baseline before the run: it is commonly the very file this run
    # is about to overwrite ($ORE_GRAPH_OUT/bench/results.json).
    baseline = load_results(Path(args.baseline)) if args.baseline else None

    result = bench.run(cfg, source_path=spath if args.questions else None)
    print("\n" + result["_report"])
    print(f"\nwrote {result['_paths']['report']}\n      {result['_paths']['results']}")
    paths = result.get("path_quality", {}).get("totals", {})
    totals = result["vs_source"]["totals"]
    rc = 1 if (paths.get("passed", 0) < paths.get("cases", 0)
               or totals["answers_failed"] or totals["variants_failed"]) else 0

    if baseline is not None:
        cmp = compare_results(baseline, result, strict=args.strict)
        print("\n" + format_comparison(cmp, str(args.baseline)))
        if not cmp["ok"]:
            rc = 1

    if args.promote:
        moves, held = promotable(result["vs_source"]["rows"],
                                 allow_weak=args.promote_all)
        for qid, entry, reason in held:
            print(f"held back {qid} {entry}: {reason}")
        if moves:
            promote_file(spath, moves)
            for qid, entries in moves.items():
                for entry in entries:
                    print(f"promoted {qid} {entry}")
            print(f"\nedited {spath}; re-run bench to refresh results.json against it")
        else:
            print("nothing to promote")
    return rc
