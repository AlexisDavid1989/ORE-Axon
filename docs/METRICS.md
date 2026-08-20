# Metrics baseline — 2026-08-17

Two cheap, reproducible measurements, recorded here so future builds can be
compared against them instead of re-deriving from scratch. Neither changes
pipeline behaviour; `link.py` now *surfaces* numbers it was already computing
(see "Include recall" below), and the latency numbers are read-only queries
against the built graph.

Graph this was measured against:

| | |
|---|---|
| Nodes | 90,374 |
| Edges | 190,550 |
| Cross-module edges | 14,168 (verify's independent recount) / 14,499 (link.py's own add-count, pre-dedup) |
| Curated community names attached | 524 communities |

Reproduce with `python -m oregraph verify` (recall) and the benchmark script
described below (latency).

---

## 1. Cross-module include recall

`link.py` resolves C++ `#include` directives to graph nodes to create the
cross-chunk edges that make OREData → QuantExt → QuantLib traversal possible
(see its module docstring). Until now it counted `unresolved_includes` but
never reported it anywhere, and never counted includes that didn't even match
one of `INCLUDE_ROOTS` (`ql/`, `qle/`, `ored/`, `orea/`) — those simply never
entered the count at all. `oregraph merge` and `oregraph verify` now print the
full breakdown (`link.py::scan_includes` / `link.py::link`).

```
total_includes         31,736
resolved_includes      27,312   (86%)
unresolved_includes         6   (ORE prefix matched, no indexed node)
ignored_non_ore_prefix  4,418   (no INCLUDE_ROOTS prefix matched at all)
```

**Headline: 86% of all `#include` directives in the scanned tree resolve to a
graph node.** The other 14% breaks down as follows.

### Correctly ignored — 4,333 of 4,418 (14.1% → 13.7% of total)

Not ORE code, so not resolvable and not wanted:

| Prefix | Count | What it is |
|---|---:|---|
| `(system, no subdir)` | 2,300 | `<vector>`, `<cmath>`, `<memory>`, … stdlib |
| `boost/` | 1,475 | third-party |
| `(same-directory relative)` | 550 | `"foo.hpp"` quoted includes with no path — same-directory, already covered by each chunk's own AST extraction, not a cross-*chunk* relationship |
| `sys/`, `unsupported/`, `OpenCL/`, `CL/`, `Eigen/`, `mach/` | 9 | other third-party / platform headers |

### Should have resolved but didn't — 85 of 4,418 (0.27% of total)

Genuine ORE-internal include prefixes that `INCLUDE_ROOTS` doesn't know about,
all confined to the test-utility chunks (**not** the four primary labelled
modules QuantLib/QuantExt/OREData/OREAnalytics, so this does not affect the
"OREData → QuantExt → QuantLib in 3 hops" claim in the README):

| Prefix | Count | Resolves to | Used by |
|---|---:|---|---|
| `test/` | 39 | `OREData/test/`, `OREAnalytics/test/`, `QuantLib/test-suite/` | ORETests chunk |
| `oret/` | 37 | `ORETest/oret/` (shared test utilities) | ORETests chunk |
| `fuzzer/` | 6 | `QuantLib/fuzz-test-suite/` | QuantLibFuzzTests chunk |
| `test-suite/` | 3 | `QuantLib/test-suite/` | ORETests chunk |

Not fixed here — flagged for a future `INCLUDE_ROOTS` addition if anyone
needs cross-chunk traversal *within* the test-utility chunks specifically.

### Unresolved despite a matching ORE prefix — 6 occurrences / 4 unique targets

| Target | Cause |
|---|---|
| `QuantExt/qle/gitversion.hpp` | generated at build time, not present in a source checkout — expected |
| `QuantLib/ql/config.hpp` | generated at configure time — expected |
| `QuantExt/qle/termstructures//blacktriangulationatmvol.hpp` | **double-slash typo in ORE's own source** (`OREData/ored/marketdata/market.cpp:28`); the single-slash form of the same include resolves fine from 4 other call sites |
| `QuantLib/ql/pricingengines//barrier/analyticdoublebarrierengine.hpp` | same typo pattern (`OREData/ored/portfolio/builders/equitydoublebarrieroption.hpp:29`) |

The two generated-file misses are expected and not fixable from a checkout.
The two double-slash cases are a real, if tiny (2 edges), false negative — our
path matching doesn't normalize repeated slashes. Not fixed here; noted for
whoever next touches `link.py`.

**Net:** of 31,736 total includes, 31,645 (99.7%) are accounted for correctly
(resolved, or correctly ignored, or an expected generated-file miss). 91
(0.29%) are known, low-priority gaps, none of which touch the four primary
modules.

---

## 2. MCP server latency

Measured with the official `mcp` Python client SDK talking to
`python -m graphify.serve <merged-graph>` over stdio — the same command
`oregraph mcp` writes into `.mcp.json`. Three runs each, median reported.

| Measurement | Runs | Median |
|---|---|---:|
| Cold start (process launch → `initialize` returns) | 4.72s, 4.77s, 4.70s | **4.72s** |
| `get_neighbors("Instrument")` (high-degree node, warm server) | 0.525s, 0.511s, 0.503s | **0.511s** |
| `shortest_path("SwapEngineBuilder", "DiscountingSwapEngine")` (warm server) | 0.069s, 0.019s, 0.020s | **0.020s** |

**Cold start is ~4.7s, under the ~10s threshold worth flagging — no adoption
problem today.** Worth re-checking after a graph size increase (e.g. once
`Examples/` XML/CSV gets semantically extracted); cold start is presumably
dominated by loading and indexing the 90k-node / 190k-edge JSON into
networkx, so it should scale with graph size.

`get_neighbors` on a genuinely high-degree node (`Instrument`, which the
README uses as its own "works well" example) costs ~0.5s — noticeably slower
than `shortest_path`, which resolves in ~20ms once the fuzzy label match
narrows to a start/end pair. Neither is slow enough to be a UX problem in an
agent session, but `get_neighbors` is the one to watch if it grows with graph
size.

Reproduce: see the benchmark script pattern — `StdioServerParameters(command=<cfg.python>, args=["-m", "graphify.serve", str(cfg.merged_graph)])`
via `mcp.client.stdio.stdio_client` + `mcp.ClientSession`, timing
`session.initialize()` for cold start and `session.call_tool(...)` for query
latency. Not committed as a script here since it's one-off measurement, not
pipeline code.

---

## 3. What the curated-name mapping is worth — `oregraph bench`

The names in `labels/` are *presentation* metadata: `merge.py` writes a
`community_name` onto every node and the MCP server surfaces it, but they never
change topology, so every structural query returns the same nodes and edges with
or without them. `oregraph bench` isolates the difference the names alone make.

It builds a **control graph** from the real merged graph by overwriting every
`community_name` with the pipeline's own unlabelled fallback (`<repo> / Community
<n>`, exactly what `merge.py` writes for an unlabelled community), so mapped and
control are byte-identical apart from the names. It then runs one question set
against both, reproducing each MCP tool's text output by calling
`graphify.serve`'s module-level render helpers directly — no `mcp` package, no
stdio handshake, no process-launch jitter — so every metric except wall-clock
latency is identical on any machine.

```
python -m oregraph bench --generate     # ground a suite on your build (once)
python -m oregraph bench                 # deterministic layer
python -m oregraph bench --llm           # + LLM answer accuracy (needs OPENAI_API_KEY)
```

`--generate` writes `bench/questions.json` from the current graph: one question
per curated community (a high-degree member whose `get_node` resolves back to
that community), plus `get_community` and `query_graph` questions. Regenerate on
another checkout to ground the suite against that build; the committed suite
records its own graph node/edge counts and every run prints the suite's sha256.

**Deterministic layer** (identical to the digit across machines and time, given
the same build; only latency is machine-dependent):

- **name-recognition rate** — does the answer surface a meaningful subsystem name?
- **answer-in-output rate** — does the tool output already contain the answer key?
- **total response tokens** — a fixed regex token estimate (no tokenizer dep).
- **median query latency** — median of `--repeats` runs (default 3).

**LLM layer** (opt-in): feeds each variant's tool output to an OpenAI-compatible
model (`OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OREBENCH_MODEL`) at temperature 0,
grading the answer and reporting accuracy, token usage and latency over
`--trials`. Skipped cleanly when no key is set.

### Baseline — 2026-08-18 (graphify 0.9.44, PYTHONHASHSEED=0, 56-question suite)

Graph: 93,872 nodes / 185,993 edges. Control: all 93,872 names stripped.

| metric | mapped | control |
|---|---|---|
| graph load (s) | ~1.5 | ~1.6 |
| median query latency (ms) | ~17 | ~18 |
| total response tokens | 11,105 | 11,176 |
| name-recognition rate | 100% | 0% |
| answer-in-output rate | 100% | 24% |

**Headline: with identical topology, the mapping lifts the share of questions
answerable straight from tool output from 24% to 100%, for a 0.6% token cost and
no latency change.** The 24% control floor is where a node label happens to
contain the answer words on its own; the other 76% are only answerable because a
curated name is attached. Latency and token counts confirm the names are free at
query time — their entire value is interpretability.

Reproduce: `python -m oregraph bench`. Results land in
`<ORE_GRAPH_OUT>/bench/report.md` and `results.json`.

### Build-task track — implement an instrument ORE does not have

`--build` runs a realistic engineering task instead of a lookup: **add a
`CompoundOption` trade to ORE**. CompoundOption (an option on an option) is
genuinely absent from ORE's trade types (confirmed: 0 `CompoundOption`
registrations in `OREData/ored/utilities/databuilders.cpp`, none in the
portfolio), while QuantLib already ships the underlying
(`ql/instruments/compoundoption.hpp` +
`ql/pricingengines/exotic/analyticcompoundoptionengine.hpp`) - so it is a real
"wire existing pricing into a new ORE trade" job. The task and its touchpoint
rubric live in `bench/build_tasks.json`, grounded against the vanilla-option
pattern in the checkout.

Each task carries a **rubric** of the ORE subsystems a correct implementation
must touch (new `Trade` subclass, XML serialization, `TradeFactory`
registration, `EngineBuilder`, `EngineFactory` registration, the QuantLib
instrument, its engine, the trade XSD). Two measurements:

- **Deterministic** — the share of those touchpoints the graph already *names*
  in the retrieved context (mapped vs control). Reproducible, no LLM.
- **LLM** (with `--llm`) — the model writes an implementation plan from the
  context and is graded against the same rubric; reports plan coverage, tokens
  and latency per variant.

Baseline (same graph, deterministic layer):

| metric | mapped | control |
|---|---|---|
| touchpoints surfaced in graph context | 75% (6/8) | 62% (5/8) |
| context tokens | 2,973 | 3,103 |

Mapped surfaces one extra touchpoint (`xsd_schema`, via the curated name
"Config/trade XML serialization") that the control graph loses when its names
are stripped. Both graphs correctly *fail* to surface `ql_instrument` and
`ql_engine`: those do not exist in ORE yet and must come from QuantLib
knowledge - which is the point of choosing a genuinely missing instrument. Run
`python -m oregraph bench --build --llm` to grade a model's actual plan.

### Graphify vs no-Graphify track (`--vs-source`)

The tracks above compare *mapped vs control* - the value of the names. This one
compares *graph vs no graph* - the value of Graphify at all, on the axis it is
marketed on (token reduction). For each question the graph answers in one
compact `query_graph` call; the no-graph baseline is the token size of the
source files that answer draws from - the code an agent would otherwise read to
answer the same thing. That baseline is **generous to the no-graph side**: it
assumes the agent already knows exactly which files to open, which is itself
what the graph provides. Needs the ORE checkout (`ORE_ENGINE`) to size files.

Baseline (8 questions, same graph):

| question | graph tok | source tok | ratio |
|---|--:|--:|--:|
| how is a swap priced | 1,499 | 125,287 | 83.6x |
| how is sensitivity risk computed | 1,392 | 109,366 | 78.6x |
| how are scenarios generated for simulation | 2,153 | 48,003 | 22.3x |
| how is a yield curve constructed | 1,479 | 23,965 | 16.2x |
| how is an equity option trade built and priced | 2,578 | 32,828 | 12.7x |
| how is a bond priced | 986 | 11,230 | 11.4x |
| how is a portfolio loaded from XML | 1,486 | 11,803 | 7.9x |
| how does the SABR volatility model work | 1,448 | 6,910 | 4.8x |
| **total** | **13,021** | **369,392** | **28.4x** |

**Headline: ~28x fewer tokens overall (median ~14x per question, up to ~84x) to
reach the same answer through the graph than by reading the source it points
to.** This is the graph's value and is independent of the curated names; it sits
in the same order of magnitude as graphify's marketed figure, and the true
saving is larger still, since the baseline assumes perfect file selection - the
real no-graph alternative is grepping and reading whole modules. Reproduce:
`python -m oregraph bench --vs-source`.



