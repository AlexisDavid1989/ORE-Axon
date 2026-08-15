# Fixing the community names

**Status: needs one human pass. Until it is done, treat community names in the
graph as unreliable.**

## What is wrong

`labels/<chunk>.json` maps a community id to a name someone wrote by hand:

```json
{ "0": "Log-Cubic Interpolation Variants", "2": "Linear Interpolation" }
```

Those ids come out of Louvain community detection. **Every build re-runs
Louvain**, and the partition it produces depends on the exact graph — so the ids
are only meaningful for the one build the names were written against. The
original pipeline re-clustered on every rebuild and never regenerated the label
files, so the names came unstuck from the groups they describe.

It fails silently. Reports still render, the MCP server still answers, and the
names are simply wrong. From the last build of `QuantLib-01-foundations`:

| id | name it carries | what is actually in it |
|---|---|---|
| 0 | Log-Cubic Interpolation Variants | `loginterpolation.hpp` — correct |
| 1 | ABCD Volatility Interpolation | `abcdinterpolation.hpp` — correct |
| 2 | Linear Interpolation | `errorfunction.hpp` — **wrong** |
| 3 | Error Function (erf) | `currencies/america.hpp` — **wrong** |
| 4 | Beta & Binomial Distributions | `patterns/observable.cpp` — **wrong** |

`oregraph relabel --only QuantLib-01-foundations` reports 15 of 15 names would
move. The names themselves are good; only the mapping is broken.

## Fixing it

### 1. See the damage

```bash
python -m oregraph build --only <chunk>
python -m oregraph relabel --only <chunk>
```

Output marks each name `same`, `MOVE` (a better community exists) or `AMBIG`
(several names best-match one community, so the proposal cannot separate them).

### 2. Correct the mapping

The proposal is a heuristic — token overlap between the name and its members'
node ids. It is reliable on distinctive names ("Adaptive Runge-Kutta ODE Solver"
lands exactly) and weak where names share vocabulary (three interpolation names
all score highest on the same community). Do not accept it blindly.

For anything marked `AMBIG`, or if you would rather redo it properly, relabel
from scratch — this is graphify's own Step 5, and an agent does it well:

> Read `<ORE_GRAPH_OUT>/<chunk>/graphify-out/.graphify_analysis.json`. For each
> community, look at its member node ids and write a 2–5 word plain-language
> name. Write the result as `{"<community id>": "<name>"}` to
> `labels/<chunk>.json`.

Reuse the existing names where they still fit — they are good descriptions of
ORE, just misfiled.

### 3. Pin it so it cannot rot again

```bash
python -m oregraph relabel --only <chunk> --write-anchors
```

This writes `labels/<chunk>.anchors.json`, recording the 15 highest-degree
members of each named community. On later builds `labels.py` re-attaches names
by anchor overlap instead of by id, so a name follows its content through
re-clustering and ordinary code churn.

Measured on `QuantLib-01-foundations` with a correct mapping, anchor matching
recovered 15/15 names on an unchanged corpus, 15/15 with 10% of files removed,
and 14/15 with 25% removed.

A name whose anchors no longer win any community is **dropped**, not relocated.
An earlier version reassigned it to its second-best community, which put names
on groups they did not describe — a wrong name is worse than a missing one.

### 4. Commit

```bash
git add labels/ && git commit -m "relabel <chunk>: fix community mapping, pin anchors"
```

Then it is done for everyone — teammates get correct names without repeating any
of this.

## Order of work

Highest value first, by how much each chunk is queried:

1. `OREAnalytics` (40 names) — XVA, SIMM, SA-CCR, exposure
2. `OREData` (40) — portfolio, trade builders, curve config
3. `QuantExt` (40) — ORE's QuantLib extensions
4. `OREDocs` (43) and `OREXsd` (19) — cheap, and the doc/schema graphs are small
5. QuantLib chunks (15 each) — least often the subject of a question
