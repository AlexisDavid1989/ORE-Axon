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

## 3. Graphify vs no-Graphify — token cost of answering (`oregraph bench`)

This measures the value of Graphify at all, on the axis it is marketed on
(token reduction). For each question the graph answers in one compact
`query_graph` call; the no-graph baseline is the token size of the source files
that answer draws from - the code an agent would otherwise read to answer the
same thing. That baseline is **generous to the no-graph side**: it assumes the
agent already knows exactly which files to open, which is itself what the graph
provides. Needs the ORE checkout (`ORE_ENGINE`) to size files.

`query_graph`'s output is reproduced by calling `graphify.serve`'s module-level
render helper directly - no `mcp` package, no stdio handshake, no process-launch
jitter - so the token numbers are identical on any machine given the same build.

```
python -m oregraph bench                          # default question set
python -m oregraph bench --questions my.json      # your own questions
```

The question set lives in `bench/source_questions.json`; every run prints its
sha256 and the graph node/edge counts so results are comparable across time.

### Baseline — graphify 0.9.44, 8-question suite

Graph: 93,872 nodes / 185,993 edges.

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
to.** It sits in the same order of magnitude as graphify's marketed figure, and
the true saving is larger still, since the baseline assumes perfect file
selection - the real no-graph alternative is grepping and reading whole modules.

Reproduce: `python -m oregraph bench`. Results land in
`<ORE_GRAPH_OUT>/bench/report.md` and `results.json`.




