"""Measure Graphify's token cost against reading the source it points to.

The graph answers a question in one compact `query_graph` call (~1-2k tokens).
The no-graph baseline is the token size of the source files that answer draws
from - the code an agent would otherwise have to read to answer the same thing.
That baseline is *generous to the no-graph side*: it assumes the agent already
knows exactly which files to open, which is itself what the graph provides. The
real no-graph alternative is grepping and reading whole modules, so the true
saving is larger than the ratio reported here.

Cost is only half of it
-----------------------
A cheaper answer is not a better one, so a question may also carry a
`required_nodes` rubric naming nodes the answer has to contain. Without one a
question measures cost only, and a change that drops the right node while
getting cheaper reads as an improvement - which is how a retrieval regression
hides. `xfail_nodes` records a rubric the graph does not satisfy yet.

Presence is not proof
---------------------
Every answer now spends the whole ~2,000-token budget, so cost no longer tells
answers apart, and "the node is somewhere in a ~90-node answer" is a weak thing
to assert. Four things make a passing entry say more:

  * `controls` - unrelated questions of the same shape. A required node that
    turns up in their answers is *weak*: its presence shows the node is a hub,
    not that the retrieval understood the question. s34 required
    `Swap [pricing engine mapping]` and passed for a question about a bond,
    because graphify seeded the word "fieldmap" on the best-connected entry.
  * rank and margin - where the node sits in the fused ranking and how far that
    is from the token-budget cut. A node ranked 90th of 91 is *fragile*.
  * `variants` - paraphrases graded against the same rubric. A rubric tuned
    while reading one wording is not evidence about the others.
  * `delivered` and `precision` - how much of the rubric arrived, and how much
    of what came back is not generic noise (see `noise_kind`).

`why` records, per rubric entry, the reason it is expected. It is required from
the question named by `meta.why_required_from` on, so the expectation is
written down independently of the answer it is later graded against.

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

#: The query_graph renderer prints each node as `NODE <label> [src=<file> loc=<loc>
#: community=<name>]`. The source runs to " loc=", not to the next space: a fieldmap
#: entry's is `fieldmap/trade/Interest Rate Swaption`, which `\S*` cut to
#: `fieldmap/trade/Interest`, so no rubric entry could name it in full.
_SRC_RE = re.compile(r"src=(\S+)")
_NODE_RE = re.compile(r"^NODE (.+?) \[src=(.*?) loc=", re.M)

#: A required entry within this many nodes of the token-budget cut is *fragile*.
#: Not a guess: see docs/BENCH.md, "Fragile margin". `bench --fragility` rebuilt
#: the graph 11 ways that change no fact in it (10 node/edge orders, and 1% extra
#: inert nodes); entries crossed the cut from as far as 23 nodes away, so 23 + 1,
#: rounded up to a multiple of 5. Inside it, a harmless rebuild can push the entry
#: out. It is a floor: an entry outside both halves' answers also got in once, and
#: a real change (the fusion function, graphify's retrieval) moves nodes further.
#: `--fragility` says when this is stale.
FRAGILE_MARGIN = 25

#: Precision is also read over an answer's first `_HEAD` nodes: an answer that
#: opens with noise (s34's began `Envelope`, `TradeActions`, `Size`, `string`,
#: `vector`) wastes the part a reader looks at first.
_HEAD = 10


def estimate_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


# ---------------------------------------------------------------------------
# Rubric entries: parsing and matching
# ---------------------------------------------------------------------------

def parse_nodes(output: str) -> list[tuple[str, str]]:
    """(label, source file) of every NODE line, in answer order."""
    return _NODE_RE.findall(output)


def entry_matches(entry: str, label: str, src: str) -> bool:
    """Whether one node satisfies one rubric entry.

    An entry is one of:
      `PiecewiseYieldCurve`                     - a node label, matched whole
      `YieldCurve@marketdata/yieldcurve.hpp`    - label from a particular file
      `src:Tools/`                              - any node drawn from that path

    Labels match whole, not as substrings, so requiring `Swap` is not satisfied
    by `SwapIndex`; duplicate labels across files are why the `@` form exists.
    The `src:` form is for questions about a body of code rather than a symbol
    ("what does the tools front end do"), where naming one node would be
    arbitrary but the answer still has to come from the right place.
    """
    if entry.startswith("src:"):
        return entry[4:] in src
    want, _, frag = entry.partition("@")
    return label == want and (not frag or frag in src)


def entry_rank(nodes: list[tuple[str, str]], entry: str) -> int | None:
    """1-based position of the first node satisfying `entry`, or None."""
    for i, (label, src) in enumerate(nodes, 1):
        if entry_matches(entry, label, src):
            return i
    return None


def _missing_nodes(output: str, required: list[str]) -> list[str]:
    """Which rubric entries the answer failed to satisfy."""
    found = parse_nodes(output)
    return [req for req in required if entry_rank(found, req) is None]


def _needs_fieldmap(entry: str) -> bool:
    return entry.removeprefix("src:").partition("@")[2].startswith("fieldmap/") \
        or entry.startswith("src:fieldmap/")


def grade_answer(output: str, question: dict, *, has_fieldmap: bool = True
                 ) -> tuple[str | None, list[str], list[str]]:
    """Grade one answer: (status, missing required, missing known-gap).

    `required_nodes` is what the answer must contain and is what gates the
    command. `xfail_nodes` states what the answer *should* also contain but
    demonstrably does not yet - reported, never gating, so a known gap is
    recorded rather than either forgotten or left souring the suite. Splitting
    the two matters on a question that is half right: the working half still
    gates while the gap stays visible, which a question-level xfail cannot do.
    An `xfail_nodes` entry that starts passing is reported as `xpass` so it can
    be promoted.

    A rubric naming a `fieldmap/...` path is skipped when the graph was merged
    without a fieldmap snapshot, since that merge is opt-in and its absence is
    not a regression.
    """
    required = question.get("required_nodes") or []
    gaps = question.get("xfail_nodes") or []
    if not required and not gaps:
        return None, [], []
    if not has_fieldmap and any(_needs_fieldmap(e) for e in required + gaps):
        return "skip", [], []
    missing_req = _missing_nodes(output, required)
    missing_gap = _missing_nodes(output, gaps)
    if missing_req:
        status = "fail"
    elif gaps and len(missing_gap) < len(gaps):
        status = "xpass"
    elif gaps:
        status = "xfail"
    else:
        status = "pass"
    return status, missing_req, missing_gap


def rubric(question: dict) -> tuple[list[str], list[str]]:
    """(required entries, known-gap entries) of a question."""
    return (list(question.get("required_nodes") or []),
            list(question.get("xfail_nodes") or []))


def phrasings(question: dict) -> list[str]:
    """The question as asked, then its paraphrase variants (the ones that gate,
    then the known-failing `xfail_variants`)."""
    return [question["question"], *(question.get("variants") or []),
            *(question.get("xfail_variants") or [])]


def controls_for(question: dict, entry: str) -> list[str]:
    """Negative-control questions for one required entry.

    `controls` is a list (applies to every required entry of the question) or a
    dict keyed by entry, with `"*"` for the ones that apply to all."""
    raw = question.get("controls") or []
    if isinstance(raw, dict):
        raw = list(raw.get("*", [])) + list(raw.get(entry, []))
    out: list[str] = []
    for c in raw:
        if c not in out:
            out.append(c)
    return out


def _qnum(qid: str) -> int | None:
    m = re.fullmatch(r"s(\d+)", str(qid))
    return int(m.group(1)) if m else None


def check_suite(suite: dict) -> list[str]:
    """Structural problems in a question file. Empty means well formed.

    Shared by `verify` and the unit tests, so a malformed rubric is caught
    where the suite is edited rather than surfacing as a strange bench result."""
    problems: list[str] = []
    seen_ids: set[str] = set()
    why_from = _qnum(str((suite.get("meta") or {}).get("why_required_from", "")))
    for q in suite.get("questions", []):
        qid = q.get("id", "?")
        if qid in seen_ids:
            problems.append(f"{qid}: duplicate question id")
        seen_ids.add(qid)
        req, gaps = rubric(q)
        entries = req + gaps
        for e in set(entries):
            if entries.count(e) > 1:
                problems.append(f"{qid}: entry {e!r} appears more than once in the rubric")
        why = q.get("why") or {}
        variants = q.get("variants") or []
        xvariants = q.get("xfail_variants") or []
        for key in why:
            if key not in entries and key not in xvariants:
                problems.append(f"{qid}: why names {key!r}, which is not a rubric entry "
                                "or an xfail variant")
        # A phrasing that is known to fail is a gap someone chose to record, so
        # the reason is written down whatever the question's age.
        for v in xvariants:
            if not str(why.get(v, "")).strip():
                problems.append(f"{qid}: xfail variant {v!r} has no `why`")
        n = _qnum(qid)
        if why_from is not None and n is not None and n >= why_from:
            for e in entries:
                if not str(why.get(e, "")).strip():
                    problems.append(f"{qid}: rubric entry {e!r} has no `why`")
        seen_v: list[str] = []
        for v in variants + xvariants:
            if not isinstance(v, str) or not v.strip():
                problems.append(f"{qid}: empty variant")
            elif v.strip().lower() == q["question"].strip().lower() or v in seen_v:
                problems.append(f"{qid}: variant {v!r} repeats another phrasing")
            seen_v.append(v)
        if (variants or xvariants) and not entries:
            problems.append(f"{qid}: variants without a rubric grade nothing")
        raw = q.get("controls") or []
        if raw and not entries:
            problems.append(f"{qid}: controls without a rubric entry test nothing")
        if isinstance(raw, dict):
            for key in raw:
                if key != "*" and key not in entries:
                    problems.append(f"{qid}: controls key {key!r} is not a rubric entry")
            flat = [c for v in raw.values() for c in v]
        else:
            flat = list(raw)
        own = {p.strip().lower() for p in phrasings(q)}
        for c in flat:
            if not isinstance(c, str) or not c.strip():
                problems.append(f"{qid}: empty control")
            elif c.strip().lower() in own:
                problems.append(f"{qid}: control {c!r} is the question itself")
    return problems


# ---------------------------------------------------------------------------
# Rank, margin, noise
# ---------------------------------------------------------------------------

def standing(ranked: list[tuple[str, str]], cutoff: int, entry: str) -> dict:
    """Where one rubric entry sits in the fused ranking.

    `ranked` is every candidate the fusion produced, best first; `cutoff` is how
    many the token budget let through. `margin` is the number of nodes between
    the entry and the cut: 0 means it is the last node kept, negative means it
    was cut (and by how many places). `support` counts satisfying nodes that
    made it into the answer - a `src:` entry met by forty nodes is not in the
    danger a single hit at the edge is. `stub_only` marks an entry met only by
    a node with no source file, i.e. a reference to a symbol the corpus never
    defines, which shows the label was mentioned and nothing more."""
    hits = [i for i, (label, src) in enumerate(ranked)
            if entry_matches(entry, label, src)]
    kept = [i for i in hits if i < cutoff]
    rank = hits[0] + 1 if hits else None
    return {
        "rank": rank,
        "margin": cutoff - rank if rank else None,
        "support": len(kept),
        "stub_only": bool(kept) and all(not ranked[i][1] for i in kept),
    }


def is_fragile(info: dict, margin: int | None = None) -> bool:
    """Delivered, but closer to the cut than a harmless rebuild can move it."""
    threshold = FRAGILE_MARGIN if margin is None else margin
    m = info.get("margin")
    return m is not None and 0 <= m < threshold


#: Labels that name the language, its standard library or QuantLib's scalar
#: typedefs. They are in the graph because code mentions them, and they turn up
#: in an answer because they are hubs, not because they answer anything.
GENERIC_LABELS = frozenset("""
string vector map set list pair tuple array deque unordered_map unordered_set
shared_ptr unique_ptr weak_ptr optional any function ostream istream
stringstream size_t ptrdiff_t bool int double float char long unsigned void
boost std
Real Size Integer Natural Rate Spread Time DiscountFactor Volatility Decimal
BigInteger BigNatural Probability
""".split())

#: Headers pulled in by nearly every translation unit. Their file nodes carry no
#: information about what a question asked.
GENERIC_HEADERS = frozenset("""
types.hpp qldefines.hpp shared_ptr.hpp optional.hpp any.hpp null.hpp all.hpp
errors.hpp config.hpp
""".split())


def noise_kind(label: str, src: str) -> str | None:
    """Why a returned node is generic noise, or None if it is content.

    "stub": no source file - a symbol the code refers to and the corpus never
    defines (`string`, `vector`, `Handle`), so it cannot say where anything is.
    "generic": a defined node that is language vocabulary (`GENERIC_LABELS`) or
    a universal header (`GENERIC_HEADERS`).

    A fixed list on purpose: a definition derived from the suite's own answers
    would move whenever the suite did, and two runs could not be compared."""
    if not src:
        return "stub"
    if label in GENERIC_LABELS or label in GENERIC_HEADERS:
        return "generic"
    return None


def noise_counts(nodes: list[tuple[str, str]]) -> dict:
    stub = sum(noise_kind(l, s) == "stub" for l, s in nodes)
    generic = sum(noise_kind(l, s) == "generic" for l, s in nodes)
    n = len(nodes)
    head = nodes[:_HEAD]
    head_noise = sum(noise_kind(l, s) is not None for l, s in head)
    return {
        "stub": stub, "generic": generic,
        "precision": round((n - stub - generic) / n, 4) if n else None,
        "precision_at_10": round((len(head) - head_noise) / len(head), 4) if head else None,
    }


def _answer_sha(nodes: list[tuple[str, str]]) -> str:
    text = "\n".join(f"{label}\t{src}" for label, src in nodes)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

class GraphAdapter:
    """Load one graph.json and answer `query_graph` with the exact text the MCP
    server would return.

    That is `oregraph.serve`'s merged answer, not graphify's alone - the two
    must stay the same call, or the benchmark stops describing what the server
    actually serves. `graphify_only` keeps the old path available as the
    baseline a change is measured against."""

    def __init__(self, graph_path: Path | None = None, *, graph=None):
        from graphify import serve  # imported lazily: needs graphify installed
        self._serve = serve
        if graph is not None:
            self.G = graph
            self.path_graph = None
            return
        from .query import load_path_graph
        self.G = serve._load_graph(str(graph_path))
        self.path_graph = load_path_graph(graph_path)

    @classmethod
    def from_graph(cls, graph) -> "GraphAdapter":
        """An adapter over an in-memory graph (used to bench a perturbed copy)."""
        return cls(graph=graph)

    def answer(self, question: str, *, mode: str = "bfs", depth: int = 3,
               token_budget: int = 2000):
        """The served answer together with the two halves it was fused from."""
        from .query import query_graph_answer
        return query_graph_answer(
            self.G, question, mode=mode, depth=min(int(depth), 6),
            token_budget=int(token_budget))

    def query_graph(self, question: str, *, mode: str = "bfs", depth: int = 3,
                    token_budget: int = 2000) -> str:
        return self.answer(question, mode=mode, depth=depth,
                           token_budget=token_budget).text

    def graphify_only(self, question: str, *, mode: str = "bfs", depth: int = 3,
                      token_budget: int = 2000) -> str:
        return self._serve._query_graph_text(
            self.G, question, mode=mode, depth=min(int(depth), 6),
            token_budget=int(token_budget))

    def oregraph_only(self, question: str, *, mode: str = "bfs", depth: int = 3,
                      token_budget: int = 2000) -> str:
        from .query import query_question
        return query_question(
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


def _shape(q: dict) -> dict:
    return {"mode": q.get("mode", "bfs"), "depth": q.get("depth", 3),
            "token_budget": q.get("token_budget", 2000)}


def evaluate(adapter: GraphAdapter, q: dict, phrase: str, *,
             has_fieldmap: bool = True) -> dict:
    """Ask one phrasing of `q` and grade the answer against its rubric.

    Shared by the suite run, the paraphrase variants, the fragility check and
    `--explain`, so every view of a question grades the same served answer."""
    ans = adapter.answer(phrase, **_shape(q))
    out = ans.text
    status, missing_req, missing_gap = grade_answer(out, q, has_fieldmap=has_fieldmap)
    served = parse_nodes(out)
    ranked = parse_nodes("\n".join(ans.ranked))
    required, gaps = rubric(q)
    entries = required + gaps
    graded = status not in (None, "skip")
    stands = {e: standing(ranked, ans.shown, e) for e in entries} if graded else {}
    missing = set(missing_req) | set(missing_gap)
    reached = [e for e in entries if e not in missing] if graded else []
    return {
        "answer": ans, "text": out, "served": served, "ranked": ranked,
        "status": status, "missing_req": missing_req, "missing_gap": missing_gap,
        "reached": reached, "standing": stands,
        "fragile": [e for e in required if e in stands and is_fragile(stands[e])],
        "stub_only": [e for e in required if e in stands and stands[e]["stub_only"]],
        "noise": noise_counts(served), "sha": _answer_sha(served),
        "rubric_total": len(entries) if graded else 0,
    }


def run_controls(adapter: GraphAdapter, q: dict, cache: dict,
                 entries: list[str] | None = None) -> tuple[dict, int]:
    """Which entries also appear in the answers to unrelated questions.

    Returns ({entry: [control question, ...]} for the weak ones, number of
    control queries the question needed). Controls are asked with the question's
    own mode, depth and budget, since "the same shape" is the point. `entries`
    defaults to the required ones; the suite run adds known gaps it has reached,
    so `--promote` can refuse to lock in one that would be weak."""
    if entries is None:
        entries = rubric(q)[0]
    per_entry = {e: controls_for(q, e) for e in entries}
    weak: dict[str, list[str]] = {}
    asked: set[str] = set()
    for entry, controls in per_entry.items():
        for control in controls:
            key = (control, tuple(sorted(_shape(q).items())))
            if key not in cache:
                cache[key] = parse_nodes(adapter.answer(control, **_shape(q)).text)
            asked.add(control)
            if entry_rank(cache[key], entry) is not None:
                weak.setdefault(entry, []).append(control)
    return weak, len(asked)


def _variant_row(adapter: GraphAdapter, q: dict, phrase: str, has_fieldmap: bool,
                 main: dict, known_gap: bool = False) -> dict:
    """One paraphrase graded against the question's rubric. `known_gap` marks an
    `xfail_variants` phrasing: reported, never gating, and it says when it starts
    to pass."""
    ev = evaluate(adapter, q, phrase, has_fieldmap=has_fieldmap)
    return {
        "question": phrase,
        "known_gap_variant": known_gap,
        "answer_status": ev["status"],
        "graph_tokens": estimate_tokens(ev["text"]),
        "missing_nodes": ev["missing_req"],
        "known_gaps": ev["missing_gap"],
        "delivered": len(ev["reached"]),
        "rubric_total": ev["rubric_total"],
        "fragile": ev["fragile"],
        "answer_sha256": ev["sha"],
        # entries the original phrasing reached and this one does not
        "lost": [e for e in main["reached"] if e not in ev["reached"]],
    }


def run_vs_source(adapter: GraphAdapter, questions: list[dict], engine: Path,
                  log=print) -> dict:
    """For each question: tokens the graph returns vs tokens of the source files
    that answer draws from, plus how well the answer satisfies its rubric."""
    resolver = _source_resolver(adapter, engine)
    has_fieldmap = any(str(d.get("source_file", "")).startswith("fieldmap/")
                       for _n, d in adapter.G.nodes(data=True))
    tok_cache: dict = {}
    control_cache: dict = {}

    def file_tokens(p: Path):
        if p not in tok_cache:
            try:
                tok_cache[p] = estimate_tokens(p.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                tok_cache[p] = None
        return tok_cache[p]

    rows = []
    appearances: dict[tuple, int] = {}
    for q in questions:
        ev = evaluate(adapter, q, q["question"], has_fieldmap=has_fieldmap)
        out, status = ev["text"], ev["status"]
        graph_tok = estimate_tokens(out)
        abspaths: set = set()
        for s in set(_SRC_RE.findall(out)):
            abspaths |= resolver.get(s, set())
        present = [p for p in abspaths if file_tokens(p) is not None]
        source_tok = sum(file_tokens(p) for p in present)
        ratio = round(source_tok / graph_tok, 1) if graph_tok else None
        gaps = q.get("xfail_nodes") or []
        graded = status not in (None, "skip")
        weak, n_controls = ({}, 0)
        if graded:
            weak, n_controls = run_controls(
                adapter, q, control_cache,
                rubric(q)[0] + [g for g in gaps if g in ev["reached"]])
        variants = ([*(_variant_row(adapter, q, v, has_fieldmap, ev)
                       for v in q.get("variants") or []),
                     *(_variant_row(adapter, q, v, has_fieldmap, ev, known_gap=True)
                       for v in q.get("xfail_variants") or [])] if graded else [])
        for key in set(ev["served"]):
            appearances[key] = appearances.get(key, 0) + 1
        rows.append({
            "id": q["id"], "question": q["question"],
            "graph_tokens": graph_tok, "source_files": len(present),
            "source_tokens": source_tok, "ratio": ratio,
            "unresolved_files": len(abspaths) - len(present),
            "answer_status": status,
            "required_nodes": len(q.get("required_nodes") or []),
            "missing_nodes": ev["missing_req"],
            "known_gaps": ev["missing_gap"],
            "closed_gaps": [g for g in gaps if g not in ev["missing_gap"]] if graded else [],
            "truncated": "TRUNCATED" in out,
            "answer_sha256": ev["sha"],
            "nodes_returned": len(ev["served"]),
            "candidates": len(ev["ranked"]),
            "cutoff": ev["answer"].shown,
            "rubric_total": ev["rubric_total"],
            "delivered": len(ev["reached"]),
            "reached_nodes": ev["reached"],
            "noise": {"stub": ev["noise"]["stub"], "generic": ev["noise"]["generic"]},
            "precision": ev["noise"]["precision"],
            "precision_at_10": ev["noise"]["precision_at_10"],
            "standing": ev["standing"],
            "fragile": ev["fragile"],
            "stub_only": ev["stub_only"],
            "weak": weak,
            "controls_run": n_controls,
            "variants": variants,
        })
        log(f"    {q['id']}: graph={graph_tok} tok  source={source_tok:,} tok "
            f"({len(present)} files)  {ratio}x"
            + (f"  answer={status.upper()}" if status else "")
            + (f" missing={ev['missing_req']}" if ev["missing_req"] else "")
            + (f" WEAK={sorted(weak)}" if weak else "")
            + (f" variants_failed={sum(v['answer_status'] == 'fail' for v in variants if not v['known_gap_variant'])}"
               if any(v["answer_status"] == "fail" and not v["known_gap_variant"]
                      for v in variants) else ""))

    tot_g = sum(r["graph_tokens"] for r in rows)
    tot_s = sum(r["source_tokens"] for r in rows)
    graded_rows = [r for r in rows if r["answer_status"] not in (None, "skip")]
    n_nodes = sum(r["nodes_returned"] for r in graded_rows)
    n_noise = sum(r["noise"]["stub"] + r["noise"]["generic"] for r in graded_rows)
    delivered = sum(r["delivered"] for r in graded_rows)
    total = sum(r["rubric_total"] for r in graded_rows)
    req_total = sum(r["required_nodes"] for r in graded_rows)
    req_missing = sum(len(r["missing_nodes"]) for r in graded_rows)
    all_variants = [v for r in graded_rows for v in r["variants"]]
    variant_rows = [v for v in all_variants if not v["known_gap_variant"]]
    gap_variants = [v for v in all_variants if v["known_gap_variant"]]
    ubiquitous = sorted(
        ((label, src, n) for (label, src), n in appearances.items()
         if n >= max(3, len(rows) // 4) and noise_kind(label, src) is None),
        key=lambda t: (-t[2], t[0]))[:12]
    return {
        "rows": rows,
        "totals": {
            "questions": len(rows),
            "graph_tokens": tot_g,
            "source_tokens": tot_s,
            "overall_ratio": round(tot_s / tot_g, 1) if tot_g else None,
            "median_ratio": round(statistics.median(
                r["ratio"] for r in rows if r["ratio"] is not None), 1) if rows else None,
            "asserted": len(graded_rows),
            "no_rubric": sum(r["answer_status"] is None for r in rows),
            "skipped": sum(r["answer_status"] == "skip" for r in rows),
            "answers_passed": sum(r["answer_status"] == "pass" for r in graded_rows),
            "answers_failed": sum(r["answer_status"] == "fail" for r in graded_rows),
            "xfail": sum(r["answer_status"] == "xfail" for r in graded_rows),
            "xpass": sum(r["answer_status"] == "xpass" for r in graded_rows),
            # delivered: rubric entries present / all rubric entries (required
            # and known-gap alike). The pass count is all-or-nothing per
            # question; this one moves when a single node comes or goes.
            "delivered": delivered,
            "rubric_total": total,
            "required_delivered": req_total - req_missing,
            "required_total": req_total,
            "gaps_closed": delivered - (req_total - req_missing),
            "gaps_total": total - req_total,
            "nodes_returned": n_nodes,
            "noise_nodes": n_noise,
            "precision": round((n_nodes - n_noise) / n_nodes, 4) if n_nodes else None,
            "precision_at_10": round(statistics.mean(
                r["precision_at_10"] for r in graded_rows
                if r["precision_at_10"] is not None), 4) if graded_rows else None,
            "weak_entries": sum(len(r["weak"]) for r in rows),
            "fragile_entries": sum(len(r["fragile"]) for r in rows),
            "stub_only_entries": sum(len(r["stub_only"]) for r in rows),
            "variants": len(variant_rows),
            "variants_failed": sum(v["answer_status"] == "fail" for v in variant_rows),
            "variants_lost": sum(bool(v["lost"]) for v in variant_rows),
            # xfail_variants: phrasings known to fail; reported, never gating
            "variants_known_gaps": len(gap_variants),
            "variants_xfail": sum(v["answer_status"] == "fail" for v in gap_variants),
            "variants_xpass": sum(v["answer_status"] != "fail" for v in gap_variants),
            "controls_run": sum(r["controls_run"] for r in rows),
            "ubiquitous": [{"label": l, "src": s, "answers": n}
                           for l, s, n in ubiquitous],
        },
    }


# ---------------------------------------------------------------------------
# --explain
# ---------------------------------------------------------------------------

#: How much larger than the question's own budget the "where would it rank
#: with room to spare" probe is. Absent from a 2,000-token answer says nothing
#: about *how far off* a node is; ten times the room usually settles it.
DEEP_FACTOR = 10


def explain_question(adapter: GraphAdapter, q: dict, *, variant: int = 0,
                     has_fieldmap: bool = True) -> dict:
    """For each rubric entry: its rank in graphify's half, in oregraph's half
    and in the fused answer, and how far that is from the token-budget cut.

    A half only shows what fits its own budget, so an entry missing from it may
    be one place or two hundred places short. `deep_*` re-asks the half with
    `DEEP_FACTOR` times the budget to say which."""
    phrase = phrasings(q)[variant]
    shape = _shape(q)
    ev = evaluate(adapter, q, phrase, has_fieldmap=has_fieldmap)
    ans = ev["answer"]
    g_nodes = parse_nodes(ans.graphify)
    o_nodes = parse_nodes(ans.ours)
    deep_shape = {**shape, "token_budget": shape["token_budget"] * DEEP_FACTOR}
    g_deep = parse_nodes(adapter.graphify_only(phrase, **deep_shape))
    o_deep = parse_nodes(adapter.oregraph_only(phrase, **deep_shape))
    required, gaps = rubric(q)
    rows = []
    for kind, entries in (("required", required), ("gap", gaps)):
        for e in entries:
            st = ev["standing"].get(e) or standing(ev["ranked"], ans.shown, e)
            first = next(((l, s) for l, s in ev["ranked"] if entry_matches(e, l, s)), None)
            rows.append({
                "entry": e, "kind": kind,
                "graphify": entry_rank(g_nodes, e), "graphify_deep": entry_rank(g_deep, e),
                "oregraph": entry_rank(o_nodes, e), "oregraph_deep": entry_rank(o_deep, e),
                "merged": st["rank"], "margin": st["margin"],
                "support": st["support"], "stub_only": st["stub_only"],
                "fragile": kind == "required" and is_fragile(st),
                "delivered": e in ev["reached"], "matched": first,
            })
    return {
        "id": q["id"], "variant": variant, "question": phrase, **shape,
        "status": ev["status"], "shown": ans.shown, "candidates": len(ev["ranked"]),
        "graphify_nodes": len(g_nodes), "oregraph_nodes": len(o_nodes),
        "graphify_deep_nodes": len(g_deep), "oregraph_deep_nodes": len(o_deep),
        "deep_budget": deep_shape["token_budget"],
        "noise": ev["noise"], "rows": rows,
    }


def _cell(rank: int | None, deep: int | None) -> str:
    if rank is not None:
        return f"#{rank}"
    return f"-(#{deep})" if deep is not None else "-"


def format_explain(info: dict) -> str:
    tag = f"{info['id']}" + (f"#{info['variant']}" if info["variant"] else "")
    L = [f"{tag}: {info['question']}",
         f"  {info['mode']} depth {info['depth']}, budget {info['token_budget']} tokens; "
         f"status {str(info['status']).upper()}",
         f"  fused: {info['shown']} nodes kept of {info['candidates']} candidates "
         f"(graphify half {info['graphify_nodes']}, oregraph half {info['oregraph_nodes']}); "
         f"precision {info['noise']['precision']} (P@10 {info['noise']['precision_at_10']})",
         f"  '-(#n)' = absent from that half's own answer, but rank n with "
         f"{info['deep_budget']}-token room (graphify {info['graphify_deep_nodes']} nodes, "
         f"oregraph {info['oregraph_deep_nodes']})",
         ""]
    width = max([len(r["entry"]) for r in info["rows"]] + [5])
    L.append(f"  {'entry'.ljust(width)}  {'kind':8} {'graphify':>10} {'oregraph':>10} "
             f"{'merged':>7} {'margin':>7}  note")
    for r in info["rows"]:
        merged = f"#{r['merged']}" if r["merged"] else "-"
        margin = f"{r['margin']:+d}" if r["margin"] is not None else "-"
        notes = []
        if not r["delivered"]:
            notes.append("CUT" if r["merged"] else "NOT REACHED")
        if r["fragile"]:
            notes.append(f"FRAGILE (<{FRAGILE_MARGIN})")
        if r["stub_only"]:
            notes.append("STUB-ONLY (matched node has no source file)")
        if r["support"] > 1:
            notes.append(f"{r['support']} matching nodes")
        if r["matched"] and r["delivered"] and r["matched"][1]:
            notes.append(f"via {r['matched'][0]} [{r['matched'][1]}]")
        L.append(f"  {r['entry'].ljust(width)}  {r['kind']:8} "
                 f"{_cell(r['graphify'], r['graphify_deep']):>10} "
                 f"{_cell(r['oregraph'], r['oregraph_deep']):>10} "
                 f"{merged:>7} {margin:>7}  {'; '.join(notes)}")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Golden paths
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _pct(n: int, d: int) -> str:
    return f"{n / d:.1%}" if d else "n/a"


def format_report(result: dict) -> str:
    m = result["meta"]
    vs = result["vs_source"]
    t = vs["totals"]
    L: list[str] = []
    L.append("# Graphify vs no-Graphify - token cost of answering\n")
    L.append(f"- graphify: {m['graphify_version']}  |  python: {m['python']}  "
             f"|  PYTHONHASHSEED={m['pythonhashseed']}")
    L.append(f"- graph: {m['graph_nodes']:,} nodes / {m['graph_edges']:,} edges")
    L.append(f"- questions: {m['questions']} (suite sha256 {m['questions_sha256'][:12]})")
    L.append(f"- token count: {m['token_method']}\n")
    L.append("Compact graph query vs the source files that answer draws from (a "
             "conservative no-graph baseline: it assumes the agent already knows "
             "which files to open).\n")
    L.append("| question | graph tok | source files | source tok | ratio | delivered | precision | answer |")
    L.append("|---|--:|--:|--:|--:|--:|--:|---|")
    for r in vs["rows"]:
        status = r["answer_status"]
        delivered = f"{r['delivered']}/{r['rubric_total']}" if r["rubric_total"] else "-"
        prec = f"{r['precision']:.2f}" if r.get("precision") is not None else "-"
        L.append(f"| {r['question']} | {r['graph_tokens']:,} | {r['source_files']} "
                 f"| {r['source_tokens']:,} | {r['ratio']}x | {delivered} | {prec} "
                 f"| {status.upper() if status else '-'} |")
    L.append(f"| **total** | **{t['graph_tokens']:,}** | | **{t['source_tokens']:,}** "
             f"| **{t['overall_ratio']}x** | **{t['delivered']}/{t['rubric_total']}** "
             f"| **{t['precision'] or 0:.2f}** | |")
    L.append("")
    L.append(f"Overall {t['overall_ratio']}x fewer tokens (median {t['median_ratio']}x "
             f"per question) to reach the same answer via the graph. Every answer "
             f"spends the whole budget, so the token column no longer tells answers "
             f"apart - read the answer-content section below.\n")
    L.append("## Answer content\n")
    skipped = (f", {t['skipped']} skipped for want of a fieldmap snapshot"
               if t["skipped"] else "")
    L.append(f"{t['answers_passed']}/{t['asserted']} asserted answers contained every "
             f"node their rubric requires. {t['no_rubric']} of {t['questions']} "
             f"questions carry no rubric and measure cost only{skipped}.\n")
    L.append(f"- **delivered**: {t['delivered']}/{t['rubric_total']} rubric nodes present "
             f"({_pct(t['delivered'], t['rubric_total'])}) - required "
             f"{t['required_delivered']}/{t['required_total']}, known gaps closed "
             f"{t['gaps_closed']}/{t['gaps_total']}")
    L.append(f"- **precision**: {_pct(t['nodes_returned'] - t['noise_nodes'], t['nodes_returned'])} "
             f"of the {t['nodes_returned']:,} returned nodes are not generic noise; "
             f"mean precision over each answer's first 10 nodes is "
             f"{t['precision_at_10']:.1%}. Noise = a node with no source file (a "
             f"symbol the corpus never defines) or a language/QuantLib-typedef label "
             f"or universal header (`GENERIC_LABELS`, `GENERIC_HEADERS` in bench.py)")
    if t.get("ubiquitous"):
        L.append("- ubiquitous but not on the stoplist (in a quarter of answers or "
                 "more): " + ", ".join(f"{u['label']} ({u['answers']})"
                                       for u in t["ubiquitous"]))
    L.append("")
    for r in vs["rows"]:
        if r["answer_status"] == "fail":
            L.append(f"- **FAIL {r['id']}** ({r['question']}): "
                     + ", ".join(r["missing_nodes"]))
        elif r["answer_status"] == "xpass":
            L.append(f"- **XPASS {r['id']}** ({r['question']}): now reached, "
                     f"promote to required_nodes: " + ", ".join(r["closed_gaps"]))
    gaps = [r for r in vs["rows"] if r["known_gaps"]]
    if gaps:
        L.append(f"\n{sum(len(r['known_gaps']) for r in gaps)} known gaps across "
                 f"{len(gaps)} questions - nodes the answer should reach and does "
                 f"not. These do not gate the command.\n")
        for r in gaps:
            L.append(f"- {r['id']} ({r['question']}): "
                     + ", ".join(r["known_gaps"]))
    L.append("")
    L.extend(_quality_section(vs))
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


def _quality_section(vs: dict) -> list[str]:
    """What the passing entries are worth: weak, fragile, stub-only, paraphrases."""
    t = vs["totals"]
    L = ["## How much a pass proves\n"]
    covered = sum(1 for r in vs["rows"] if r["controls_run"])
    L.append(f"{t['controls_run']} negative-control queries ran for {covered} questions; "
             f"an entry is *weak* when its node also appears in the answer to an "
             f"unrelated question of the same shape. An entry is *fragile* when it "
             f"is delivered but within {FRAGILE_MARGIN} nodes of the token-budget "
             f"cut (margin = nodes between it and the cut).\n")
    weak = [r for r in vs["rows"] if r["weak"]]
    if weak:
        L.append(f"**{t['weak_entries']} weak entries** - presence proves nothing:\n")
        for r in weak:
            for entry, controls in r["weak"].items():
                gap = (" (a known gap it has reached: do not promote)"
                       if entry in r["closed_gaps"] else "")
                L.append(f"- {r['id']} `{entry}`{gap} also answers: "
                         + "; ".join(f"\"{c}\"" for c in controls))
        L.append("")
    else:
        L.append("No weak entries.\n")
    fragile = [r for r in vs["rows"] if r["fragile"]]
    if fragile:
        L.append(f"**{t['fragile_entries']} fragile entries:**\n")
        for r in fragile:
            for entry in r["fragile"]:
                st = r["standing"][entry]
                L.append(f"- {r['id']} `{entry}` rank {st['rank']}, margin {st['margin']:+d} "
                         f"(cutoff {r['cutoff']} of {r['candidates']} candidates)")
        L.append("")
    stub = [r for r in vs["rows"] if r["stub_only"]]
    if stub:
        L.append(f"**{t['stub_only_entries']} stub-only entries** - satisfied only by a "
                 f"node with no source file:\n")
        for r in stub:
            for entry in r["stub_only"]:
                L.append(f"- {r['id']} `{entry}`")
        L.append("")
    if t["variants"] or t.get("variants_known_gaps"):
        L.append(f"**Paraphrases**: {t['variants']} variants graded against the same "
                 f"rubric; {t['variants_failed']} fail, {t['variants_lost']} lose a node "
                 f"the original wording reached. A further {t.get('variants_known_gaps', 0)} "
                 f"phrasings are recorded as known paraphrase gaps (`xfail_variants`: "
                 f"{t.get('variants_xfail', 0)} still fail, "
                 f"{t.get('variants_xpass', 0)} now pass and can move to `variants`); "
                 f"those do not gate.\n")
        for r in vs["rows"]:
            for v in r["variants"]:
                gap = v.get("known_gap_variant")
                if gap and v["answer_status"] == "fail":
                    continue       # a recorded gap, still failing: nothing to say
                if gap or v["answer_status"] == "fail" or v["lost"] or v["fragile"]:
                    lost = f" lost {', '.join(v['lost'])}" if v["lost"] else ""
                    tag = "known gap now PASSES" if gap else str(v["answer_status"]).upper()
                    L.append(f"- {r['id']} \"{v['question']}\": {tag}{lost}"
                             + (f" fragile {', '.join(v['fragile'])}" if v["fragile"] else ""))
        L.append("")
    return L


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
    suite = json.loads(raw.decode("utf-8"))
    problems = check_suite(suite)
    if problems:
        raise RuntimeError("the question file is malformed:\n  " + "\n  ".join(problems))
    questions = suite["questions"]

    log("[bench] loading graph")
    adapter = GraphAdapter(cfg.merged_graph)
    log(f"[bench] running {len(questions)} questions (graph vs source)")
    vs = run_vs_source(adapter, questions, cfg.engine, log=log)
    path_suite = cfg.bench_dir / "path_questions.json"
    path_raw = path_suite.read_bytes()
    path_cases = json.loads(path_raw.decode("utf-8"))["paths"]
    log(f"[bench] running {len(path_cases)} golden paths")
    path_quality = run_path_quality(adapter, path_cases, log=log)

    gstat = cfg.merged_graph.stat()
    result = {
        "meta": {
            "graphify_version": ilmd.version("graphifyy"),
            "python": sys.version.split()[0],
            "pythonhashseed": os.environ.get("PYTHONHASHSEED", "unset"),
            "graph_nodes": adapter.G.number_of_nodes(),
            "graph_edges": adapter.G.number_of_edges(),
            "graph_size": gstat.st_size,
            "graph_mtime_ns": gstat.st_mtime_ns,
            "questions": len(questions),
            "questions_sha256": hashlib.sha256(raw).hexdigest(),
            "paths_sha256": hashlib.sha256(path_raw).hexdigest(),
            "token_method": "regex word/punct split (deterministic, no deps)",
            "fragile_margin": FRAGILE_MARGIN,
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
