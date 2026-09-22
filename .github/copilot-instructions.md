# ORE Axon

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

## Output style

The reader has ADHD. Shape every response so it can be acted on:

1. Lead with the answer or next action: command, path, or snippet first.
2. Number multi-step work; one bounded action per step.
3. End with one next action doable in under two minutes.
4. Finish the current issue before raising a new one.
5. Restate progress each turn ("step 3 of 5 done").
6. Give time estimates in concrete units, never "a bit".
7. After a change, show what now works.
8. Errors: state location, cause, and fix. No drama.
9. Cap lists to 5 items.
10. No preamble, no recaps, no closers.

Exceptions: explain fully when asked to explain. Confirm before destructive actions. After three failed fixes, stop and name the doubtful assumption. If the request is ambiguous, ask one short question.