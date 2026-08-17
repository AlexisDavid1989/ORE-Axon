# Known issues

Things that are known to be wrong or incomplete, logged rather than fixed on
sight, because fixing them needs a decision or an investigation this repo's
maintainer should make deliberately - not something to walk into as a side
effect of unrelated work.

## Curated names needing a maintainer decision

None of these are fixed on sight - fixing them needs a decision this repo's
maintainer should make deliberately, and docs/RELABELLING.md's standing rule
is explicit that no existing curated name is ever renamed or reassigned
without that sign-off, even when it has obviously landed on the wrong
community. `relabel --audit` flags them; nothing here auto-resolves.

### Misattached (audit finds no vocabulary overlap with its community)

- **QuantLib-01-foundations, id 8, "Incremental statistics and
  histograms".** New with the 2026-08-17 graphifyy 0.9.44 re-baseline (see
  "Upgrading graphifyy" below). Its anchors - unchanged since the 0.9.6-era
  pin - still best-match this community post-rebuild, but the community's
  actual content is the Clayton/Marshall-Olkin copula family
  (`claytoncopula.hpp/.cpp`, `marshallolkincopula.hpp/.cpp`) - nothing about
  incremental statistics or histograms. Where the real content moved has not
  been traced.
- **QuantExt, id 157 (id 145 before the 0.9.44 re-baseline - community ids
  are Louvain output and shift on every rebuild, they are not a stable
  reference), "Exotic swaptions and annuity mapping".** Flagged by `relabel
  --audit` after `--sync`: "swaptions" (plural) doesn't match the
  community's "swaption" (singular - `genericswaption.hpp`), and "annuity"
  and "exotic" don't appear anywhere in it at all (`crossccyswap.hpp`,
  `flexiswap.hpp`, `genericswaption.hpp/.cpp`). The "annuity mapping" part of
  the name likely described content that has since moved elsewhere. Present
  since at least the 2026-08 deterministic-rebuild pass, unchanged by the
  0.9.44 upgrade.

### No longer attach anywhere (as of the 0.9.44 re-baseline, 2026-08-17)

The 0.9.44 reclustering (see below) left 35 of the 528 previously-pinned
names unable to win any community's argmax, including the entry above
("Incremental statistics and histograms" was deliberately excluded from
`--write-anchors` rather than let it re-pin onto the copula community - its
*old* anchors are what's preserved, not a live attachment) and the
QuantLib-04-instruments-pricing "Callability schedule for callable bonds"
name flagged as misattached in earlier revisions of this doc - it now fails
to attach at all rather than attaching wrong, which is a strictly more
honest outcome, not a new problem.

Their anchor entries were **not deleted**: `write_anchors` silently
overwriting anything absent from the current `--sync` mapping was a real bug
found during this upgrade (see below), fixed to merge-preserve instead. Full
list, by chunk (35 names):

- OREAnalytics (3): Analytics manager & analytic modules; Pricing & stress
  test analytics; Risk engine header declarations
- OREData (11): Barrier data & FX barrier options; Bond & trade type
  headers; Bond data & bond builders; Convention registry & builders; Curve
  config base & headers; Model builder & market headers; Model calibration
  basket & instruments; Swap & cross-currency swap trades; Trade & builder
  source files; Trade additional data and fixings; Trade engine builders
- QuantExt (7): Asia-Pacific Ibor indexes / European Ibor & OIS indexes;
  Bond instruments & pricing engines; Country/Region Calendars;
  Cross-currency swap instruments / Instrument engine & results classes;
  FX-linked cashflows & coupons / Coupon pricers & cashflow utilities;
  Vectorised LGM & AMC engines; Volatility term structures & surfaces
- QuantLib-00-core (1): Cash flow base class
- QuantLib-01-foundations (2): Covariance decomposition and factor
  reduction; Incremental statistics and histograms (see above)
- QuantLib-02-timeinfra (4): Calendar base class and country calendars
  (mixed) / Null and weekends-only calendars (mixed); Day counter
  conventions; ECB and ASX futures dates / Dividend cash flow and
  time-basket; Overnight index definitions
- QuantLib-03-methods-termstructures (1): Binomial tree lattice models
- QuantLib-04-instruments-pricing (2): Callability schedule for callable
  bonds; Risky bond and CDS engines
- QuantLib-05-models (1): Correlation and drift-calculator interfaces
- QuantLib-06-experimental (3): FFT pricing engines (+ analytic Heston);
  Virtual power plant option instrument; YoY cap/floor price surface base /
  Interpolated YoY cap/floor price surface

Recovering any of these is the normal digest -> name -> audit -> pin loop in
docs/RELABELLING.md ("the one exception") - trace where the anchors' nodes
now live, check no other name already occupies the successor community, and
get sign-off before pinning. Never on-your-own-initiative just because a
name failed to attach.

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

Re-confirmed on 0.9.44 (the pin the repo now uses, see "Upgrading
graphifyy" below): `cluster()` on the same repro returned 348, 348, 341, and
349 communities across four unpinned runs, 344 and 344 across two runs
pinned to `PYTHONHASHSEED=0`, with the partition itself identical run to
run once pinned. Same shape as 0.9.42: the clustering-variance half of the
bug is unchanged. Do not remove the `PYTHONHASHSEED=0` relaunch in
`oregraph/cli.py` on the strength of a version bump - it is still required.

Worked around here by relaunching every `build`/`merge` under
`PYTHONHASHSEED=0`. Upstream issue (title and body updated with the 0.9.42
numbers above):
https://github.com/Graphify-Labs/graphify/issues/2817

## Upgrading graphifyy

Pinned exactly in `requirements.txt` - currently **0.9.44** - because the
committed anchors in `labels/` were generated against one version's
clustering and a different version partitions the corpus differently
(confirmed repeatedly: 0.9.6, 0.9.42, and 0.9.44 each give a different edge
count and community structure on the same input), so bumping the pin
silently detaches curated names from their communities exactly the way an
ORE upgrade does. The pin's purpose is one shared clustering across the
team; 0.9.44 is API-compatible and available on the internal mirror.

Treat a graphifyy version bump as the same deliberate operation as an ORE
upgrade, in this order:

1. Bump the pin in `requirements.txt`, reinstall.
2. Full rebuild: `python -m oregraph build`.
3. `python -m oregraph relabel --sync` - the id files are about to be
   meaningless against the new clustering otherwise.
4. `python -m oregraph relabel --audit` - must come back clean (or only
   flags already reviewed and logged above) before pinning anything.
5. `python -m oregraph relabel --write-anchors` (all chunks).
6. `python -m oregraph verify` - expect a shortfall, not 100%: anchors
   absorb most of a re-partition but not all (488/528 = 92% on the 0.9.44
   upgrade below; see "no longer attach anywhere" above for what didn't and
   why that's not itself a bug).

Do not remove the `PYTHONHASHSEED=0` relaunch in `oregraph/cli.py` as part of
an upgrade - it is still required as of 0.9.44 (see above).

### 0.9.6 -> 0.9.44 (2026-08-17): a real bug, not just re-clustering

The first rebuild against 0.9.44 lost far more than ordinary drift: 63 of 530
names attached (every code chunk got zero; only the two semantic chunks
worked). Root cause: `oregraph/build_ast.py` called
`graphify.extract.extract(code_files, cache_root=cache_root)` without the
`root=` parameter graphify added between 0.9.6 and 0.9.44 specifically to fix
this class of bug (upstream issue #1941 - `root` is the explicit
id/source_file relativization anchor; `cache_root` is only used as a fallback
when `root` is unset, and cache_root sits outside the source tree by design,
see `add_repo_paths`'s docstring). Without it, ids fell back to an
absolute-path form again, and `oregraph/fix_ids.py` - written narrowly
against 0.9.6's specific raw-id shape to repair exactly this - no longer
recognized 0.9.44's shape and left ~62% of ids unrepaired.

Fixed by passing `root=root` to `extract()`, and updating `add_repo_paths` to
resolve `source_file` against `root` instead of `cache_root` to match (it had
the same latent assumption, which the first fix alone turned into `stamped:
0` on every chunk - `link.py`'s cross-module resolution has its own
`repo_path`-missing fallback and was unaffected, but nothing else that reads
`repo_path` does). `fix_ids.py` is now a no-op on every chunk
(`"skipped: no absolute-path ids detected"`) and is kept only as a defensive
fallback, not the primary fix.

Confirmed via a controlled comparison: the unfixed 0.9.44 build's
`indexed_files` (5,523) and cross-module edge count (14,549 pre-dedup)
matched the 0.9.6 baseline (5,523 / 14,499) almost exactly; only the fixed
build diverged (5,944 / 15,376), tracking the file-index increase 1:1. Reads
as the old `cache_root`-relative path math silently under-resolving ~421
files' `repo_path` even on 0.9.6 - masked because nobody had a corrected
number to compare against - not as a regression from the fix. Final,
corrected cross-module count: **15,293** (verify's independent recount),
against a 14,168 baseline; total edges 186,010 against 190,550. Neither
should be read as a target for a future upgrade to reproduce - they are this
corpus's numbers on this graphifyy version, nothing more.

Separately, `relabel --write-anchors` turned out to unconditionally overwrite
each chunk's `.anchors.json` from scratch, with no read of the existing file
- meaning any name that failed to re-attach this round (see "no longer
attach anywhere" above) would have had its anchor history *permanently
deleted* the moment anchors were re-pinned, foreclosing exactly the recovery
path docs/RELABELLING.md describes. Fixed to merge: an existing anchor entry
whose name is absent from the current `--sync` mapping is now preserved
as-is. A related gap in the same function: two names combining onto one
community (`labels.py`'s `"A / B"` join) were being written back as a single
combined-string entry instead of two independent ones, which would have lost
either name's own anchors the moment the merge that combined them ever
un-merged. Also fixed, by writing one entry per sub-name. Both fixes are in
`oregraph/relabel.py::write_anchors`; `oregraph/verify.py` now has a
"curated-name retention rate" check (informational floor at 50%) so a
collapse like the unfixed 63/530 can never pass silently again.

## Why there is one pinned graphifyy version, not two

The 0.9.6 state (90,374 nodes, 190,550 edges, 14,168 cross-module, 530
curated names all attached, verified 2026-08-17) is preserved as git tag
`v1.0-graphify-0.9.6` rather than as a second supported configuration or a
long-lived branch. The pin's entire purpose is one shared clustering across
the team: two pinned versions would mean two anchor sets pointing at two
different community structures for the same code, which is the two-versions
problem the pin exists to prevent, not a hedge against it. A tag is the
whole safety net - the 0.9.6 state stays recoverable (`git checkout
v1.0-graphify-0.9.6`) without anyone having to keep it building, keep its
anchors current, or decide which of two graphs an agent question should
answer against.

## Docs and XSD have zero edges to code (v1.1)

`OREDocs` and `OREXsd` are extracted as their own chunks with no cross-links
into the code chunks, so "which code implements what the ScriptedTrade docs
describe" cannot be answered - and the tools don't say so. Asked that
question, `shortest_path` matches the `ScriptedTrade` class and returns a
confident-looking code-to-code path, never touching the 31 documentation
nodes on the subject. Treat any docs<->code answer as unfounded until this
is built. See README.md, "Does not work" for the user-facing version of this
same gap.
