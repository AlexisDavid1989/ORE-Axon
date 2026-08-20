# ORE Axon

A queryable knowledge graph of the [ORE](https://github.com/OpenSourceRisk/Engine)
codebase, wired into Claude Code and VS Code / Copilot over MCP so an agent can
ask the architecture questions instead of grepping 5,000 files.

Built on [graphify](https://pypi.org/project/graphifyy/). This repo is the ORE
corpus map, the build pipeline, and the curated community names — roughly 1 MB.
The graph itself is **not** committed: it is ~100 MB, it rebuilds from your own
checkout in minutes, and a prebuilt copy would describe someone else's commit.

---

## Why use it — ~28× fewer tokens per answer

Answering a question from the graph costs a fraction of the tokens of reading the
ORE source it points to. Measured across 8 questions (`oregraph bench`, graphify
0.9.44), the graph reaches the same answer for **~28× fewer tokens overall
(median ~14×, up to ~84×)** — and that baseline is *generous* to the no-graph
side, since it assumes you already know exactly which files to open.

| question | graph tokens | reading the source | ratio |
|---|--:|--:|--:|
| how is a swap priced | 1,499 | 125,287 | **83.6×** |
| how is sensitivity risk computed | 1,392 | 109,366 | **78.6×** |
| how is a yield curve constructed | 1,479 | 23,965 | 16.2× |
| how is an equity option built & priced | 2,578 | 32,828 | 12.7× |
| **total (8 questions)** | **13,021** | **369,392** | **28.4×** |

Reproduce it yourself: `python -m oregraph bench`. Full table and method in
[docs/METRICS.md](docs/METRICS.md).

---

**Implementing the outstanding work?** Start at
**[docs/CLAUDE-CODE.md](docs/CLAUDE-CODE.md)** (recommended — and the only
option on Copilot's free plan, which has no agent mode) or
[docs/COPILOT.md](docs/COPILOT.md) if you have Copilot Pro. Each has every
phase with the exact prompts to paste.

## Quick start

See [docs/INSTALL.md](docs/INSTALL.md) for setup.

**No API key is required.** Code is extracted structurally (AST); the documents
and schemas were extracted once by an LLM and the results are committed under
`semantic-chunks/`, so your build just reads them.

### What it answers well, and what it doesn't

**Works well — structural questions.** "What inherits from `X`" (`get_neighbors`),
"how does A reach B" (`shortest_path`), "what is in this cluster"
(`get_community`). Cross-module traversal works: OREData → QuantExt → QuantLib
resolves in 3 hops.

```
Shortest path (3 hops):
  SwapEngineBuilder <--contains-- swap.hpp --includes--> discountingswapengine.hpp --contains--> DiscountingSwapEngine
```

**Does not work — documentation-to-code questions.** Docs, XSD and code are
separate layers with **zero edges between them**. "Which code implements what the
ScriptedTrade docs describe" cannot be answered. Worse, the tools do not say so:
asked that question, `shortest_path` matches the `ScriptedTrade` *class* and
returns a confident-looking code-to-code path, never touching the 31 documentation
nodes on the subject. Treat any docs↔code answer as unfounded. Planned for v1.1.

**Use the right tool.** `shortest_path` answers "is there a route", not "what does
X depend on" — asked the latter it returns co-inclusion artefacts (two files that
both include `actual365fixed.hpp` are not a dependency). For dependency and
blast-radius questions use `get_neighbors`. Avoid `query_graph` in DFS mode on
broad questions; it returns thousands of loosely related nodes.

**Queries need a real symbol as the entry point.** `"portfolio/swap.hpp"` finds
nothing; `"TradeFactory"` works. Start from a class or function name, not a path.

### Keeping it current

```bash
cp hooks/post-merge <Engine>/.git/hooks/post-merge && chmod +x $_
```

graphify caches extraction per file, so a rebuild after `git pull` only touches
what changed — usually seconds.

---

## Configuration

Resolution order: CLI flag → environment variable → `oregraph.toml` → autodetect.

| Setting | Env var | Default |
|---|---|---|
| ORE Engine checkout | `ORE_ENGINE` | autodetected by walking up from cwd |
| Graph output dir | `ORE_GRAPH_OUT` | OS cache dir (`%LOCALAPPDATA%`, `~/.cache`, …) |

Keep the output directory **out of OneDrive/Dropbox** — a build writes hundreds
of megabytes of intermediates. `oregraph info` warns if it detects a synced path.

---

## Commands

| Command | Purpose |
|---|---|
| `info` | Resolved paths, chunk status, whether graphify is installed |
| `coverage` | Which repo files no chunk claims — run after any ORE upgrade |
| `build` | Extract every chunk, then merge. `--only <chunk>` to narrow |
| `merge` | Re-merge already-built chunks |
| `relabel` | Check curated names against the current clustering |
| `verify` | Post-build integrity checks |
| `mcp` | Write MCP config for Claude Code and/or VS Code |
| `bench` | Graph vs no-graph token cost (the numbers above) |

---

## How it is structured

ORE is too large for one graphify pass (graphify warns above 500 files), so the
corpus is split into chunks that are extracted independently and stitched
together afterwards. `oregraph/chunks.py` is the map.

```
QuantLib-00-core … 07-processes   QuantLib, split by subsystem
QuantExt, OREData, OREAnalytics   the ORE libraries
App, ORESwig, ORETools…, ORETests, OREExamples
OREDocs, OREXsd                   semantic — built from committed extraction
```

Two rules govern that file, both of which the original setup violated:

1. **Never change the targets of a chunk that has curated labels.** Community
   ids come from Louvain and shift when the corpus changes; the label files are
   keyed by id. Add new content as a *new* chunk.
2. **Every path should belong to exactly one chunk.** `oregraph coverage` is the
   check — a chunk map has no natural notion of "everything else", which is how
   `ql/processes` and 1,500 example files went missing without a single warning.

---

## What was wrong with the previous setup

This repo exists because an audit of the original build found four problems, all
of which failed silently — the graph rendered fine and answered questions badly.

**1. No cross-module edges.** Each chunk was extracted in isolation, so
`#include <qle/...>` from OREData had no target node in scope and the
relationship was simply never created — not even recorded as dangling. The
merged graph was 78,619 nodes in **twelve disconnected islands, with zero edges
between them**. Nothing could be traced from ORE down into QuantLib.
*Fixed:* `link.py` recovers those edges by reading `#include` directives from
source and resolving them against the chunk map.

**2. Communities were concatenated, not namespaced.** Every chunk numbers its
communities from 0, and the merge kept those raw ids — so "community 0" in the
merged graph was 1,259 nodes drawn from all twelve modules with no edges between
them. Any community-level query returned a meaningless mixture.
*Fixed:* `merge.py` namespaces communities as `<chunk>:<id>`.

**3. Curated names were dropped on merge, and had drifted anyway.** All 272
hand-written community names were lost in the merged graph — every community
came out as "Community N" in the one artifact the MCP server actually reads.
Worse, the names had come unstuck from their communities: each rebuild re-runs
Louvain, but the static label files were never regenerated, so they describe an
older clustering. In the last build `QuantLib-01-foundations` community 2 was
named "Linear Interpolation" while holding the error-function code, and
community 3 was "Error Function (erf)" while holding currency definitions.
*Fixed:* the merge carries names through, and all 530 names have since been
rewritten against the current clustering, audited and pinned to content anchors
so they survive future re-clustering. See
[docs/RELABELLING.md](docs/RELABELLING.md) for how to maintain them.

**4. Silent coverage gaps.** `ql/processes`, every top-level `ql/*.hpp` (the base
classes the rest of ORE inherits from), `Examples/`, `ORE-SWIG/`, `Tools/`,
`FrontEnd/` and all test suites were outside the chunk map. Separately,
`rebuild_all.py` merged only the ten code chunks, so the next `git pull` would
have dropped the docs and schemas from the merged graph entirely.
*Fixed:* chunks added for all of it, `coverage` reports the rest, and the merge
includes every chunk.

---

## Status

The current build:

| | |
|---|---|
| Nodes | 90,374 |
| Edges | 190,550 |
| Cross-module edges | 14,168 |
| Curated community names | 530 |

Built against:

| | |
|---|---|
| ORE release | v16 (16th release, Jan 2025 – Apr 2026) |
| Commit | `3b62ba248e36ea92f408f0d863ede09639074836` on `master`, untagged |
| Nearest tag | `v1.8.16.0` |
| QuantLib | 1.42.1 |
| graphifyy | 0.9.44 |

Building against a different ORE commit produces a different graph — a
handful of curated names may not attach, which is expected. `oregraph info`
prints the version of your current checkout; `oregraph verify` prints the
version the merged graph was actually built from, so the two are always
comparable instead of guessed at.

| Area | State |
|---|---|
| Code chunks (AST) | Complete, including the previously missing paths |
| Docs — 329 `.tex` | Complete, committed under `semantic-chunks/docs/` |
| XSD — 23 schemas | Complete, committed under `semantic-chunks/xsd/` |
| Cross-module links | Complete — 14,168 edges, verified on every build |
| Community names | Complete — 530 names, curated, audited and pinned |
| `Examples/` XML & CSV | Not yet extracted — see below |

Community names cover 82% of communities of 50 nodes or more. They are pinned to
content anchors, so they survive re-clustering when you rebuild against a newer
ORE; `verify` checks on every build that each one still reaches the merged graph.
To add or correct a name, see [docs/RELABELLING.md](docs/RELABELLING.md).

### Remaining work

**Examples config files.** ~1,100 XML portfolios and CSV market-data files are
scanned for code but not semantically extracted. That pass needs an LLM: set
`GEMINI_API_KEY` (`pip install 'graphifyy[gemini]'`) and it is fully automated on
any host, or run it in Claude Code, which dispatches extraction subagents in
parallel. VS Code / Copilot works too but graphify falls back to pasting chunk
JSON back by hand, ~50 rounds at this size. Commit the resulting chunks to
`semantic-chunks/examples/` and nobody has to do it again.
