"""Compare two bench runs, question by question.

`oregraph bench` overwrites `$ORE_GRAPH_OUT/bench/results.json` on every run, so
"did this change move the answers" means copying the file aside first and
diffing afterwards by eye. CLAUDE.md rule 3 needs exactly that comparison before
and after any change to the merged graph, and it is the comparison most likely
to be skipped or skimmed, so it is a command: `bench --baseline <old.json>`.

What counts as a regression
---------------------------
Anything that makes an answer worse *in a way the rubric can see*:

  * a question that now fails (or is now skipped for want of a fieldmap);
  * a required entry that is newly missing, or a known gap that had been
    reached and no longer is;
  * a required entry that has newly become *weak* (turns up in the answers to
    unrelated questions - the s34 failure);
  * a paraphrase variant that now fails or loses a node.

Everything else that differs is reported but does not fail the command: token
counts and source-file counts (informational, and nearly constant now that
every answer spends the whole budget), a changed answer hash, entries that have
become fragile. `strict=True` promotes *any* difference to a failure, for the
case CLAUDE.md asks for - a graph change that should be bench-identical.

Old results written before a field existed simply lack it; only fields present
in both runs are compared, so an older baseline still works for the ones it has.
"""
from __future__ import annotations

import json
from pathlib import Path


def load_results(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _rubric_now(row: dict) -> set[str]:
    """Every rubric entry of a row, from what it recorded about them."""
    return (set(row.get("reached_nodes") or []) | set(row.get("missing_nodes") or [])
            | set(row.get("known_gaps") or []))


def _diff_row(old: dict, new: dict) -> tuple[list[str], list[str], list[str]]:
    """(regressions, other changes, improvements) for one question."""
    regress: list[str] = []
    info: list[str] = []
    better: list[str] = []

    o_stat, n_stat = old.get("answer_status"), new.get("answer_status")
    if o_stat != n_stat:
        line = f"status {str(o_stat).upper()} -> {str(n_stat).upper()}"
        if n_stat == "fail" or (n_stat == "skip" and o_stat not in (None, "skip")):
            regress.append(line)
        elif o_stat == "fail":
            better.append(line)
        else:
            info.append(line)

    o_miss, n_miss = set(old.get("missing_nodes") or []), set(new.get("missing_nodes") or [])
    if n_miss - o_miss:
        regress.append("now missing: " + ", ".join(sorted(n_miss - o_miss)))
    if o_miss - n_miss:
        better.append("no longer missing: " + ", ".join(sorted(o_miss - n_miss)))

    # An entry the old run reached and this one does not - covers a reopened
    # known gap, which `missing_nodes` (required only) cannot see.
    if "reached_nodes" in old and "reached_nodes" in new:
        lost = [e for e in old["reached_nodes"]
                if e in _rubric_now(new) and e not in new["reached_nodes"]
                and e not in n_miss - o_miss]
        gained = [e for e in new["reached_nodes"]
                  if e in _rubric_now(old) and e not in old["reached_nodes"]
                  and e not in o_miss - n_miss]
    else:
        lost = [e for e in old.get("closed_gaps") or []
                if e in (new.get("known_gaps") or [])]
        gained = [e for e in new.get("closed_gaps") or []
                  if e not in (old.get("closed_gaps") or [])]
    if lost:
        regress.append("no longer reached: " + ", ".join(lost))
    if gained:
        better.append("newly reached: " + ", ".join(gained))

    if "weak" in old and "weak" in new:
        newly_weak = sorted(set(new["weak"]) - set(old["weak"]))
        if newly_weak:
            regress.append("newly weak (appears for unrelated questions): "
                           + ", ".join(newly_weak))
        cured = sorted(set(old["weak"]) - set(new["weak"]))
        if cured:
            better.append("no longer weak: " + ", ".join(cured))
    if "fragile" in old and "fragile" in new:
        newly = sorted(set(new["fragile"]) - set(old["fragile"]))
        if newly:
            info.append("newly fragile: " + ", ".join(newly))

    for field, label in (("graph_tokens", "tokens"), ("source_files", "source files"),
                         ("source_tokens", "source tokens")):
        if field in old and field in new and old[field] != new[field]:
            info.append(f"{label} {old[field]:,} -> {new[field]:,}")
    if "answer_sha256" in old and "answer_sha256" in new \
            and old["answer_sha256"] != new["answer_sha256"] \
            and not (regress or info or better):
        info.append("answer changed (same status, tokens and files)")
    elif "answer_sha256" in old and "answer_sha256" in new \
            and old["answer_sha256"] != new["answer_sha256"]:
        info.append("answer changed")

    o_var = {v["question"]: v for v in old.get("variants") or []}
    for v in new.get("variants") or []:
        prev = o_var.get(v["question"])
        if prev is None:
            continue
        # A recorded paraphrase gap that has stopped failing is not a
        # regression when it starts again, but one that passed and now fails is,
        # whichever list it sits in.
        if v["answer_status"] == "fail" and prev["answer_status"] != "fail":
            regress.append(f"variant \"{v['question']}\" now fails")
        elif set(v.get("lost") or []) - set(prev.get("lost") or []):
            regress.append(f"variant \"{v['question']}\" now loses "
                           + ", ".join(sorted(set(v["lost"]) - set(prev.get("lost") or []))))
        elif prev["answer_status"] == "fail" and v["answer_status"] != "fail":
            better.append(f"variant \"{v['question']}\" no longer fails")
    return regress, info, better


def compare_results(old: dict, new: dict, *, strict: bool = False) -> dict:
    """Diff two results.json documents. `ok` is False on any regression, or on
    any difference at all when `strict`."""
    o_rows = {r["id"]: r for r in old["vs_source"]["rows"]}
    n_rows = {r["id"]: r for r in new["vs_source"]["rows"]}
    changes = []
    for qid, n in n_rows.items():
        o = o_rows.get(qid)
        if o is None:
            continue
        regress, info, better = _diff_row(o, n)
        if regress or info or better:
            changes.append({"id": qid, "question": n["question"],
                            "regressions": regress, "other": info, "improved": better})
    added = [q for q in n_rows if q not in o_rows]
    # A question that vanished takes its rubric with it: coverage lost silently.
    removed = [q for q in o_rows if q not in n_rows]
    regressions = sum(bool(c["regressions"]) for c in changes) + len(removed)
    o_t, n_t = old["vs_source"]["totals"], new["vs_source"]["totals"]
    totals = {}
    for key in ("answers_passed", "answers_failed", "xfail", "xpass", "delivered",
                "rubric_total", "precision", "precision_at_10", "weak_entries",
                "fragile_entries", "graph_tokens"):
        if key in o_t and key in n_t:
            totals[key] = (o_t[key], n_t[key])
    identical = not changes and not removed and not added
    return {
        "changes": changes, "added": added, "removed": removed,
        "regressions": regressions, "totals": totals, "identical": identical,
        "strict": strict,
        "ok": not regressions and (identical or not strict),
        "old_meta": old.get("meta", {}), "new_meta": new.get("meta", {}),
    }


def format_comparison(cmp: dict, baseline: str = "baseline") -> str:
    L = [f"## Against {baseline}\n"]
    om, nm = cmp["old_meta"], cmp["new_meta"]
    if om.get("graphify_version") != nm.get("graphify_version"):
        L.append(f"- graphify {om.get('graphify_version')} -> {nm.get('graphify_version')}")
    if om.get("graph_nodes") != nm.get("graph_nodes") or om.get("graph_edges") != nm.get("graph_edges"):
        L.append(f"- graph {om.get('graph_nodes'):,} nodes / {om.get('graph_edges'):,} edges -> "
                 f"{nm.get('graph_nodes'):,} / {nm.get('graph_edges'):,}")
    if om.get("questions_sha256") != nm.get("questions_sha256"):
        L.append("- the question file changed between the two runs")
    if cmp["identical"]:
        L.append("\nIdentical: no question differs in status, tokens, source files, "
                 "missing nodes or answer.\n")
    else:
        L.append(f"\n{len(cmp['changes'])} questions changed; "
                 f"**{cmp['regressions']} regression(s)**.\n")
    for c in cmp["changes"]:
        tag = "REGRESSION" if c["regressions"] else ("improved" if c["improved"] else "changed")
        L.append(f"- {c['id']} ({c['question']}): {tag}")
        for line in c["regressions"]:
            L.append(f"    - REGRESSION: {line}")
        for line in c["improved"]:
            L.append(f"    - improved: {line}")
        for line in c["other"]:
            L.append(f"    - {line}")
    for q in cmp["removed"]:
        L.append(f"- {q}: REGRESSION - question removed since the baseline")
    if cmp["added"]:
        L.append(f"- added since the baseline: {', '.join(cmp['added'])}")
    if cmp["totals"]:
        L.append("")
        L.append("| metric | baseline | now |")
        L.append("|---|--:|--:|")
        for key, (a, b) in cmp["totals"].items():
            L.append(f"| {key} | {a} | {b} |")
    L.append("")
    if cmp["strict"] and not cmp["identical"]:
        L.append("--strict: the run is not identical to the baseline.")
    return "\n".join(L)
