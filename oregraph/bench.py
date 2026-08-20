"""Measure what the curated-name mapping is worth.

`labels/` attaches a human-written `community_name` to each community; `merge.py`
writes it onto every node, and the MCP server surfaces it in `get_node`,
`get_community` and `query_graph` output. The mapping is *presentation*
metadata: it never changes graph topology, so a rebuild without it answers every
structural query identically - only the names it reports differ. This module
quantifies the difference that makes.

How it measures
---------------
It builds one control graph from the real merged graph by overwriting every
`community_name` with the pipeline's own unlabelled fallback ("<repo> / Community
<n>", exactly what `merge.py` writes for a community with no curated label), then
runs an identical question set against both. Topology, node ids, edges and
community ids are byte-for-byte identical between the two; only the names differ.

Why it does not talk to the MCP server
--------------------------------------
The graph tools' text output is produced by module-level render helpers in
`graphify.serve` (a comment there notes they are module-level precisely "so
tests can call it without an mcp install"). Calling them directly makes the
benchmark deterministic and free of the `mcp` package, the stdio handshake and
process-launch jitter, so token counts and answer-hit rates are identical on
every machine. Only wall-clock latency is machine-dependent, and it is reported
as such.

Two layers
----------
* Deterministic (always): per-query latency, response token estimate, whether a
  meaningful subsystem name is surfaced, and whether the tool output already
  contains the answer. Every number here except latency is reproducible to the
  digit across machines and across time, given the same build.
* LLM (opt-in, ``--llm``): feeds each variant's tool output to an
  OpenAI-compatible model and grades the answer, reporting accuracy, token usage
  and latency. Needs ``OPENAI_API_KEY``; skipped cleanly without it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Token estimate is a fixed regex split rather than a real BPE tokenizer on
# purpose: tiktoken is an optional dependency and its result would differ by
# encoding version, breaking the "identical on every machine" guarantee. This
# counts word runs and individual punctuation, which tracks real token counts
# closely enough to compare two variants and stays byte-stable everywhere.
_TOKEN_RE = re.compile(r"\w+|[^\w\s]")

#: Words too generic to prove a subsystem was identified, dropped from an
#: auto-derived answer key so a hit means the model named the actual subsystem.
_STOP = {"the", "and", "for", "with", "from", "using", "based", "core",
         "general", "common", "misc", "other", "util", "utils", "support"}


def estimate_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


# ---------------------------------------------------------------------------
# Control graph: same graph, curated names stripped back to the fallback.
# ---------------------------------------------------------------------------

def make_control_graph(mapped_path: Path, control_path: Path) -> dict:
    """Write a copy of the merged graph with every curated name removed.

    A node's `community_name` becomes the same "<repo> / Community <n>" string
    `merge.py` writes when a community has no curated label, derived from the
    node's own `community_key` so the result is exactly a graph built with no
    label files. Returns counts for the report.
    """
    data = json.loads(mapped_path.read_text(encoding="utf-8"))
    stripped = 0
    for n in data.get("nodes", []):
        key = n.get("community_key")
        if key and ":" in str(key):
            repo, cid = str(key).split(":", 1)
            n["community_name"] = f"{repo} / Community {cid}"
            stripped += 1
        elif "community_name" in n:
            # No community_key to rebuild from; blank it rather than leak a name.
            n["community_name"] = ""
            stripped += 1
    control_path.parent.mkdir(parents=True, exist_ok=True)
    control_path.write_text(json.dumps(data), encoding="utf-8")
    return {"nodes": len(data.get("nodes", [])), "names_stripped": stripped}


# ---------------------------------------------------------------------------
# Adapter: reproduce each MCP tool's text output from a loaded graph.
# ---------------------------------------------------------------------------

class GraphAdapter:
    """Load one graph.json and answer tool calls with the exact text the MCP
    server would return, by delegating to `graphify.serve`'s render helpers."""

    def __init__(self, graph_path: Path):
        from graphify import serve  # imported lazily: needs graphify installed
        self._serve = serve
        t0 = time.perf_counter()
        self.G = serve._load_graph(str(graph_path))
        self.communities = serve._communities_from_graph(self.G)
        self.load_seconds = time.perf_counter() - t0

    # Each body mirrors the matching closure in graphify.serve._build_server so
    # the text is identical to a live server response; see serve.py ~1698-1802.
    def _get_node(self, args: dict) -> str:
        s, G = self._serve, self.G
        label = args["label"].lower()
        matches = [(nid, d) for nid, d in G.nodes(data=True)
                   if label in (d.get("label") or "").lower() or label == nid.lower()]
        if not matches:
            return f"No node matching '{label}' found."
        nid, d = matches[0]
        return "\n".join([
            f"Node: {s.sanitize_label(d.get('label', nid))}",
            f"  ID: {s.sanitize_label(nid)}",
            f"  Source: {s.sanitize_label(str(d.get('source_file', '')))} {s.sanitize_label(str(d.get('source_location', '')))}",
            f"  Type: {s.sanitize_label(str(d.get('file_type', '')))}",
            f"  Community: {s.sanitize_label(str(d.get('community_name') or d.get('community', '')))}",
            f"  Degree: {G.degree(nid)}",
        ])

    def _get_neighbors(self, args: dict) -> str:
        s, G = self._serve, self.G
        label = args["label"].lower()
        matches = s._find_node(G, label)
        if not matches:
            return f"No node matching '{label}' found."
        rivals = s.find_node_ambiguity(G, label)
        if rivals:
            listing = "\n".join(
                f"  {G.nodes[r].get('source_file') or r}\n    id: {r}" for r in rivals)
            return (f"Ambiguous: '{label}' matches {len(rivals)} nodes in different files.\n"
                    f"{listing}\nRetry with the repo-relative path or the full node id.")
        nid = matches[0]
        lines = [f"Neighbors of {s.sanitize_label(G.nodes[nid].get('label', nid))}:"]

        def _edge_at(d: dict) -> str:
            loc = str(d.get("source_location") or "")
            return (f" at={s.sanitize_label(str(d.get('source_file') or ''))}:{s.sanitize_label(loc)}"
                    if loc else "")

        rel_filter = args.get("relation_filter", "").lower()
        for nb in G.successors(nid):
            d = s.edge_data(G, nid, nb)
            rel = d.get("relation", "")
            if rel_filter and rel_filter not in rel.lower():
                continue
            lines.append(f"  --> {s.sanitize_label(G.nodes[nb].get('label', nb))} "
                         f"[{s.sanitize_label(str(rel))}] [{s.sanitize_label(str(d.get('confidence', '')))}]{_edge_at(d)}")
        for nb in G.predecessors(nid):
            d = s.edge_data(G, nb, nid)
            rel = d.get("relation", "")
            if rel_filter and rel_filter not in rel.lower():
                continue
            lines.append(f"  <-- {s.sanitize_label(G.nodes[nb].get('label', nb))} "
                         f"[{s.sanitize_label(str(rel))}] [{s.sanitize_label(str(d.get('confidence', '')))}]{_edge_at(d)}")
        budget = int(args.get("token_budget", 2000))
        return s._cut_lines_to_budget(
            lines, budget, "Narrow with relation_filter or use get_node for a specific symbol")

    def _get_community(self, args: dict) -> str:
        s, G = self._serve, self.G
        cid = int(args["community_id"])
        nodes = self.communities.get(cid, [])
        if not nodes:
            return f"Community {cid} not found."
        header = s._community_header(cid, G.nodes[nodes[0]].get("community_name"))
        lines = [f"{header} ({len(nodes)} nodes):"]
        for n in nodes:
            d = G.nodes[n]
            lines.append(f"  {s.sanitize_label(d.get('label', n))} [{s.sanitize_label(str(d.get('source_file', '')))}]")
        budget = int(args.get("token_budget", 2000))
        return s._cut_lines_to_budget(
            lines, budget, "Raise token_budget or use get_node for specific members")

    def _query_graph(self, args: dict) -> str:
        return self._serve._query_graph_text(
            self.G, args["question"],
            mode=args.get("mode", "bfs"),
            depth=min(int(args.get("depth", 3)), 6),
            token_budget=int(args.get("token_budget", 2000)),
            context_filters=args.get("context_filter"))

    def _shortest_path(self, args: dict) -> str:
        return self._serve._shortest_path_text(self.G, args)

    def _graph_stats(self, _args: dict) -> str:
        G = self.G
        confs = [d.get("confidence", "EXTRACTED") for _, _, d in G.edges(data=True)]
        total = len(confs) or 1
        return (f"Nodes: {G.number_of_nodes()}\nEdges: {G.number_of_edges()}\n"
                f"Communities: {len(self.communities)}\n"
                f"EXTRACTED: {round(confs.count('EXTRACTED') / total * 100)}%\n"
                f"INFERRED: {round(confs.count('INFERRED') / total * 100)}%\n"
                f"AMBIGUOUS: {round(confs.count('AMBIGUOUS') / total * 100)}%\n")

    _TOOLS = {
        "get_node": _get_node,
        "get_neighbors": _get_neighbors,
        "get_community": _get_community,
        "query_graph": _query_graph,
        "shortest_path": _shortest_path,
        "graph_stats": _graph_stats,
    }

    def call(self, tool: str, args: dict, repeats: int = 1) -> tuple[str, float]:
        """Return (text, median latency in seconds over `repeats` runs)."""
        fn = self._TOOLS.get(tool)
        if fn is None:
            raise ValueError(f"unknown tool {tool!r}; known: {sorted(self._TOOLS)}")
        text = ""
        times = []
        for _ in range(max(1, repeats)):
            t0 = time.perf_counter()
            text = fn(self, args)
            times.append(time.perf_counter() - t0)
        return text, statistics.median(times)

    def curated_names(self) -> set[str]:
        """Meaningful community names present on this graph (the mapped one)."""
        out = set()
        for _, d in self.G.nodes(data=True):
            nm = d.get("community_name")
            if nm and "Community " not in str(nm):
                out.add(str(nm))
        return out


# ---------------------------------------------------------------------------
# Question suite: load, and generate a grounded default from the live graph.
# ---------------------------------------------------------------------------

def load_questions(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _answer_key(name: str) -> list[str]:
    """Distinctive lower-case words from a community name, for grading."""
    words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", name)]
    return [w for w in words if w not in _STOP][:3]


def generate_questions(cfg, out_path: Path, per_repo: int = 4) -> dict:
    """Build a grounded question set from the current mapped graph.

    Every question references a node that actually resolves on this build and a
    community name that actually attached, so the committed suite is valid
    against the graph it was generated from. Regenerate on another machine to
    ground it against that machine's build.
    """
    adapter = GraphAdapter(cfg.merged_graph)
    G = adapter.G

    # One representative high-degree node per curated community, spread by repo.
    by_comm: dict[int, tuple[int, str, str, str]] = {}  # cid -> (degree,label,repo,name)
    for nid, d in G.nodes(data=True):
        nm = d.get("community_name")
        cid = d.get("community")
        if cid is None or not nm or "Community " in str(nm):
            continue
        label = d.get("label")
        if not label or len(label) < 4:
            continue
        deg = G.degree(nid)
        cur = by_comm.get(int(cid))
        if cur is None or deg > cur[0]:
            by_comm[int(cid)] = (deg, label, str(d.get("repo") or ""), str(nm))

    per_repo_count: dict[str, int] = {}
    node_qs: list[dict] = []
    for cid, (_deg, label, repo, name) in sorted(
            by_comm.items(), key=lambda kv: -kv[1][0]):
        if per_repo_count.get(repo, 0) >= per_repo:
            continue
        # Keep only nodes get_node resolves to the intended community: its
        # substring match must return a node carrying this exact name.
        text, _ = adapter.call("get_node", {"label": label})
        if f"Community: {name}" not in text:
            continue
        key = _answer_key(name)
        if not key:
            continue
        per_repo_count[repo] = per_repo_count.get(repo, 0) + 1
        node_qs.append({
            "id": f"n{len(node_qs) + 1:02d}",
            "tool": "get_node",
            "args": {"label": label},
            "question": f"Which ORE subsystem (community) does the symbol "
                        f"'{label}' belong to? Answer with the subsystem name.",
            "expect_name": name,
            "answer_key": key,
            "repo": repo,
        })

    # A few get_community questions on the largest named communities.
    comm_qs: list[dict] = []
    for cid, (_deg, _label, repo, name) in sorted(
            by_comm.items(), key=lambda kv: -len(adapter.communities.get(kv[0], [])))[:6]:
        key = _answer_key(name)
        if not key:
            continue
        comm_qs.append({
            "id": f"c{len(comm_qs) + 1:02d}",
            "tool": "get_community",
            "args": {"community_id": cid},
            "question": f"What subsystem is community {cid}, and what does it do?",
            "expect_name": name,
            "answer_key": key,
            "repo": repo,
        })

    # Two natural-language query_graph questions (latency/token coverage; graded
    # on whether a curated subsystem name is surfaced, so no fixed answer key).
    query_qs = [
        {"id": "q01", "tool": "query_graph",
         "args": {"question": "How is a swap priced?", "mode": "bfs", "depth": 3},
         "question": "How is a swap priced in ORE?", "expect_name": None,
         "answer_key": []},
        {"id": "q02", "tool": "query_graph",
         "args": {"question": "yield curve construction", "mode": "bfs", "depth": 3},
         "question": "How is a yield curve constructed?", "expect_name": None,
         "answer_key": []},
    ]

    suite = {
        "meta": {
            "description": "Grounded ORE knowledge-graph benchmark suite. "
                           "Regenerate with `oregraph bench --generate` to ground "
                           "against your own build.",
            "generated_from": {
                "nodes": G.number_of_nodes(),
                "edges": G.number_of_edges(),
            },
        },
        "questions": node_qs + comm_qs + query_qs,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(suite, indent=2), encoding="utf-8")
    return suite


# ---------------------------------------------------------------------------
# Deterministic layer.
# ---------------------------------------------------------------------------

def _name_recognized(text: str, expect_name: str | None, curated: set[str]) -> bool:
    if expect_name:
        return expect_name.lower() in text.lower()
    low = text.lower()
    return any(nm.lower() in low for nm in curated)


def _answer_present(text: str, answer_key: list[str]) -> bool | None:
    if not answer_key:
        return None
    low = text.lower()
    return all(term in low for term in answer_key)


def run_deterministic(adapters: dict[str, GraphAdapter], questions: list[dict],
                      curated: set[str], repeats: int) -> dict:
    """Run every question against every variant; collect per-query metrics."""
    per_variant: dict[str, dict] = {}
    for variant, adapter in adapters.items():
        rows = []
        for q in questions:
            text, latency = adapter.call(q["tool"], q["args"], repeats=repeats)
            rows.append({
                "id": q["id"],
                "tool": q["tool"],
                "latency_ms": round(latency * 1000, 3),
                "resp_tokens": estimate_tokens(text),
                "resp_chars": len(text),
                "name_recognized": _name_recognized(text, q.get("expect_name"), curated),
                "answer_present": _answer_present(text, q.get("answer_key", [])),
            })
        graded = [r for r in rows if r["answer_present"] is not None]
        per_variant[variant] = {
            "load_seconds": round(adapter.load_seconds, 3),
            "rows": rows,
            "totals": {
                "questions": len(rows),
                "median_latency_ms": round(statistics.median(
                    r["latency_ms"] for r in rows), 3) if rows else 0,
                "total_resp_tokens": sum(r["resp_tokens"] for r in rows),
                "name_recognition_rate": round(
                    sum(r["name_recognized"] for r in rows) / len(rows), 4) if rows else 0,
                "answer_present_rate": round(
                    sum(bool(r["answer_present"]) for r in graded) / len(graded), 4) if graded else None,
                "graded_questions": len(graded),
            },
        }
    return per_variant


# ---------------------------------------------------------------------------
# Optional LLM layer.
# ---------------------------------------------------------------------------

class LLMUnavailable(RuntimeError):
    pass


def _llm_config() -> dict:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise LLMUnavailable(
            "OPENAI_API_KEY is not set. The LLM layer needs an OpenAI-compatible "
            "endpoint; set OPENAI_API_KEY (and optionally OPENAI_BASE_URL, "
            "OREBENCH_MODEL) or run without --llm.")
    return {
        "key": key,
        "base": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "model": os.environ.get("OREBENCH_MODEL", "gpt-4o-mini"),
    }


def _chat(cfg: dict, system: str, user: str, timeout: int = 90) -> tuple[str, dict, float]:
    body = json.dumps({
        "model": cfg["model"],
        "temperature": 0,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{cfg['base']}/chat/completions", data=body, method="POST",
        headers={"Authorization": f"Bearer {cfg['key']}",
                 "Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed https api base
        payload = json.loads(resp.read().decode("utf-8"))
    latency = time.perf_counter() - t0
    answer = payload["choices"][0]["message"]["content"] or ""
    usage = payload.get("usage", {})
    return answer, usage, latency


_LLM_SYSTEM = ("You answer questions about the ORE C++ quantitative-finance "
               "codebase using ONLY the provided graph context. If the context "
               "names a subsystem, use that name. Answer in one short sentence.")


def run_llm(adapters: dict[str, GraphAdapter], questions: list[dict],
            trials: int, log=print) -> dict:
    cfg = _llm_config()
    per_variant: dict[str, dict] = {}
    for variant, adapter in adapters.items():
        rows = []
        for q in questions:
            key = q.get("answer_key") or []
            if not key:
                continue  # ungraded question; skip in the LLM layer
            context, _ = adapter.call(q["tool"], q["args"])
            user = f"Context:\n{context}\n\nQuestion: {q['question']}\nAnswer:"
            corrects, ptoks, ctoks, ttoks, lats = [], [], [], [], []
            for _ in range(max(1, trials)):
                answer, usage, latency = _chat(cfg, _LLM_SYSTEM, user)
                low = answer.lower()
                corrects.append(all(term in low for term in key))
                ptoks.append(usage.get("prompt_tokens", 0))
                ctoks.append(usage.get("completion_tokens", 0))
                ttoks.append(usage.get("total_tokens", 0))
                lats.append(latency)
            rows.append({
                "id": q["id"], "tool": q["tool"],
                "accuracy": round(sum(corrects) / len(corrects), 4),
                "prompt_tokens": round(statistics.mean(ptoks), 1),
                "completion_tokens": round(statistics.mean(ctoks), 1),
                "total_tokens": round(statistics.mean(ttoks), 1),
                "latency_ms": round(statistics.mean(lats) * 1000, 1),
            })
            log(f"    [{variant}] {q['id']}: acc={rows[-1]['accuracy']:.0%} "
                f"tok={rows[-1]['total_tokens']:.0f}")
        per_variant[variant] = {
            "model": cfg["model"], "trials": trials, "rows": rows,
            "totals": {
                "graded_questions": len(rows),
                "accuracy": round(statistics.mean(r["accuracy"] for r in rows), 4) if rows else None,
                "mean_total_tokens": round(statistics.mean(r["total_tokens"] for r in rows), 1) if rows else None,
                "mean_latency_ms": round(statistics.mean(r["latency_ms"] for r in rows), 1) if rows else None,
            },
        }
    return per_variant


# ---------------------------------------------------------------------------
# Build-task layer: implement an instrument ORE does not have.
# ---------------------------------------------------------------------------

_BUILD_SYSTEM = (
    "You are a senior ORE (Open Source Risk Engine) C++ developer. Using ONLY "
    "the provided knowledge-graph context about the existing ORE codebase, "
    "produce a concrete implementation plan. Name the subsystem for every step. "
    "Do not invent subsystems not implied by the context or standard "
    "ORE/QuantLib layout.")


def load_build_tasks(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _assemble_context(adapter: GraphAdapter, retrieval: list[dict]) -> str:
    parts = []
    for step in retrieval:
        text, _ = adapter.call(step["tool"], step["args"])
        head = f"{step['tool']}({json.dumps(step['args'])})"
        parts.append(f"### {head}\n{text}")
    return "\n\n".join(parts)


def _rubric_hits(text: str, rubric: list[dict]) -> list[str]:
    low = text.lower()
    return [item["id"] for item in rubric
            if any(k.lower() in low for k in item["any"])]


def run_build(adapters: dict[str, GraphAdapter], tasks: list[dict],
              trials: int, log=print) -> dict:
    """Deterministic context-coverage per variant, plus optional LLM grading.

    The deterministic part measures how many of a task's required touchpoints
    the graph context already surfaces (mapped vs control) - reproducible with
    no LLM. The LLM part grades the model's actual plan against the same rubric.
    """
    llm_cfg = None
    llm_note = None
    try:
        llm_cfg = _llm_config()
    except LLMUnavailable as exc:
        llm_note = str(exc)

    per_variant: dict[str, dict] = {}
    for variant, adapter in adapters.items():
        rows = []
        for t in tasks:
            rubric = t["rubric"]
            ctx = _assemble_context(adapter, t["retrieval"])
            ctx_hits = _rubric_hits(ctx, rubric)
            row = {
                "id": t["id"],
                "instrument": t.get("instrument", t["id"]),
                "rubric_items": len(rubric),
                "context_tokens": estimate_tokens(ctx),
                "context_coverage": round(len(ctx_hits) / len(rubric), 4),
                "context_hits": ctx_hits,
            }
            if llm_cfg:
                user = t["prompt"] + "\n\nGraph context:\n" + ctx
                covs, ptoks, ctoks, ttoks, lats, all_hits = [], [], [], [], [], set()
                for _ in range(max(1, trials)):
                    answer, usage, latency = _chat(llm_cfg, _BUILD_SYSTEM, user)
                    hits = _rubric_hits(answer, rubric)
                    all_hits.update(hits)
                    covs.append(len(hits) / len(rubric))
                    ptoks.append(usage.get("prompt_tokens", 0))
                    ctoks.append(usage.get("completion_tokens", 0))
                    ttoks.append(usage.get("total_tokens", 0))
                    lats.append(latency)
                row.update({
                    "llm_coverage": round(statistics.mean(covs), 4),
                    "llm_hits": sorted(all_hits),
                    "llm_missing": sorted({i["id"] for i in rubric} - all_hits),
                    "prompt_tokens": round(statistics.mean(ptoks), 1),
                    "completion_tokens": round(statistics.mean(ctoks), 1),
                    "total_tokens": round(statistics.mean(ttoks), 1),
                    "latency_ms": round(statistics.mean(lats) * 1000, 1),
                })
                log(f"    [{variant}] {t['id']}: ctx-cov={row['context_coverage']:.0%} "
                    f"llm-cov={row['llm_coverage']:.0%} tok={row['total_tokens']:.0f}")
            else:
                log(f"    [{variant}] {t['id']}: ctx-cov={row['context_coverage']:.0%} "
                    f"({len(ctx_hits)}/{len(rubric)} touchpoints in context)")
            rows.append(row)

        totals = {
            "tasks": len(rows),
            "mean_context_coverage": round(
                statistics.mean(r["context_coverage"] for r in rows), 4) if rows else None,
            "mean_context_tokens": round(
                statistics.mean(r["context_tokens"] for r in rows), 1) if rows else None,
        }
        if llm_cfg:
            totals["mean_llm_coverage"] = round(
                statistics.mean(r["llm_coverage"] for r in rows), 4) if rows else None
            totals["mean_total_tokens"] = round(
                statistics.mean(r["total_tokens"] for r in rows), 1) if rows else None
            totals["mean_latency_ms"] = round(
                statistics.mean(r["latency_ms"] for r in rows), 1) if rows else None
        per_variant[variant] = {"rows": rows, "totals": totals}

    return {"variants": per_variant, "llm": llm_cfg is not None,
            "model": llm_cfg["model"] if llm_cfg else None,
            "trials": trials, "note": llm_note}


# ---------------------------------------------------------------------------
# Graphify-vs-source layer: the compact graph query vs reading the code.
# ---------------------------------------------------------------------------

#: The query_graph renderer prints each node as `NODE <label> [src=<file> ...]`.
_SRC_RE = re.compile(r"src=(\S+)")


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
    that answer draws from. The source total is a conservative no-graph baseline
    (it assumes the agent already knows which files to open)."""
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
        out, _ = adapter.call("query_graph", {
            "question": q["question"], "mode": q.get("mode", "bfs"),
            "depth": q.get("depth", 3), "token_budget": q.get("token_budget", 2000)})
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


# ---------------------------------------------------------------------------
# Report.
# ---------------------------------------------------------------------------

def format_report(result: dict) -> str:
    m = result["meta"]
    L: list[str] = []
    L.append("# ORE knowledge-graph mapping benchmark\n")
    L.append(f"- graphify: {m['graphify_version']}  |  python: {m['python']}  "
             f"|  PYTHONHASHSEED={m['pythonhashseed']}")
    L.append(f"- graph: {m['graph_nodes']:,} nodes / {m['graph_edges']:,} edges")
    L.append(f"- control: {m['control']['names_stripped']:,} community names stripped to fallback")
    L.append(f"- questions: {m['questions']} (suite sha256 {m['questions_sha256'][:12]})")
    L.append(f"- token count: {m['token_method']}  |  latency repeats: {m['repeats']}\n")

    det = result["deterministic"]
    variants = list(det)
    L.append("## Deterministic layer (reproducible on any machine)\n")
    L.append("| metric | " + " | ".join(variants) + " |")
    L.append("|" + "---|" * (len(variants) + 1))

    def row(label, fn):
        L.append(f"| {label} | " + " | ".join(fn(det[v]["totals"], det[v]) for v in variants) + " |")

    row("graph load (s)", lambda t, v: f"{v['load_seconds']:.2f}")
    row("median query latency (ms)", lambda t, v: f"{t['median_latency_ms']:.2f}")
    row("total response tokens", lambda t, v: f"{t['total_resp_tokens']:,}")
    row("name-recognition rate", lambda t, v: f"{t['name_recognition_rate']:.0%}")
    row("answer-in-output rate", lambda t, v:
        "n/a" if t["answer_present_rate"] is None else f"{t['answer_present_rate']:.0%}")
    L.append("")
    L.append(f"Name-recognition and answer-in-output are the mapping's direct effect: "
             f"identical topology, so any difference is the curated names alone. "
             f"({det[variants[0]]['totals']['graded_questions']} graded questions.)\n")

    if result.get("llm"):
        llm = result["llm"]
        lv = list(llm)
        L.append("## LLM layer\n")
        L.append(f"model: {llm[lv[0]]['model']}  |  trials: {llm[lv[0]]['trials']}\n")
        L.append("| metric | " + " | ".join(lv) + " |")
        L.append("|" + "---|" * (len(lv) + 1))
        L.append("| accuracy | " + " | ".join(
            "n/a" if llm[v]["totals"]["accuracy"] is None else f"{llm[v]['totals']['accuracy']:.0%}"
            for v in lv) + " |")
        L.append("| mean total tokens/Q | " + " | ".join(
            f"{llm[v]['totals']['mean_total_tokens']:.0f}" if llm[v]["totals"]["mean_total_tokens"] else "n/a"
            for v in lv) + " |")
        L.append("| mean latency (ms) | " + " | ".join(
            f"{llm[v]['totals']['mean_latency_ms']:.0f}" if llm[v]["totals"]["mean_latency_ms"] else "n/a"
            for v in lv) + " |")
        L.append("")
    elif result["meta"].get("llm_note"):
        L.append("## LLM layer\n")
        L.append(result["meta"]["llm_note"] + "\n")

    if result.get("build"):
        b = result["build"]
        bv = list(b["variants"])
        task_names = ", ".join(sorted({r["instrument"] for r in b["variants"][bv[0]]["rows"]}))
        L.append("## Build task layer — implement a missing instrument\n")
        L.append(f"task(s): {task_names}\n")
        L.append("| metric | " + " | ".join(bv) + " |")
        L.append("|" + "---|" * (len(bv) + 1))
        L.append("| touchpoints surfaced in graph context | " + " | ".join(
            f"{b['variants'][v]['totals']['mean_context_coverage']:.0%}" for v in bv) + " |")
        L.append("| context tokens | " + " | ".join(
            f"{b['variants'][v]['totals']['mean_context_tokens']:.0f}" for v in bv) + " |")
        if b["llm"]:
            L.append(f"| model plan touchpoint coverage ({b['model']}) | " + " | ".join(
                f"{b['variants'][v]['totals']['mean_llm_coverage']:.0%}" for v in bv) + " |")
            L.append("| plan tokens/task | " + " | ".join(
                f"{b['variants'][v]['totals']['mean_total_tokens']:.0f}" for v in bv) + " |")
            L.append("| plan latency (ms) | " + " | ".join(
                f"{b['variants'][v]['totals']['mean_latency_ms']:.0f}" for v in bv) + " |")
        L.append("")
        L.append("Touchpoints-in-context is deterministic: the share of a task's required "
                 "ORE subsystems the graph already names in the retrieved context. The gap "
                 "is what the curated names add to discoverability."
                 + ("" if b["llm"] else f"\n\nLLM plan grading skipped: {b['note']}") + "\n")

    if result.get("vs_source"):
        vs = result["vs_source"]
        t = vs["totals"]
        L.append("## Graphify vs no-Graphify — token cost of answering\n")
        L.append("Compact graph query vs the source files that answer draws from "
                 "(a conservative no-graph baseline: it assumes the agent already "
                 "knows which files to open).\n")
        L.append("| question | graph tok | source files | source tok | ratio |")
        L.append("|---|--:|--:|--:|--:|")
        for r in vs["rows"]:
            L.append(f"| {r['question']} | {r['graph_tokens']:,} | {r['source_files']} "
                     f"| {r['source_tokens']:,} | {r['ratio']}x |")
        L.append(f"| **total** | **{t['graph_tokens']:,}** | | **{t['source_tokens']:,}** "
                 f"| **{t['overall_ratio']}x** |")
        L.append("")
        L.append(f"Overall {t['overall_ratio']}x fewer tokens (median {t['median_ratio']}x "
                 f"per question) to reach the same answer via the graph. This is the "
                 f"graph's value, independent of the curated names.\n")

    return "\n".join(L)


# ---------------------------------------------------------------------------
# Orchestration.
# ---------------------------------------------------------------------------

def run(cfg, *, questions_path: Path | None = None, repeats: int = 3,
        with_llm: bool = False, llm_trials: int = 1, with_build: bool = False,
        build_path: Path | None = None, with_vs_source: bool = False,
        source_path: Path | None = None, log=print) -> dict:
    import importlib.metadata as ilmd

    if not cfg.merged_graph.exists():
        raise RuntimeError(f"{cfg.merged_graph} not found - run `oregraph build` first")

    qpath = questions_path or (cfg.bench_dir / "questions.json")
    if not qpath.exists():
        raise RuntimeError(
            f"{qpath} not found - run `oregraph bench --generate` to create a "
            "suite grounded on your build")
    raw = qpath.read_bytes()
    suite = json.loads(raw.decode("utf-8"))
    questions = suite["questions"]

    control_path = cfg.bench_out / "graph-control.json"
    log(f"[bench] building control graph -> {control_path}")
    control_stats = make_control_graph(cfg.merged_graph, control_path)

    log("[bench] loading mapped graph")
    mapped = GraphAdapter(cfg.merged_graph)
    log("[bench] loading control graph")
    control = GraphAdapter(control_path)
    adapters = {"mapped": mapped, "control": control}
    curated = mapped.curated_names()

    log(f"[bench] running {len(questions)} questions x {len(adapters)} variants "
        f"(repeats={repeats})")
    det = run_deterministic(adapters, questions, curated, repeats)

    result = {
        "meta": {
            "graphify_version": ilmd.version("graphifyy"),
            "python": sys.version.split()[0],
            "pythonhashseed": os.environ.get("PYTHONHASHSEED", "unset"),
            "graph_nodes": mapped.G.number_of_nodes(),
            "graph_edges": mapped.G.number_of_edges(),
            "questions": len(questions),
            "questions_sha256": hashlib.sha256(raw).hexdigest(),
            "token_method": "regex word/punct split (deterministic, no deps)",
            "repeats": repeats,
            "control": control_stats,
        },
        "deterministic": det,
    }

    if with_llm:
        try:
            log("[bench] running LLM layer")
            result["llm"] = run_llm(adapters, questions, llm_trials, log=log)
        except LLMUnavailable as exc:
            result["meta"]["llm_note"] = f"skipped: {exc}"
            log(f"[bench] LLM layer skipped: {exc}")

    if with_build:
        bpath = build_path or (cfg.bench_dir / "build_tasks.json")
        if not bpath.exists():
            raise RuntimeError(f"{bpath} not found")
        tasks = load_build_tasks(bpath)["tasks"]
        log(f"[bench] running build task layer ({len(tasks)} task(s))")
        result["build"] = run_build(adapters, tasks, llm_trials, log=log)
        result["meta"]["build_tasks_sha256"] = hashlib.sha256(
            bpath.read_bytes()).hexdigest()

    if with_vs_source:
        spath = source_path or (cfg.bench_dir / "source_questions.json")
        if not spath.exists():
            raise RuntimeError(f"{spath} not found")
        sqs = json.loads(spath.read_text(encoding="utf-8"))["questions"]
        if not cfg.engine.exists():
            raise RuntimeError(
                f"vs-source needs the ORE checkout to size source files, but "
                f"{cfg.engine} does not exist - set ORE_ENGINE")
        log(f"[bench] running Graphify-vs-source layer ({len(sqs)} questions)")
        result["vs_source"] = run_vs_source(mapped, sqs, cfg.engine, log=log)
        result["meta"]["source_questions_sha256"] = hashlib.sha256(
            spath.read_bytes()).hexdigest()

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
