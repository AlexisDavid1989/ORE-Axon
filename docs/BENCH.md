# The bench suite

`python -m oregraph bench` asks a fixed set of prose questions the way the MCP
server would be asked and grades what comes back. This page is the reference for
what it measures, what a pass is worth, and the tools for working on it. The
token-cost story is in [METRICS.md](METRICS.md) section 3.

## What a pass proves

Every answer now spends the whole ~2,000-token budget (1,996-2,025), so the token
column no longer tells answers apart, and "the node is somewhere in a ~90-node
answer" is a weak thing to assert. s34 once required `Swap [pricing engine
mapping]` and passed for a question about a bond, because graphify seeds the word
"fieldmap" on the best-connected mapping entry; when edges changed it failed, and
it had never shown the answer was right. So a passing entry is checked four ways:

| check | question it answers |
|---|---|
| **controls** | does the node also appear for an unrelated question? then it is a hub (*weak*) |
| **rank and margin** | how far is the node from the token-budget cut? close means *fragile* |
| **variants** | does a differently worded question still reach it? |
| **why** | was the expectation written down from the source, independent of the answer? |

## Commands

| command | does |
|---|---|
| `bench` | run the suite, write `report.md` / `results.json`, exit 1 on a failed answer, failed golden path or failing variant |
| `bench --questions PATH` | run a different suite, e.g. `bench/heldout_questions.json`. It still overwrites `results.json` and `report.md`, so run the real suite again afterwards |
| `bench --baseline OLD.json` | also diff against an earlier `results.json`; exit 1 on a regression. Read *before* the run, so `$ORE_GRAPH_OUT/bench/results.json` itself works |
| `bench --baseline OLD.json --strict` | any difference at all fails - for a graph change that must be bench-identical (CLAUDE.md rule 3) |
| `bench --explain s01` / `s01#2` | each rubric node's rank in graphify's half, oregraph's half and the merged answer, and its distance from the cut. `-(#n)` = absent from that half's own answer but rank *n* with 10x the budget. Writes nothing |
| `bench --promote` | move reached known gaps into `required_nodes`, editing the JSON textually (layout kept, CRLF kept). Weak, fragile and stub-only entries are held back with the reason; `--promote-all` overrides |
| `bench --fragility [--seeds N] [--perturb shuffle,inert]` | re-ask the suite on harmlessly perturbed copies of the graph and report which entries cross the cut. Writes `fragility.json` / `.md` only |

Each run overwrites `results.json` and `report.md`; copy them aside (or pass
`--baseline` the path) before comparing. `--explain`, `--fragility` and a bench
run on a throwaway `--questions` file are the ways to look without disturbing the
last real run - but note a run on any suite replaces `results.json`, so re-run the
real one afterwards.

## The question file

`bench/source_questions.json` is hand-formatted; the tools edit it textually and
tests pin the layout (`format_question` reproduces every existing question byte
for byte). Fields of a question:

| field | meaning |
|---|---|
| `id`, `question`, `mode`, `depth`, `token_budget` | the call. Budget defaults to 2000 |
| `required_nodes` | must be in the answer; gates the command |
| `xfail_nodes` | should be, and is not yet; reported, never gates, `XPASS` when reached |
| `variants` | paraphrases graded against the same rubric; a variant that misses a required node **gates** |
| `xfail_variants` | paraphrases known to fail; reported, never gate, must carry a `why` |
| `controls` | unrelated questions of the same shape (see below) |
| `why` | `{entry or xfail variant: reason}` |
| `meta.why_required_from` | first question id that must justify every rubric entry (`s51`) |

Entries are `label`, `label@source-file` or `src:<path fragment>`. Labels match
whole (`Swap` is not `SwapIndex`); the `@` and `src:` parts are substrings of the
node's chunk-relative `source_file` (`Bonds/Bonds.cpp`, not
`QuantLib/Examples/Bonds/Bonds.cpp`). Fieldmap labels are `X [pricing engine
mapping]`, `X [curve config mapping]`, `X [convention mapping]`, `X [trade
mapping]`; xsd nodes are `name (complexType)` with the schema's own spelling.

`verify` fails when the file is malformed (`bench.check_suite`): a `why` naming
something that is not an entry, a duplicate entry, a control that is the question
itself, an entry without a `why` from `s51` on, an `xfail_variant` without one at
any age.

### Rules for writing entries

* **Derive expectations from the source**, never from the answer they will be
  graded against: `python -m oregraph query-fields X`, ORE_Forge's data, the C++,
  `xsd/`, `Docs/`, the test directories. Write the `why` with the file and line.
  s51-s64 were drafted this way before any of them was run; the split between
  `required_nodes` and `xfail_nodes` was then mechanical (reached / not reached),
  and each gap says so in its `why`.
* **Never move an entry from `required_nodes` to `xfail_nodes` to get green
  without a written reason.** A gap for a new entry is recorded, not hidden.
* **A control must be a question whose *correct* answer excludes the node.** For a
  node true of most questions (`YieldCurve [curve config mapping]` is a config of
  every trade; `legData` is the leg of nearly every trade) no such question
  exists - leave it without controls and say so in its `why`. `controls` may be a
  list (all required entries) or `{entry: [...], "*": [...]}`.
* **A concept in `_CONCEPT_SEEDS` is domain knowledge, not an answer key.** The
  test is paraphrase - that is what `variants` are for. Write them before looking
  at any answer; keep them as written.

## Held-out questions

`bench/heldout_questions.json` is a second suite of 33 questions - `h01-h16` and
`g01-g17` - written from the ORE source (a `grep` of the Engine checkout, `query-fields`),
never from an answer, each with a `why` naming the file. It exists because the main suite's
rubric was read while retrieval was being improved, so its pass count cannot say whether an
improvement generalises. Run it after a retrieval change:

```
python -m oregraph bench --questions bench/heldout_questions.json
python -m oregraph bench                     # then the real suite, to restore results.json
```

It has only `required_nodes` (no known gaps, variants or controls), so a question either
passes or fails. Its two halves are not equal evidence, and the file says so in `meta`:
`h01-h16` were used as a development set (their failures were read), `g01-g17` were frozen
before any change was run on them and only their aggregate was ever read. Today: 31/33
questions and 51/56 entries, from 13/33 and 28/56 before the retrieval channels
([RETRIEVAL.md](RETRIEVAL.md)); `h06` and `g03` still fail (see KNOWN-ISSUES.md). Do not
tune against it question by question - when a question in it is read to fix something, it
stops being held out; write a new one.

## Definitions

**delivered** - rubric nodes present in the served answer / all rubric nodes
(required and known-gap alike). The question-level pass count is all-or-nothing;
this moves when one node comes or goes.

**precision** - the share of returned nodes that are not generic noise, pooled
over the suite; **P@10** is the same over each answer's first ten nodes, averaged
(an answer that opens with `Envelope`, `TradeActions`, `Size`, `string`, `vector`
wastes the part read first). A node is noise if (`bench.noise_kind`):

* it has **no source file** - a symbol the code mentions and the corpus never
  defines (`string`, `vector`, `Handle`, `Period`, ...), so it cannot say where
  anything is; or
* its label is C++ / standard-library / boost vocabulary or a QuantLib scalar
  typedef (`GENERIC_LABELS`), or it is a universal header (`GENERIC_HEADERS`:
  `types.hpp`, `qldefines.hpp`, ...).

The list is fixed on purpose: one derived from the suite's own answers would move
whenever the suite did. The report also lists *ubiquitous* nodes that are not on
the list (in a quarter of answers or more) as candidates.

**rank, margin** - `rank` is the node's 1-based place in the fused ranking (both
halves, before the budget cut); `margin` is the number of nodes between it and the
cut: 0 is the last node kept, negative was cut. For `src:` entries the best match.
`support` is how many matching nodes made the cut.

**weak** - the required node appears in the served answer to one of its
`controls`. **stub-only** - it is met only by a node with no source file.
**fragile** - delivered with margin < `FRAGILE_MARGIN`.

### Fragile margin

`bench.FRAGILE_MARGIN = 25` nodes. It is measured, not chosen: `bench --fragility`
rebuilt the merged graph in memory 11 ways that change no fact in it - ten
different node/edge insertion orders (`shuffle`) and 1% extra edgeless nodes no
question mentions (`inert`) - and asked the whole suite again. Each perturbed run
changed 37-39 of 50 answers (about 900 nodes in the symmetric difference across
the suite) for `shuffle`, 18 of 50 (320 nodes) for `inert`. **No delivered required
entry dropped out.** Four known gaps *crossed the cut* (got in): three from 8, 13
and 23 nodes outside it, one from outside both halves' answers entirely. How far
from the cut an entry stood when a harmless change pushed it across is how far a
harmless change can push a node: farthest 23, plus one, rounded up to a multiple
of 5.

Read it as a floor, not a guarantee. An entry beyond it is safe from *rebuild
noise*, not from a real change: `LegData` (margin 34 on "how is a swap priced")
was dropped once by a change of fusion function, not by noise. That is what
`--baseline` is for. Re-measure with `bench --fragility --seeds 10` after any
change to retrieval or to the suite's size; the report says `STALE` when the
suggested margin exceeds the constant. Distance from the cut - not rank shift at
the head of the list, which is large (`build` moved 14 places) and irrelevant - is
the right measure.

## Comparing runs

`--baseline` reports questions whose status, tokens, source files, missing nodes
or answer changed. **Regression** (exit 1): a question that now fails or is
skipped; a required entry newly missing; a known gap that had been reached and no
longer is; an entry newly weak; a variant that now fails or loses a node; a
question removed. Token and file counts, a changed answer hash and newly fragile
entries are reported but do not fail - except under `--strict`. An older baseline
without a field simply is not compared on it.

## State (2026-09-25, graphify 0.9.44)

64 questions: 61 pass, 3 xfail, 0 fail. 163 required entries, all delivered; 3 known
gaps open. Delivered 163/166 (98.2%); precision 89.5%, P@10 88.9%. 58 gating variants
all pass and none loses a node; of the 16 recorded paraphrase gaps, 7 now pass. 122
control queries. On `bench/heldout_questions.json` (see [RETRIEVAL.md](RETRIEVAL.md)):
31/33 questions, 51/56 entries, from 13/33 and 28/56.

What moved, and how (the mechanisms are in [RETRIEVAL.md](RETRIEVAL.md)): 27 questions
went from xfail to pass, with 60 gap entries promoted by `bench --promote`, which held
back only what was weak, fragile or stub-only at the time. Nothing was moved out of
`required_nodes`, no rubric entry was edited to be met, and no `_CONCEPT_SEEDS` entry
was added.

* **The three left are rubric questions.** s09 `LGM` (nine source-less stubs), s38
  `src:AsianOption` (one of 20 example directories) and s48 `src:Makefile.am`
  (QuantExt has none). They have no `why`; each needs its owner's decision.
* **Weak: the same nine.** Fragile: one, s01 `LegData`, margin 19 (was 34; the
  baseline's two, `SwapEngineBuilderBase` and `DefaultCurve`, are now robust). Stub-only:
  one, `IrLgm1fParametrization` on s09.
* **A measurement bug, fixed.** A node's source ran to the next space, so
  `fieldmap/trade/Interest Rate Swaption` was read as `fieldmap/trade/Interest` and
  s51's entry for it could not be met by any answer, however good. It now runs to
  ` loc=` (`bench._NODE_RE`; `tests/test_bench_metrics.py` pins it). s34's entry kept the
  truncated fragment and still matches.
* **`pass` is not "every gap reached".** A question is `xpass` when *any* known gap
  is reached; the number to read is `delivered`.

## State at the first run (2026-09-24, graphify 0.9.44)

Kept because it is why s51-s64 exist: 34 pass, 30 xfail, 0 fail; delivered 103/166
(62.0%); precision 88.2%, P@10 85.6%. The findings below were true of that graph.

What the new checks found, none of it visible before:

* **Coverage of the cross-domain fieldmap links is nearly absent.** Of s51-s55
  (which pricing engine prices a Swaption / FX option, which conventions a yield
  curve config uses, which curve config a CDS resolves to, which convention a
  default curve uses) only 2 of 32 entries are reached. The nodes are in the graph
  - `--explain s51` shows `EuropeanSwaption [pricing engine mapping]` at rank 189
  in oregraph's half - retrieval does not surface them for these wordings. The
  same holds for the docs (`Docs/UserGuide/curve_configurations/default_curves_*`,
  the Hull-White note), test files (`OREData/test/cds.cpp`, `conventions.cpp`,
  `sensitivityanalysis.cpp`) and the CDS complexType (s57, s58, s60, s62-s64):
  40 recorded gaps across the 14 new questions. What is reached: the swaption
  trade class, the `DefaultCurve` config entry, the netting-set doc and schema, the
  swaption complexTypes.
* **Nine weak required entries**, e.g. `SensitivityAnalysis` (also answers "how
  does the binomial tree pricing engine work"), `Period`, the `src:test/`,
  `src:experimental/`, `src:vcxproj`, `src:xsd/instruments.xsd` and
  `src:nettingdata.tex` entries. `src:test/` matches any path containing `test/`,
  `ORE-SWIG/test` included, so it is too broad to prove much.
* **Two fragile entries** (`SwapEngineBuilderBase` on s01, margin 20;
  `DefaultCurve [curve config mapping]` on s55, margin 11) and **one stub-only**
  (`IrLgm1fParametrization` on s09 is met only by a source-less node).
* **Paraphrases**: 16 of 74 variants lose nodes the original wording reaches:
  all three on s01 (`LegData`, `SwapEngineBuilderBase`), both on s14 (PnL explain
  without the words "PnL explain"), one each on s08, s12 ("credit valuation
  adjustments" for XVA), s43, s44, s51, and two each on s55, s56 and s59. They are
  in `xfail_variants`, each with its reason; the 58 that pass gate.

None of these were moved out of `required_nodes` to make the run green; the weak
and fragile legacy entries are left as they were and flagged.
