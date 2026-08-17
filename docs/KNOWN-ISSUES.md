# Known issues

Things that are known to be wrong or incomplete, logged rather than fixed on
sight, because fixing them needs a decision or an investigation this repo's
maintainer should make deliberately - not something to walk into as a side
effect of unrelated work.

## Two curated names may be misattached

Both surfaced as side effects of the 2026-08 deterministic-rebuild pass, not
from a dedicated audit - there has been no full review of all 530 names
against their current content, only of the ones that changed. Neither is in
scope to fix without the standing "never rename an existing name" rule's
sign-off (see docs/RELABELLING.md, "the one exception").

- **QuantLib-04-instruments-pricing, id 92, "Callability schedule for
  callable bonds".** Its anchors still best-match this community (47%
  recall, above threshold), but the community's actual content is
  amortizing/CMS/zero-coupon/CPI bond declarations
  (`amortizingcmsratebond.hpp`, `amortizingfixedratebond.hpp`,
  `cmsratebond.hpp`, `cpibond.hpp`, `zerocouponbond.hpp`, ...) - nothing
  about callability schedules. This is also what blocks naming the actual
  successor of the old "Amortizing, CMS and zero-coupon bonds" name: its
  content lives here now, but the id is already occupied by this name.
- **QuantExt, id 145, "Exotic swaptions and annuity mapping".** Flagged by
  `relabel --audit` after `--sync`: "swaptions" (plural) doesn't match the
  community's "swaption" (singular - `genericswaption.hpp`), and "annuity"
  and "exotic" don't appear anywhere in it at all (`crossccyswap.hpp`,
  `flexiswap.hpp`, `genericswaption.hpp/.cpp`). The "annuity mapping" part of
  the name likely described content that has since moved elsewhere.

## graphify: clustering output depends on `PYTHONHASHSEED`

Given byte-identical extraction input, `graphify.build.build_from_json()` +
`graphify.cluster.cluster()` returns a different edge count and Louvain
partition on every process run unless `PYTHONHASHSEED` is pinned - confirmed
with a minimal repro calling only stock graphify functions, no code from this
project. See the comment above the `PYTHONHASHSEED` relaunch in
`oregraph/cli.py` for the exact numbers.

Re-ran the same repro against 0.9.42 (the pin here is still 0.9.6, see
"Upgrading graphifyy" below): edge count came back **stable** across
unpinned runs, only the Louvain partition still varied, by a narrower margin
than on 0.9.6. Reads as: the edge-loss half of this bug is fixed since 0.9.6,
the clustering half is not. `PYTHONHASHSEED=0` still fully fixes it on
0.9.42 - the relaunch is still required, not optional, on either version.

Worked around here by relaunching every `build`/`merge` under
`PYTHONHASHSEED=0`. Upstream issue (title and body updated with the 0.9.42
numbers above):
https://github.com/Graphify-Labs/graphify/issues/2817

## Upgrading graphifyy

Pinned to 0.9.6 in `requirements.txt` because the committed anchors in
`labels/` were generated against that version's clustering - a different
version partitions the corpus differently (confirmed: 0.9.42 gives a
different edge count and community structure on the same input, see above),
so bumping the pin silently detaches every curated name from its community
exactly the way an ORE upgrade does.

Treat a graphifyy version bump as the same deliberate operation as an ORE
upgrade, in this order:

1. Bump the pin in `requirements.txt`, reinstall.
2. Full rebuild: `python -m oregraph build`.
3. `python -m oregraph relabel --sync` - the id files are about to be
   meaningless against the new clustering otherwise.
4. `python -m oregraph relabel --audit` - must come back clean (or only the
   two pre-existing flags above) before pinning anything.
5. `python -m oregraph relabel --write-anchors` (all chunks).
6. `python -m oregraph verify` - target 530 attached, all checks green.

Do not remove the `PYTHONHASHSEED=0` relaunch in `oregraph/cli.py` as part of
an upgrade - it is still required on 0.9.42 (see above), and there is no
evidence yet that a later version won't need it either.

## Docs and XSD have zero edges to code (v1.1)

`OREDocs` and `OREXsd` are extracted as their own chunks with no cross-links
into the code chunks, so "which code implements what the ScriptedTrade docs
describe" cannot be answered - and the tools don't say so. Asked that
question, `shortest_path` matches the `ScriptedTrade` class and returns a
confident-looking code-to-code path, never touching the 31 documentation
nodes on the subject. Treat any docs<->code answer as unfounded until this
is built. See README.md, "Does not work" for the user-facing version of this
same gap.
