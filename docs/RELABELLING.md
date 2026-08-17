# Community names

**Status: complete and pinned.** 530 curated names cover 82% of communities of
50 nodes or more. `oregraph verify` checks on every build that each of them
still reaches the merged graph. That 82% figure moves with the clustering —
it dropped from an earlier 92% purely because a reproducibility fix (pinning
`PYTHONHASHSEED`) changed which communities exist, not because names were lost.

This document is for maintaining them — adding a name, correcting one, or
recovering after an ORE upgrade re-clusters the corpus.

## What a community name is

graphify runs Louvain community detection over each chunk, producing groups of
tightly-connected nodes. A group is only useful to a reader if it has a name, so
`labels/<chunk>.json` maps a community id to a short plain-language description:

```json
{ "0": "Log-linear and log-cubic interpolation", "3": "Error function (erf) approximation" }
```

Those names are what the MCP server surfaces when an agent asks about the
architecture, which is why a wrong name is worse than no name: it misleads a
reader who has no way to tell it is wrong.

## Why anchors exist

Community ids come out of Louvain, and **every build re-runs Louvain**. The
partition depends on the exact graph, so the ids are only meaningful for the one
build the names were written against. The original pipeline re-clustered on every
rebuild and never regenerated the label files, so the names came unstuck from the
groups they described — silently. Reports still rendered and the MCP server still
answered; the names were simply wrong. In one build of `QuantLib-01-foundations`,
community 2 was named "Linear Interpolation" while holding the error-function
code, and community 3 was "Error Function (erf)" while holding currency
definitions.

`labels/<chunk>.anchors.json` fixes this. For each named community it records the
~15 highest-degree member node ids. On a later build, `labels.py` scores every
new community against every anchor set and gives each name to the community
holding most of its anchors. Node ids derive from source paths, so they survive
re-clustering and ordinary code churn far better than community numbering does.

Measured on `QuantLib-01-foundations`: 15/15 names recovered on an unchanged
corpus, 15/15 with 10% of files removed, 14/15 with 25% removed.

A name that cannot win its own best-match community is **dropped, not
relocated**. An earlier version reassigned it to its second choice, which put
names on groups they did not describe.

## The id file becomes derived once a chunk is anchored

Before a chunk has ever been pinned, `labels/<chunk>.json` (id → name) *is*
the mapping — there is nothing else to attach from. Once `labels/<chunk>.anchors.json`
exists, that stops being true: attachment happens by anchor overlap, and the
id file is only kept around because `relabel --audit` and a future
`--write-anchors` both read it. Nothing re-derives it automatically, so after
a rebuild reclusters the corpus, its ids silently point at the wrong
communities — the same failure this whole document exists to fix, just
one level up: the *name* is still attached to the right code, but the id file
that maps community-id → name is stale, and running `--audit` against it
reports names as misfiled that are not. Run this first, every time, before
`--audit` on an already-anchored chunk:

```bash
python -m oregraph relabel --sync
```

This overwrites `labels/<chunk>.json` from whatever the merged graph's
anchors currently attach — names are copied verbatim, never reworded, only
the id each one sits under changes. `--audit` also runs this check itself:
if more than a quarter of a chunk's names come back mismatched, it assumes
the id file is stale rather than reporting a quarter of your curated names as
suddenly wrong, and tells you to sync first.

Never hand-edit an anchored chunk's id file directly — `--sync` overwrites it
from the anchors on the next run, so an edit that isn't also reflected in the
anchors (via `--write-anchors`) simply disappears.

## Adding or fixing a name

The loop is: digest → name → audit → pin.

### 1. Build the naming brief

```bash
python -m oregraph relabel --digest --top 80 --only <chunk>
```

Writes `RELABEL_BRIEF.md` into the chunk's output directory: each community
reduced to the source files it spans and its most connected symbols. About 25 KB
instead of the ~1 MB raw analysis, and far easier to name from — what identifies
a community is which files it covers, which the raw node ids bury. `--top`
controls how many of the largest communities are included.

### 2. Write names

Read the brief and write a 2–5 word plain-language name per community. What
makes this hard is that names must be distinguishable **from each other**: a bare
"Interpolation" is useless in a chunk where a dozen communities are
interpolation. Name the specific family — "Log-cubic interpolation", "ABCD
volatility interpolation".

Guidelines that survived the first full pass:

- Name what the code does, in words — not the filename. "Error function (erf)
  approximation", not `errorfunction.hpp`.
- Use ORE and QuantLib vocabulary: term structure, coupon pricer, lattice, path
  generator, calibration helper, stochastic process, curve config, engine builder.
- Skip anything not worth naming. Communities under ~10 nodes, or that are just a
  bag of primitives, belong out of the file entirely. A missing name is honest.
- Where a community genuinely holds more than one subject, say so rather than
  naming only the dominant part — `"FFT pricing engines (+ analytic Heston)"`,
  `"Null and weekends-only calendars (mixed)"`.
- Where one subject is split across headers and implementations, mark them
  `(declarations)` / `(implementations)`.

A useful cross-check for names that fail to distinguish:

```bash
python -c "
import json,sys,collections,re
d=json.load(open(sys.argv[1]))
k=collections.defaultdict(list)
for i,n in d.items(): k[frozenset(re.findall(r'[a-z]{4,}',n.lower()))].append((i,n))
for v in k.values():
    if len(v)>1: print('NEAR-DUPLICATE:',v)
" labels/<chunk>.json
```

It only sees one chunk, so it cannot catch a name that collides with one in a
*different* chunk. That happened once — QuantExt carries its own fork of
QuantLib's experimental `LognormalCmsSpreadPricer`, and both communities were
named identically. Qualify such names (`(QuantExt fork)`) rather than leaving a
reader to inspect the code to tell them apart.

### 3. Audit

```bash
python -m oregraph relabel --only <chunk> --audit
```

The acceptance gate. It checks each name against the actual contents of the
community it sits on — a name should share vocabulary with its own files and
symbols. Matching is deliberately generous: one shared token passes. It is a trap
detector, not a quality score, so a clean audit means "nothing is obviously
misfiled", not "these are good names". Short acronyms can false-positive; if the
audit flags a name you have verified by eye, prefer explaining why over
contorting the name to satisfy the check.

Must report `CLEAN` before you pin.

### 4. Pin

```bash
python -m oregraph relabel --only <chunk> --write-anchors
git add labels/ && git commit -m "relabel: <chunk>"
```

## The standing rule

**Never modify or remove an existing curated name or its anchor list. Adding a
name for a previously unnamed community is always allowed.**

Anchors are permanent — pinning a wrong mapping bakes the bug in. `relabel`
without `--write-anchors` only proposes.

The one exception is a community that has genuinely dissolved: re-clustering
fragmented it across several unrelated successors so thoroughly that no
single one of them is what the old name described anymore, and the old name
no longer attaches at all (`verify`'s "all curated names attached" check is
what surfaces this). That is a rename, not an addition, and it needs the same
explicit sign-off every time — never take it on your own initiative because a
name failed to attach. When it happens: run `--digest` on the affected
chunk(s), trace the old name's anchors to find where their nodes now live
(they still resolve — node ids survive re-clustering even when community ids
don't), and check whether any current name already occupies the successor
community before writing a new one there. It might: two names can each
legitimately best-match one community, and `labels.py` handles that by
combining them (`"A / B"`) rather than by letting one displace the other.
Same acceptance gate as any other name — audit CLEAN before pinning — and if
the natural successor is already occupied by an unrelated name, leave it
unnamed and flag the conflict rather than guessing which one is wrong.

When adding names to a chunk that already has some, the change should be purely
additive. Check it before committing:

```bash
git diff --numstat labels/<chunk>.anchors.json    # deletions must be 0
```

For a stronger check, compare the parsed structures and assert that every
pre-existing entry is unchanged and still in the same order — a clean-looking
diff is not proof on its own.

## After an ORE upgrade

Anchors re-attach names automatically; there is nothing to do by hand. Rebuild,
then check the two label lines in `verify`:

```bash
python -m oregraph build
python -m oregraph verify
```

```
[PASS] curated labels attached            524 named communities covering 23,844 nodes
[PASS] all curated names attached         every curated name reached the merged graph
```

The second line is the one that matters. `--audit` tests name-against-content on
the per-chunk graph, but attachment happens later, through anchor overlap at
merge. Nothing spanned the two until this check existed, which is how four
OREDocs names once passed every gate and still vanished from the merged graph.
If it reports a shortfall it names the missing labels: their anchors no longer
win any community. Before doing anything else, run `relabel --sync` (see
above) so `labels/<chunk>.json` reflects this build's actual ids, then
`--audit` that chunk — in most cases the name still attaches fine and the
sync alone was the fix. Only if a name is genuinely gone (see "the one
exception" above) does it need the digest → name → audit → pin loop.

Also run `python -m oregraph coverage` after an upgrade — if ORE's layout has
shifted, new paths may belong to no chunk at all.
