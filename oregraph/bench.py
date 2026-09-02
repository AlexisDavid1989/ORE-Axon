"""Measure Graphify's token cost against reading the source it points to.

The graph answers a question in one compact `query_graph` call (~1-2k tokens).
The no-graph baseline is the token size of the source files that answer draws
from - the code an agent would otherwise have to read to answer the same thing.
That baseline is *generous to the no-graph side*: it assumes the agent already
knows exactly which files to open, which is itself what the graph provides. The
real no-graph alternative is grepping and reading whole modules, so the true
saving is larger than the ratio reported here.

Why it does not talk to the MCP server
--------------------------------------
`query_graph`'s text output is produced by a module-level render helper in
`graphify.serve` (a comment there notes it is module-level precisely "so tests
can call it without an mcp install"). Calling it directly makes the benchmark
deterministic and free of the `mcp` package, the stdio handshake and
process-launch jitter, so the token numbers are identical on every machine given
the same build.
"""
from __future__ import annotations

import hashlib
import importlib.metadata as ilmd
import json
import os
import re
import statistics
import sys
from pathlib import Path

# Token estimate is a fixed regex split rather than a real BPE tokenizer on
# purpose: tiktoken is an optional dependency and its result would differ by
# encoding version, breaking the "identical on every machine" guarantee. This
# counts word runs and individual punctuation, which tracks real token counts
# closely enough for the comparison and stays byte-stable everywhere.
_TOKEN_RE = re.compile(r"\w+|[^\w\s]")

#: The query_graph renderer prints each node as `NODE <label> [src=<file> ...]`.
_SRC_RE = re.compile(r"src=(\S+)")


def estimate_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


class GraphAdapter:
    """Load one graph.json and answer `query_graph` with the exact text the MCP
    server would return, by delegating to `graphify.serve`'s render helper."""

    def __init__(self, graph_path: Path):
        from graphify import serve  # imported lazily: needs graphify installed
        from .query import load_path_graph
        self._serve = serve
        self.G = serve._load_graph(str(graph_path))
        self.path_graph = load_path_graph(graph_path)

    def query_graph(self, question: str, *, mode: str = "bfs", depth: int = 3,
                    token_budget: int = 2000) -> str:
        return self._serve._query_graph_text(
            self.G, question, mode=mode, depth=min(int(depth), 6),
            token_budget=int(token_budget))


def load_questions(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_resolver(adapter: GraphAdapter, engine: Path) -> dict[str, set]:
    """Map a node's `source_file` string to the absolute file(s) it names in the
    ORE checkout, using each chunk's root."""
    from .chunks import BY_NAME
    out: dict[str, set] = {}
    for _nid, d in adapter.G.nodes(data=True):
        sf, repo = d.get("source_file"), d.get("repo")
        if not sf or repo not in BY_NAME:
            continue
        out.setdefault(sf, set()).add(engine / BY_NAME[repo].root / sf)
    return out


def run_vs_source(adapter: GraphAdapter, questions: list[dict], engine: Path,
                  log=print) -> dict:
    """For each question: tokens the graph returns vs tokens of the source files
    that answer draws from."""
    resolver = _source_resolver(adapter, engine)
    tok_cache: dict = {}

    def file_tokens(p: Path):
        if p not in tok_cache:
            try:
                tok_cache[p] = estimate_tokens(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                tok_cache[p] = None
        return tok_cache[p]

    rows = []
    for q in questions:
        out = adapter.query_graph(
            q["question"], mode=q.get("mode", "bfs"), depth=q.get("depth", 3),
            token_budget=q.get("token_budget", 2000))
        graph_tok = estimate_tokens(out)
        abspaths: set = set()
        for s in set(_SRC_RE.findall(out)):
            abspaths |= resolver.get(s, set())
        present = [p for p in abspaths if file_tokens(p) is not None]
        source_tok = sum(file_tokens(p) for p in present)
        ratio = round(source_tok / graph_tok, 1) if graph_tok else None
        rows.append({
            "id": q["id"], "question": q["question"],
            "graph_tokens": graph_tok, "source_files": len(present),
            "source_tokens": source_tok, "ratio": ratio,
            "unresolved_files": len(abspaths) - len(present),
        })
        log(f"    {q['id']}: graph={graph_tok} tok  source={source_tok:,} tok "
            f"({len(present)} files)  {ratio}x")

    tot_g = sum(r["graph_tokens"] for r in rows)
    tot_s = sum(r["source_tokens"] for r in rows)
    return {
        "rows": rows,
        "totals": {
            "questions": len(rows),
            "graph_tokens": tot_g,
            "source_tokens": tot_s,
            "overall_ratio": round(tot_s / tot_g, 1) if tot_g else None,
            "median_ratio": round(statistics.median(
                r["ratio"] for r in rows if r["ratio"] is not None), 1) if rows else None,
        },
    }


def run_path_quality(adapter: GraphAdapter, cases: list[dict], log=print) -> dict:
    """Check that compact paths contain the relations required by a rubric."""
    from .query import query_path

    rows = []
    for case in cases:
        output = query_path(adapter.path_graph, case["symbols"],
                            max_hops=case.get("max_hops", 12))
        tokens = estimate_tokens(output)
        missing = [relation for relation in case.get("required_relations", [])
                   if f"--{relation}" not in output]
        failed = output.startswith(("NO ", "PATH TOO LONG"))
        passed = (not failed and not missing
                  and tokens <= case.get("max_tokens", 2000))
        rows.append({
            "id": case["id"],
            "symbols": case["symbols"],
            "tokens": tokens,
            "missing_relations": missing,
            "passed": passed,
        })
        log(f"    {case['id']}: {'PASS' if passed else 'FAIL'}  "
            f"tokens={tokens}  missing={missing or '-'}")
    return {"rows": rows,
            "totals": {"cases": len(rows),
                       "passed": sum(row["passed"] for row in rows)}}


def format_report(result: dict) -> str:
    m = result["meta"]
    vs = result["vs_source"]
    t = vs["totals"]
    L: list[str] = []
    L.append("# Graphify vs no-Graphify — token cost of answering\n")
    L.append(f"- graphify: {m['graphify_version']}  |  python: {m['python']}  "
             f"|  PYTHONHASHSEED={m['pythonhashseed']}")
    L.append(f"- graph: {m['graph_nodes']:,} nodes / {m['graph_edges']:,} edges")
    L.append(f"- questions: {m['questions']} (suite sha256 {m['questions_sha256'][:12]})")
    L.append(f"- token count: {m['token_method']}\n")
    L.append("Compact graph query vs the source files that answer draws from (a "
             "conservative no-graph baseline: it assumes the agent already knows "
             "which files to open).\n")
    L.append("| question | graph tok | source files | source tok | ratio |")
    L.append("|---|--:|--:|--:|--:|")
    for r in vs["rows"]:
        L.append(f"| {r['question']} | {r['graph_tokens']:,} | {r['source_files']} "
                 f"| {r['source_tokens']:,} | {r['ratio']}x |")
    L.append(f"| **total** | **{t['graph_tokens']:,}** | | **{t['source_tokens']:,}** "
             f"| **{t['overall_ratio']}x** |")
    L.append("")
    L.append(f"Overall {t['overall_ratio']}x fewer tokens (median {t['median_ratio']}x "
             f"per question) to reach the same answer via the graph.\n")
    paths = result.get("path_quality")
    if paths:
        L.append("## Golden implementation paths\n")
        L.append("| path | tokens | missing relations | result |")
        L.append("|---|--:|---|---|")
        for row in paths["rows"]:
            missing = ", ".join(row["missing_relations"]) or "-"
            status = "PASS" if row["passed"] else "FAIL"
            L.append(f"| {row['id']} | {row['tokens']:,} | {missing} | {status} |")
        totals = paths["totals"]
        L.append(f"\n{totals['passed']}/{totals['cases']} golden paths passed.\n")
    return "\n".join(L)


def run(cfg, *, source_path: Path | None = None, log=print) -> dict:
    if not cfg.merged_graph.exists():
        raise RuntimeError(f"{cfg.merged_graph} not found - run `oregraph build` first")
    if not cfg.engine.exists():
        raise RuntimeError(
            f"the ORE checkout is needed to size source files, but {cfg.engine} "
            "does not exist - set ORE_ENGINE")

    spath = source_path or (cfg.bench_dir / "source_questions.json")
    if not spath.exists():
        raise RuntimeError(f"{spath} not found")
    raw = spath.read_bytes()
    questions = json.loads(raw.decode("utf-8"))["questions"]

    log("[bench] loading graph")
    adapter = GraphAdapter(cfg.merged_graph)
    log(f"[bench] running {len(questions)} questions (graph vs source)")
    vs = run_vs_source(adapter, questions, cfg.engine, log=log)
    path_suite = cfg.bench_dir / "path_questions.json"
    path_raw = path_suite.read_bytes()
    path_cases = json.loads(path_raw.decode("utf-8"))["paths"]
    log(f"[bench] running {len(path_cases)} golden paths")
    path_quality = run_path_quality(adapter, path_cases, log=log)

    result = {
        "meta": {
            "graphify_version": ilmd.version("graphifyy"),
            "python": sys.version.split()[0],
            "pythonhashseed": os.environ.get("PYTHONHASHSEED", "unset"),
            "graph_nodes": adapter.G.number_of_nodes(),
            "graph_edges": adapter.G.number_of_edges(),
            "questions": len(questions),
            "questions_sha256": hashlib.sha256(raw).hexdigest(),
            "paths_sha256": hashlib.sha256(path_raw).hexdigest(),
            "token_method": "regex word/punct split (deterministic, no deps)",
        },
        "vs_source": vs,
        "path_quality": path_quality,
    }

    cfg.bench_out.mkdir(parents=True, exist_ok=True)
    (cfg.bench_out / "results.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8")
    report = format_report(result)
    (cfg.bench_out / "report.md").write_text(report, encoding="utf-8")
    result["_report"] = report
    result["_paths"] = {
        "results": str(cfg.bench_out / "results.json"),
        "report": str(cfg.bench_out / "report.md"),
    }
    return result
