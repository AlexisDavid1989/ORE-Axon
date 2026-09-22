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

## `query-example` on a trade class returns the whole `portfolio/` directory

`query-example FxForward` (and any class an instruments.xsd type is linked
to) fills its entire 80-file budget with `TRADE/DATA`, one line per trade
class in OREData, and every later section reads `TRUNCATED`. Cause: since
`schema_for` joined `BUNDLE_RELATIONS` (commit ab56558), the traversal goes
class -> instruments.xsd's summary node -> every other class that node is
`schema_for`-linked to (160 of instruments.xsd's 218 `schema_for` edges start at
that one node, as of the link_schema.py Tier 4 work), which is depth 2. Confirmed present before
the fieldmap change (81 `TRADE/DATA` lines on the same query against the
pre-fieldmap graph) - the fieldmap section was moved to the front of the bundle
only so it is not starved by it. Not fixed here because the right fix is a
decision: skip hub nodes in this traversal, cap per-relation fan-out, or anchor
`schema_for` at the type's own node instead of the file summary (which is the
step-3 XSD work and would remove the hub).

## The 8 XSD files with zero links are now closed (2026-09-22)

Was: `calendaradjustment.xsd`, `counterparty.xsd`, `creditsimulation.xsd`,
`historicalreturnconfig.xsd`, `input.xsd`, `ore.xsd`, `scriptlibrary.xsd` and
`stress.xsd` had no `schema_for`/`implements` edge of any kind - the OREXsd
node existed, but nothing connected it to the code that parses it. Cause:
ORE_Forge's field mapping never modelled these files at all (it only covers
trade/curve_config/convention/pricing_engine), and `link_schema.py`'s Tiers
1-3 are all name-matching, which cannot find a link like the `ORE` xsd tag to
the `Parameters` class - no name resemblance whatsoever.

Closed by three mechanisms, all source-verified, none guessed:

- **A real bug in the shared class-resolver, found while investigating why
  these files matched nothing.** OREAnalytics' `app/inputparameters.hpp`
  forward-declares dozens of classes it does not define
  (`class StressTestScenarioData;`, `class ReturnConfiguration;`,
  `class ScriptLibraryData;`, `class CreditSimulationParameters;` among them,
  confirmed by reading the file), and graphify's AST extractor gives a forward
  declaration the same `_callable_class` node shape as a real definition -
  indistinguishable without reading the source, so it silently made an
  otherwise-unique class name look ambiguous. Fixed in `_resolve_code_node`
  (`link_schema.py`) and the equivalent `_pick` (`fieldmap_link.py`) by
  preferring whichever single candidate's own source is a real definition
  (`_defines_class`: the declaration runs to a `{`, not a `;`). The fix can
  only turn a previous None into a match, never change an existing one -
  confirmed by diffing the merged graph before/after, no existing edge
  changed. This alone closed `historicalreturnconfig.xsd` (-> `ReturnConfiguration`,
  Tier 2), `scriptlibrary.xsd` (-> `ScriptLibraryData`, Tier 3) and
  `creditsimulation.xsd` (-> `CreditSimulationParameters`, Tier 3), and
  resolved 18 names in total across Tiers 2/3 (`SCHEMA_LINKS_BASELINE`
  re-pinned 261 -> 290; see that constant's comment for the breakdown).
- **Tier 4**, new in `link_schema.py` (`_root_class_declarations`): scans
  OREData/OREAnalytics source directly for the three idioms this codebase
  actually uses to validate an XML root's tag (`XMLUtils::checkNode`,
  `XMLUtils::getNodeName(...) ==`, `portfolio.cpp`'s own `node->name()) ==`),
  and links a root xsd element to the one class whose own `fromXML()` checks
  that literal tag - orthogonal to Tiers 1-3 (all name-matching, so they
  cannot find a link like the `ORE` xsd tag to the `Parameters` class, no
  name resemblance at all). 0 candidates (no source evidence) or >1
  (ambiguous) are reported, never guessed at. Closed `calendaradjustment.xsd`
  (-> `CalendarAdjustmentConfig`), `counterparty.xsd` (-> `CounterpartyManager`),
  `ore.xsd` (-> `Parameters`), `stress.xsd` (-> `StressTestScenarioData`) and,
  together with the dispatch pass below, `referencedata.xsd`.
- **A new dispatch-table pass** in `xsd_link.py`: `_authoritative_pass`
  (previously hardcoded to strip a trailing "Data" suffix) was generalized to
  a configurable suffix and pointed at `referencedata.xsd`'s
  `referenceDataTypes` dispatch group against `databuilders.cpp`'s
  `ORE_REGISTER_REFERENCE_DATUM` table - the same dispatch-table shape the
  trade/convention passes already use, just a different macro and a
  "ReferenceData" suffix instead of "Data". Both suffixes are tried, longest
  first, since one entry (`BondBasketData`) only has the bare "Data" suffix
  (see below for why it still doesn't produce an edge). This is in addition
  to Tier 4's link for `referencedata.xsd`'s own container tag
  (-> `BasicReferenceDataManager`) - the two cover different things (the
  container vs. its per-type dispatch alternatives) and both are needed.
- `input.xsd` closed as a side effect of the forward-decl fix unblocking
  Tier 2 for its `Portfolio` root element, not through Tier 4 or the dispatch
  pass.

Confirmed additive throughout: diffed the merged graph before and after this
whole change, no existing node or edge was altered, and `oregraph bench` was
unaffected (13,591 -> 13,671 tokens across the 8 questions; one question
gained a genuinely relevant file it was missing before).

What's still genuinely open within this, not chased further:

- **`Simulation`'s own root tag has no source evidence at all** - no class in
  OREData or OREAnalytics validates the literal `<Simulation>` wrapper tag
  (confirmed by direct search, not merely a search miss). `CrossAssetModel`,
  its most substantial child, does resolve, but the outer wrapper doesn't.
  Legitimate finding: worth asking ORE_Forge's or the Engine's owner whether
  that's intentional.
- **`referencedata.xsd`'s `BondBasketData` still produces no edge, for a
  different reason than first thought.** It was originally skipped outright
  because its element name doesn't end in "ReferenceData" like its 12
  siblings; `_authoritative_pass` now tries the bare "Data" suffix too
  (2026-09-22), and that part works - `BondBasketData` -> `BondBasket` ->
  `BondBasketReferenceDatum` resolves correctly (confirmed by an isolated unit
  test). But no edge reaches the real graph, because the OREXsd extraction
  never produced a node for this one type at all (checked directly: no
  `OREXsd` node exists for it, unlike its 12 siblings) - the exact same
  pre-existing extraction gap that leaves 115 of 182 trade-dispatch elements
  unmatched (see the `xsd-to-code links present` checks). Confirmed the fix
  changed nothing in the merged graph (diffed before/after: 0 nodes, 0 edges
  changed) - it only moved this entry from silently skipped to honestly
  reported as unmatched, which is the correct outcome given the missing node,
  not a regression. Closing it for real needs the same fix the query-example
  hub issue above is waiting on: OREXsd nodes for the types the LLM
  extraction currently has none for.
- **`ore_types.xsd`'s ~60 shared simple-type enums** (`dayCounter`,
  `businessDayConvention`, `calendar`, ...) are parsed by free functions in
  `OREData/ored/utilities/parsers.cpp` (`parseDayCounter`, `parseFrequency`,
  ...), not by a class's `fromXML()` - a different kind of link (type ->
  function, not type -> class) neither Tier 4 nor any existing pass attempts.
  **Checked and closed as not viable (2026-09-22), not merely deferred:**
  graphify's AST extraction does not reliably create nodes for free functions
  in this codebase - checked 7 parser functions directly in the merged graph
  (`parseDayCounter`, `parseFrequency`, `parseCompounding`, `parsePeriod`,
  `parseBool`, `parseReal`, `parseDate`), and 6 have zero nodes at all. The one
  exception, `parseCurrency`, isn't even the free function: it's a
  coincidentally-named method on a different class (`CurrencyParser`) that the
  real free function just delegates to in one line. Building this link would
  mean linking most of the ~60 types to nothing and occasionally linking one to
  the wrong thing - worse than the current honest gap. Would need a change to
  the extraction itself (or a source-level join bypassing node lookup
  entirely, e.g. matching `parseX` definitions directly the way
  `_root_class_declarations` matches `fromXML`) before this is worth
  attempting again.
- **`input.xsd`'s other elements** (`Trade`, `SubTrade`, `componentTrade`,
  `componentSubTrade`, `subTradeGroup`) are reachable indirectly, through
  instruments.xsd's own trade-type dispatch, not through a dedicated class of
  their own - not chased separately.

## Field mapping: what the graph knows it does not know

Reported by `verify` on every run rather than fixed, because each needs a
decision by whoever owns ORE_Forge or the XSD extraction:

- **132 of 383 entry -> XSD links anchor at the schema file's summary node, not
  the type's own node** (251 are type-level). The OREXsd extraction has 337
  nodes against 955 declared names, and the fallback anchor is the same one
  `schema_for` uses. Type-level anchoring needs nodes for the missing types.
- **Closed (2026-09-22): 4 of the original 6 ambiguous curve-config entries now
  resolve.** `Segments`, `InflationSegments`, `YieldCurveReport` and
  `Calibration` all name an element curveconfig.xsd declares more than once
  with different types depending on the parent element (`Segments` under
  `YieldCurve` vs. under `InflationCurve`, etc.). `fieldmap_link.py`'s
  `_parent_narrowed_type` now uses the entry's own `Parent_Node` (already
  present in ORE_Forge's data, previously unread) to resolve the parent's own
  type and look the child up as its direct element - still never a guess:
  ambiguous either way stays unresolved. Confirmed additive (`oregraph bench`:
  13,671 tokens before and after, identical to the last measured baseline in
  "The 8 XSD files with zero links" below - this only added edges to nodes
  already in the graph, no new nodes).
- **2 curve-config entries still resolve to no XSD type, for two different
  reasons, neither fixable by narrowing further**: `Report` has no
  `Parent_Node` in ORE_Forge's data at all - it is deliberately the *default*
  `ReportConfig` shared by eight different parents that mostly agree on one
  type (`reportConfiguration`), except `YieldCurve` (which is the separate,
  now-resolved `YieldCurveReport` entry) - closing it needs a majority/fallback
  heuristic, exactly the kind of guess this join's docstring says it
  deliberately avoids; and `baseltrafficlightconfig` is a lower-case key with
  no matching element in curveconfig.xsd at all - confirmed by direct search,
  not a lookup gap. `BondSpread` (convention) is in ORE's `fromXML()` but not
  declared in conventions.xsd at all.
- **ORE_Forge's `Cpp_Builders` lists four classes absent from the Engine source
  at HEAD, 7 curve-config entries carry no `Cpp_Class_Name` at all, and 18
  pricing products have no class link** - see `docs/FIELDMAP-SOURCE.md`'s
  2026-09-21 update. Findings for ORE_Forge, which this repo only reads.
- **`Commodity Swap`: ORE_Forge's `XSD_Type` is `commoditySwapData`, the
  schema's `SwapData` element declares `swapData`.** It is the CommoditySwap bug
  already described in `docs/XSD-DRIFT.md` (the schema names the wrong wrapper
  element), rediscovered independently by the graph's XSD derivation.

## Docs and XSD have zero edges to code (v1.1)

`OREDocs` and `OREXsd` are extracted as their own chunks with no cross-links
into the code chunks, so "which code implements what the ScriptedTrade docs
describe" cannot be answered - and the tools don't say so. Asked that
question, `shortest_path` matches the `ScriptedTrade` class and returns a
confident-looking code-to-code path, never touching the 31 documentation
nodes on the subject. Treat any docs<->code answer as unfounded until this
is built. See README.md, "Does not work" for the user-facing version of this
same gap.
