# ORE Axon

Build pipeline for a knowledge graph of the ORE codebase. Claude Code reads this file
automatically at session start.

## Commands

Always drive this repo through its CLI, never by calling graphify directly:

```
python -m oregraph info | coverage | build | merge | fieldmap | semantic | relabel | verify | bench | mcp
```

Paths come from `ORE_ENGINE` and `ORE_GRAPH_OUT`. Never hardcode a path in any
file here — `oregraph/config.py` resolves them, and hardcoded paths were what
made the previous version unusable by anyone but its author.

## Three rules that are easy to break silently

1. **Do not change the targets of a chunk in `oregraph/chunks.py` that has a
   file in `labels/`.** Community ids come from Louvain and shift when the
   corpus changes; the label files are keyed by id, so editing a labelled
   chunk's targets silently repoints every name onto the wrong group. Add new
   content as a new chunk instead.

2. **Never write `labels/*.anchors.json` from a mapping nobody has verified.**
   Anchors pin names permanently. Pinning a wrong mapping bakes the bug in.
   `oregraph relabel` without `--write-anchors` only proposes.

3. **Do not add bulk nodes to the merged graph without running `oregraph bench`
   before and after.** `verify` cannot see this failure. The ORE_Forge field
   mapping was first merged as 12,135 field nodes (plus a node per pricing
   combination); verify passed, and bench showed 4 of 8 answers changed and one at
   2x the tokens - graphify's term weights are global, so the damage reaches
   questions that never touch a new node. It is now one node per entry with the
   fields as attributes (bench-identical). `verify` fails if a fieldmap node is not
   an entry; the general rule is yours to keep.

## Current state

- Community names: 530 curated names in `labels/`, audited and pinned to content
  anchors, covering 82% of communities of 50+ nodes. They re-attach themselves
  on rebuild, but the id file (`labels/<chunk>.json`) is a *derived* view once a
  chunk is anchored — run `oregraph relabel --sync` before `--audit` or hand-editing
  it after a rebuild, never trust its ids directly. To add or fix a name, follow
  `docs/RELABELLING.md`.
- `semantic-chunks/examples/` is not populated yet; everything else is.
- ORE_Forge's field mapping (trade, curve config, convention, pricing engine) is
  in the graph when `ORE_FIELDMAP` is set: `oregraph fieldmap` snapshots it,
  `oregraph merge` consumes the cached snapshot (merge never calls ORE_Forge), and
  `oregraph query-fields X` reads it. ORE_Forge is a moving target edited by other
  sessions - re-run `fieldmap` then `merge` after it changes; `verify` warns when
  the graph is behind. It is opt-in: without a snapshot, merge is unchanged.
  Entries also link across domains (`maps_to_pricing_engine`, `maps_to_curve_config`,
  `maps_to_convention`), derived at snapshot time by ORE_Forge's own
  `src/core/*_links.py` (snapshot format 3: an older snapshot is refused until
  `oregraph fieldmap` is re-run). All INFERRED. They make hubs - `YieldCurve` is the
  target of ~170 trades - and graphify seeds the word "fieldmap" on the
  best-connected entry, so any change to entry degrees moves that seed (it was `Swap`'s
  pricing engine, now `YieldCurve`'s config): bench before and after, as for any graph
  change. s34 once required that accidental seed; it now requires only content.
- **`oregraph.serve` is the MCP server, not `graphify.serve`.** It builds
  graphify's server and intercepts one tool, `query_graph`, answering it with
  `query.query_graph_text`; the other nine tools, and any call with a
  `project_path` or `context_filters`, are delegated untouched. graphify is not
  modified. Both `.mcp.json` files need `PYTHONPATH` set to this repo, since
  `oregraph` is not an installed package and the config lands in the Engine
  repo. The server memoizes graphify's `_load_graph` so its copy of the graph
  and ours are the same object - without that it is two ~120MB loads.
- `query_graph` answers are graphify's retrieval fused with `query_question`'s.
  graphify seeds badly on prose: query words are matched against labels one at
  a time and never joined, so "yield curve" cannot reach `YieldCurve`, and an
  exact hit on a common member name (`engine`, `validate`, `yield` are all real
  symbols here) outranks the class that answers the question. `query_question`
  joins adjacent words, ranks a class above a member, and carries
  `_CONCEPT_SEEDS`, 32 concepts whose name shares no substring with their
  implementation (ORE computes XVA in `PostProcess`). Neither engine dominates
  - over the rubric graphify reaches 51 of 119 nodes and ours 70, together 85 -
  so `merge_answers` fuses both by reciprocal rank. Keep the fusion key on
  label *and* file: `LegData` names two nodes and collapsing them returns the
  wrong one.
- `oregraph bench` grades answers as well as pricing them, through the same
  call the server uses - if you change one, change both, or the benchmark stops
  describing what is served. `GraphAdapter.graphify_only` keeps the old path as
  the baseline to measure against. All 50 questions carry a rubric:
  `required_nodes` fails the command when missing, `xfail_nodes` only reports.
  Entries are `label`, `label@source-file`, or `src:<path fragment>`. Today 31
  of 50 pass, 96 entries gate and 23 gaps remain; when a gap closes, bench says
  XPASS and the entry moves to `required_nodes`. `verify` fails if a
  `required_nodes` entry names nothing in the graph, and warns for an
  `xfail_nodes` one, which is either a typo or a corpus gap.
- A concept added to `_CONCEPT_SEEDS` must be domain knowledge, not an answer
  key for a bench question. The test is paraphrase: re-ask the question the way
  someone else would and the rubric should still be met. That check is what
  caught the alias matcher missing "sensitivities" for `sensitivity` (the
  plural is not a prefix) and "bootstrapping" for `bootstrap`.
- A `src:` fragment is matched against `source_file`, which is chunk-relative
  (`Bonds/Bonds.cpp`), not `repo_path` (`QuantLib/Examples/Bonds/Bonds.cpp`) - so
  `src:QuantLib/Examples` can never match; use a fragment inside the chunk. Case
  matters in labels too: xsd nodes are `accumulator01Data (complexType)`, not
  `Accumulator01Data`. `verify` flags both. s48's `src:Makefile.am` is a real
  corpus gap, not a typo: `CODE_EXTS` in `build_ast.py` has no build-file
  extractor, so no Makefile node exists to reach.
- **graphifyy stays pinned at 0.9.44.** 0.9.65 (the newest the team can get) fixes
  the `PYTHONHASHSEED` clustering bug but answered less accurately: 27 -> 22 of 50
  bench answers, 97 -> 89 of 119 rubric nodes delivered, because graphify's own
  retrieval changed and its extractor builds a different graph. Do not bump the pin
  on version number alone, and keep the `PYTHONHASHSEED=0` relaunch. Evidence and
  how to re-test: docs/KNOWN-ISSUES.md, "Upgrading graphifyy".
- Run `oregraph verify` after any change to the build or merge path. Two of its
  checks are about names: `curated labels attached` and `all curated names
  attached`. The second is the one that catches a name passing `--audit` on the
  per-chunk graph and still vanishing at merge.

## Conserving plan usage

On a Pro plan, prefer Sonnet (`/model sonnet`) for build, merge and verify work
— it is mechanical. Use `/clear` between phases; a long session re-sends its
whole history on every request, which is the usual cause of unexpected usage.

Never run semantic extraction through the agent when `GEMINI_API_KEY` is set —
call graphify's Gemini backend so the token cost lands there, not on the plan.

## Working here

Prefer editing the pipeline over patching output. If a graph looks wrong, the
cause is nearly always in `chunks.py` (coverage), `link.py` (cross-module
edges), `merge.py` (namespacing and labels), `labels.py` (name attachment),
`link_schema.py`/`xsd_link.py` (XSD-to-class links - four tiers plus three
dispatch-table passes now; see link_schema.py's module docstring) or, for
the field mapping, `fieldmap_link.py`.
Add a check to `verify.py` for any defect you fix, so it cannot return unnoticed.
