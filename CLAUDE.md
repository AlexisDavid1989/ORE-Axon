# ORE Axon

Build pipeline for a knowledge graph of the ORE codebase. Claude Code reads this file
automatically at session start.

## Commands

Always drive this repo through its CLI, never by calling graphify directly:

```
python -m oregraph info | coverage | build | merge | semantic | relabel | verify | mcp
```

Paths come from `ORE_ENGINE` and `ORE_GRAPH_OUT`. Never hardcode a path in any
file here — `oregraph/config.py` resolves them, and hardcoded paths were what
made the previous version unusable by anyone but its author.

## Two rules that are easy to break silently

1. **Do not change the targets of a chunk in `oregraph/chunks.py` that has a
   file in `labels/`.** Community ids come from Louvain and shift when the
   corpus changes; the label files are keyed by id, so editing a labelled
   chunk's targets silently repoints every name onto the wrong group. Add new
   content as a new chunk instead.

2. **Never write `labels/*.anchors.json` from a mapping nobody has verified.**
   Anchors pin names permanently. Pinning a wrong mapping bakes the bug in.
   `oregraph relabel` without `--write-anchors` only proposes.

## Current state

- Community names are done: 530 curated names in `labels/`, audited and pinned to
  content anchors, covering 92% of communities of 50+ nodes. They re-attach
  themselves on rebuild. To add or fix one, follow `docs/RELABELLING.md`.
- `semantic-chunks/examples/` is not populated yet; everything else is.
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
edges), `merge.py` (namespacing and labels) or `labels.py` (name attachment).
Add a check to `verify.py` for any defect you fix, so it cannot return unnoticed.
