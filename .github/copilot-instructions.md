# ore-graphify

Build pipeline for a knowledge graph of the ORE codebase. VS Code and Copilot
read this file automatically as workspace context.

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

- Curated names in `labels/` are attached to the wrong communities — see
  `docs/RELABELLING.md`. Until fixed, `verify` reports them `id-unverified`.
- `semantic-chunks/examples/` is not populated yet; everything else is.
- Run `oregraph verify` after any change to the build or merge path.

## Working here

Prefer editing the pipeline over patching output. If a graph looks wrong, the
cause is nearly always in `chunks.py` (coverage), `link.py` (cross-module
edges), `merge.py` (namespacing and labels) or `labels.py` (name attachment).
Add a check to `verify.py` for any defect you fix, so it cannot return unnoticed.
