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
