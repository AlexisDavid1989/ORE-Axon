# Retrieval: how `query_graph` answers a prose question

The served answer is two retrievals fused under one token budget (~2,000 tokens, about
90 nodes): graphify's own, which we do not modify, and `query.query_question`, which
this page is about. What the budget cuts is decided by *order*, so order is the answer.

## The order `query_question` produces

1. **lead** - nodes of a kind the question asks for (`channels.kind_seeds`)
2. **seeds** - the lexical seeds, at most six (`query.resolve_question`)
3. **tail** - what completes an answer about them (`channels.plan`): typed fieldmap
   entries, engine builders and engines, a schema type's components, base classes,
   header siblings, the best-known derived classes, strong label matches
4. **rest** - everything the traversal reaches from the lead and the seeds, hop by hop;
   inside a hop: by how many of the question's words the label says *that no seed
   already says*, then a seed's derived classes last, then the members other code calls
   most, then the traversal's own order

Only the lead and the seeds are *expanded*. The tail is inserted, not walked: expanding
it reorders answers that never asked for it.

## Why one lexical scale was not enough

Measured on `bench/source_questions.json` on 2026-09-24: 30 of 64 questions failed, 63
rubric nodes missing. Reading where each missing node was (`bench --explain`, and the
graph itself) gave seven causes. None was "the node is not in the graph":

| cause | example | what fixes it |
|---|---|---|
| Wrong same-label node seeded. Every header that holds a `DayCounter` member gets a node for the type; one (callablebond.hpp, degree 70) out-connected the class (time/daycounter.hpp, degree 11), and seeding took the busier | s19, s10 | prefer the node in the file named after the label (`query._defines_label`) |
| A kind of artifact, scored on the class scale. "Default Curve from CDS" (a user-guide page) scores ~10 against a class's 120 and never makes six seeds | s57, s58, s62-s64, s36, s37, s60 | kind channels: search tests / docs / schema among themselves |
| Typed links walked as if untyped. `YieldCurve [curve config mapping]` has 13 `maps_to_convention` edges and 171 incoming from trades | s51-s55, s34, s35 | fieldmap channel: follow the link type the question names |
| A relation the code does not have. A trade's engine builder is looked up by a trade-type string, so there is no edge from `EquityOption` to its builder; the fieldmap entries name both | s03, s06, s53 | registry path, then builder -> engine, plus the builder's base class |
| Near a seed, not named by the question. `MakeSchedule` beside `Schedule`, `ShortRateModel` above `HullWhite`, 80 neighbours of `Period` of which one is `parsePeriod`, 54 members of `Calendar` of which one is the API | s20, s25, s26, s21, s18 | siblings, ancestors, label overlap, member usage |
| **The graph.** 2,146 of 3,967 `inherits` edges (54%) ended at a per-header stub, never the class: `DayCounter` had 11 edges and none of its 13 day counters | s19, s23 | `symbol_links.link_inheritance`, in `merge` |
| **The measurement.** A node's source was read to the next space, so `fieldmap/trade/Interest Rate Swaption` was `fieldmap/trade/Interest` and s51's entry for it could not be met | s51 | `bench._NODE_RE` reads to ` loc=` |

## Rules the channels keep

* **Silent when nothing matches.** Every channel scores its topic (question words minus
  the kind's own vocabulary and question-form filler) and returns nothing when no name
  covers it, so a misfiring intent costs no more than the words it would have spent.
* **The intent vocabulary is English about artifacts** ("tests", "user guide",
  "schema", "engine", "convention"), never the name of an answer. A word added to
  `FILLER`, `TEST_WORDS` etc. must hold for any question; the check is a paraphrase,
  and `tests/test_channels*.py` have them. It is the same rule as `_CONCEPT_SEEDS`.
* **Exact words beat acronyms** (0.6), in both directions: "cds" finds
  `creditDefaultSwapData`, "credit default swap" finds `cds.cpp`, and neither outranks
  a name that says the words. Names with no word boundary ("digitalcms.cpp") are cut
  into the graph's own vocabulary first (`channels.segment`).
* **A name that *is* the topic beats one that contains it**: "fx option" finds `FxOption`
  before `FxAsianOptionArithmeticPrice`; "Swaption" finds the trade entry whose
  `trade_type` is `Swaption` before `CommoditySwaption`.
* **A hub is not a subject.** A framework base (`Observer`, `XMLSerializable`, `Results`;
  or, for derived classes, one with more than 40) is never listed as an ancestor or
  as a family, and derived classes are only listed for the question's main subject: a
  second seed is often matched by one word ("trade").
* **A word a seed already says tells nothing new about its neighbours.** Fifty of a
  `Swap` seed's neighbours are named `...Swap...`; sorting on that put them ahead of
  `LegData`.

## Evidence

The bench alone cannot say whether this generalises - the rubric was read while the
channels were built. Two question sets were written from the source tree (`grep` of the
Engine checkout, `query-fields`), not from any answer, and are kept in
`bench/heldout_questions.json`:

| set | how it was used | before | after |
|---|---|---|---|
| `h01-h16` | written first, then read as failures appeared: a *development* set | 8/16 questions, 15/26 entries | 15/16, 23/26 |
| `g01-g17` | written after, frozen (sha256 `2311f38e...`), only aggregates ever read | 5/17, 13/30 | 16/17, 28/30 |

`g01-g17` is the number to trust: it went from 29% to 94% without being looked at.
The two that still fail (`h06`, `g03`) are described in
[KNOWN-ISSUES.md](KNOWN-ISSUES.md), with the other limits of this work.

On the 64-question suite: 34 pass -> 63 (61 by retrieval and graph changes, then two more
when their unfair rubric entries were rewritten); delivered 103/166 -> 163/166; precision
88.2% -> 89.4%, P@10 85.6% -> 89.1%; no required entry lost, no paraphrase lost, 7 of the
18 recorded paraphrase gaps now pass. One legacy required entry paid for it: s01 `LegData`
went from margin 34 to 19 (fragile below 25), because a pricing question now spends ~20
nodes on builders and engines that used to be the neighbours' turn. The baseline's two
fragile entries are now robust.

What was tried and left out, with the reason:

| idea | result |
|---|---|
| personalised-PageRank ordering | closed 4 gaps beyond the definer rule but failed s01 (a passing question), and did nothing on `h01-h16` |
| the same, plus demoting a class's members (x0.3) | 10 gaps closed on the suite, none on held-out, P@10 85.6% -> 81.9% |
| IDF-dampening the seeds | closed nothing the definer rule had not |
| one seed per (label, project) | fixed s20, failed five passing questions (s02, s05, s11, s22, s29): duplicates crowd out other concepts |
| strong label matches jump hops | reopened s23; `g01-g17` 15 -> 14/17 |
| tie-break by node degree | broke s08's paraphrase; `g01-g17` 15 -> 14/17 |
| tie-break by "used by" among every node that shares a word | margins for s06 and s23 rose to ~50, but `g01-g17` 15 -> 14/17 |
| a sourced class before a member as a tie-break | P@10 88.9% -> 90.5%, but s01 `LegData` fell from 19 to 13 |
| no seed without a source file (a stub holds a seed slot on s09) | neutral on the suite and both held-out sets, and did not reach s09's three entries |
| skipping a hub's derived classes in the traversal | did nothing: `Trade` has 32, so it is no hub; the fix was ranking a seed's derived classes last |

Two mechanisms have evidence from the suite only (they change nothing on either held-out
set): the global label-overlap channel (`parsePeriod`) and member-usage ordering
(`isBusinessDay`). They were kept because they cost no regression and are the natural
reading of "the question says these words" and "this is the class's API"; drop them
first if either ever looks wrong.

## The graph change

`merge` now runs `symbol_links.link_inheritance` after `link_symbols`. Of 2,146 `inherits`
edges that end at a stub, it points 1,249 at the class they name (937 at the class in the
file named after it, 312 at the only class of that name), and leaves 204 that name several
classes and 693 that name none. The stub edge stays, so nothing graphify saw before is
gone. Nodes: 94,442 both before and after; links 196,215 -> 197,464. `verify` fails if a
graph still has an edge the pass would resolve. Measured against the same retrieval on
the graph without it: s19 (`Actual360`, `Thirty360`) reached and `g01-g17` one question
better, nothing lost. It needed the derived-class step to be safe: on its own the pass
made 24 `*Interpolation` classes reachable and pushed s23's `LinearInterpolation` out of
the answer.

## Still open

One question, s09 ("how does the LGM model calibrate"), and it is a retrieval gap. Its three
unreached entries are `LgmData`, `LinearGaussMarkovModel` and `Lgm1fParametrization`, the
classes `LgmBuilder::calibrate()` reads, calls and calibrates (drafted from
`lgmbuilder.cpp:156-291`, before any answer was seen). The answer reaches `LgmBuilder` and
little else: the second seed is the source-less stub `IrLgm1fParametrization` (an alias in
`_CONCEPT_SEEDS` that predates this work, for a name that is only a typedef), and the two
classes sit two hops out behind hubs (`LgmData` has 63 edges, `LinearGaussMarkovModel` 90).
Keeping stubs out of the seeds is neutral everywhere and does not reach them. Naming the
three classes in `_CONCEPT_SEEDS` would pass the question and prove nothing, which is
the answer-key move `CLAUDE.md` rules out.

The other entries that used to be open were the reverse: unfair, and rewritten on
2026-09-25 rather than chased. s09's own old entries, `LGM` and `IrLgm1fParametrization`,
were met only by source-less stubs (the second is a typedef of a template). And:

* **s38** required `src:AsianOption`, one of the 20 example directories and the first
  alphabetically, for "what do the example programs demonstrate". It now asks which example
  prices Bermudan swaptions with calibrated short-rate models - the README's own words for
  `BermudanSwaption` - and requires that program. Reached without any new mechanism.
* **s48** required `src:Makefile.am` for "how does the ORE build system compile QuantExt".
  QuantExt has none (its build is CMake and a vcxproj); all 120 in the checkout are
  QuantLib's autotools files. It now asks how to build ORE from source and requires the
  user guide's CMake chapter. Reached, with both paraphrases. QuantExt's own
  `CMakeLists.txt` is still not in the corpus, since `CODE_EXTS` has no build-file
  extractor; that is a corpus decision, not something retrieval can fix.

## Cost

The oregraph half takes about 0.2 s per question warm (median 209 ms, p90 331 ms, max
462 ms over the suite), plus a one-off ~1.6 s on the first question that searches the
~9,000 test nodes, ~0.2 s for the docs and the fieldmap. The kind indexes, the fieldmap
entries, the label vocabulary and the label-stem index are built on first use and cached
on the graph object.

## Changing this

* Add a held-out question before you tune, and read the aggregate, not the failures.
* `bench --baseline <copy of results.json>` before and after; a change here moves every
  answer, so "identical" is not the target - "no required entry lost, no paraphrase
  lost" is. Read `delivered`, not `xpass`: a question is `xpass` when *any* gap is
  reached.
* A defect you fix gets a `verify` check (`same-label seeds resolve to the defining
  file`, `inherits edges reach the class they name`, `retrieval channels have their
  kinds` are the three for this work).
