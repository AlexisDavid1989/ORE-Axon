# Field-map source characterisation

Supersedes the earlier `docs/FIELDMAP-PROFILE.md` framing (profiling loose
JSON files and proposing a join). That framing was wrong: the join already
exists, in code, in `ORE_Forge`. This document only characterises that
source — it builds nothing. Every claim below is evidence (file:line, a
live call, a measured count), not inference.

> **Update, same day:** after this was written, `ore_mapping_server.py` on
> disk changed — two new tools, `get_resolved_xpaths` and
> `get_resolved_pricing_engine_xpaths`, now wrap `UnifiedXPathProvider`
> directly (source now does `sys.path.insert` + imports it at module load,
> `ore_mapping_server.py:21-22`). This closes the Step 1b/Risk #1 gap for
> *reading* resolved XPaths: MCP alone is now sufficient for that, verified
> by calling `get_resolved_xpaths(domain="trade", type_name="FX Forward")`
> and diffing it byte-for-byte against the direct-Python-call sample in
> `docs/FIELDMAP-SAMPLES.md` — identical. The rest of Steps 1-5 and the
> other risks are unaffected and still hold; see the amended Step 1b/1c/4
> and Risk #1 below, left in place with a note rather than silently
> rewritten, since the finding that MCP was insufficient was true when
> made and the fix is itself worth recording.

> **Update, later the same day — first `fromXML()` cross-check round.**
> Checked `FX Forward` and the shared `LegData` component (used by most of
> the 177 trade types) against ORE's real C++ parsers in `Engine/OREData`.
> Found and reported four confirmed bugs to a parallel Claude Code session
> working directly in `ORE_Forge` (`ore-forge-7e`); it fixed all four,
> found the `BoughtCurrency` type bug also hit 4 more FX option entries,
> discovered `SettlementData` actually has 3 different XSD shapes across 3
> trade types (not one shared component), fixed the general code pattern
> behind `SettlementData` vanishing (39 instances across ~15 trade types
> hit the same `unified_xpath_provider.py:494-496` path — now surface as
> empty containers instead of disappearing), and — this is the one
> correction to my original report worth recording — found that `Payer`
> should stay required after all: the XSD's `legData` complexType has no
> `minOccurs="0"` on `Payer` specifically (unlike `Currency`/
> `DayCounter`/`PaymentConvention`, which do), so even though the C++
> parser tolerates a missing `Payer` at runtime, ORE_Forge's own
> XSD-validating generator must always emit it. Marking it optional broke
> XSD validation for 2 trade types in ORE_Forge's own test suite — reverted,
> kept `default_value: "true"`. All fixes verified independently here
> (re-ran `get_xpath` in a fresh process; `BoughtCurrency` is now `String`,
> `SettlementData` fully resolves to `Currency`/`FXIndex`/`Date`/
> `Rules{PaymentLag,PaymentCalendar,PaymentConvention}` matching
> `fromXML()` exactly). One practical gotcha found in the process: the
> `ore-mapping` MCP server connection this session had already opened kept
> serving pre-fix data after the other session edited the files on disk —
> its `_json_cache` doesn't auto-invalidate on external changes; a fresh
> process (or a new MCP connection) sees the fix immediately, an existing
> long-lived one doesn't without a restart. Relevant to Risk #1's
> "live-server dependency, different failure mode" framing above. Nothing
> committed to `ORE_Forge` yet — fixes are in its working tree.

> **Update, 2026-09-21 — the mapping is now in the graph.** The statement above
> that this document "builds nothing" no longer describes the repo: `oregraph
> fieldmap` snapshots all four ORE_Forge domains (trade 177 entries, curve_config
> 71, convention 26, pricing_engine 112 with all 224 valid Model/Engine pairs -
> not just the trade domain this document characterised), and `oregraph merge`
> turns the cached snapshot into 386 `OREFieldmap` entry nodes linked to the C++
> class and XSD type each maps to (`oregraph/fieldmap_link.py`; `oregraph
> query-fields` reads them). What changed against the findings below:
>
> - **Risk 8 ("no authority until checked against `fromXML()`") is answered from
>   both ends.** ORE_Forge's audits are that check. On this side the graph
>   re-derives every link it can from ORE's own source rather than trusting the
>   data: trade -> class from the TradeType registry (177/177 resolve, all
>   `EXTRACTED`); convention -> class from conventions.cpp's dispatch chain (25
>   confirmed, 0 disagreements with ORE_Forge's `Cpp_Class_Name`); the remaining
>   `Cpp_Class_Name` claims (65: the curve configs plus `BondSpread`, which
>   conventions.cpp does not dispatch) are checked against the class's own source
>   naming the entry's XML tag, and all 65 do. That check is a mention, not a
>   proof of a parse, and 7 of the 65 name nested classes the AST has no node
>   for, so they link to the enclosing class and stay `INFERRED`. Where only
>   ORE_Forge's word remains the link is `INFERRED`, and disagreements are
>   listed by `verify`.
> - **Step 5's versioning conclusion is what the graph does**: the snapshot
>   records ORE_Forge's `git rev-parse HEAD` and dirty flag, the merged graph is
>   stamped with it, and `verify` warns when the checkout has moved on. It moved
>   during this work: 9367ff4 (1 Sep, the tree this document sampled), then
>   deb8490 (21 Sep 21:46) and 675cf0e (21 Sep 22:30) - the snapshot the graph
>   carries is 675cf0e.
> - **The `enumerable` claim held for all four domains, with one correction:**
>   `get_config_types()` returns only the 20 `Is_Top_Level` curve configs (a GUI
>   filter); the other 51 entries have their own `Cpp_Class_Name` and resolve on
>   their own, so all 71 are enumerated with `Is_Top_Level` kept in `meta`.
>   Pricing engines are resolved per valid pair (`get_pricing_engine_xpath`),
>   because a product's parameter set depends on it.
> - **Fields are attributes on the entry nodes, not nodes.** They were nodes
>   first (12,135 of them); against `oregraph bench` that changed 4 of the 8
>   answers and doubled the SABR one, so the design was reversed. The reasoning
>   and numbers are in `fieldmap_link.py`'s docstring.
> - **Findings for ORE_Forge's owner this surfaced** (also reported by `verify`,
>   not fixed here - ORE_Forge is read-only to this repo): `Cpp_Builders` names
>   four classes that are absent from the Engine source at v1.8.16.0-3
>   (`LGMGridBermudanSwaptionEngineBuilder`, `LgmAmcBermudanSwaptionEngineBuilder`,
>   `LgmMcBermudanSwaptionEngineBuilder`, `SwapEngineBuilderOptimised` - each
>   appears in OREData's git history but not at HEAD; the checkout does contain an
>   `LGMBermudanSwaptionEngineBuilder`, which may or may not be what replaced
>   them - not checked); `CamAmcFxOptionEngineBuilder` exists but only in
>   `fxoption.cpp`, so the graph has no node for it; and 18 pricing products carry
>   a `Trade_Type` that is not a registered TradeType and list no builders, so
>   they link to no class.

> **Update, 2026-09-24 — the four domains are now linked to each other.** The
> entries used to link only outward (to code and to the schema). ORE_Forge also
> records how its domains refer to one another - its GUI follows those references
> through `src/core/pricing_engine_links.py`, `curve_links.py` and
> `convention_links.py`, which import only the standard library - and
> `oregraph fieldmap` now calls those resolvers itself (loaded by file path, since
> importing `src.core` would run its `__init__`, which pulls in the GUI's data
> reader). Snapshot format 3 records the result per entry and `merge` turns it into
> edges between entry nodes, all `INFERRED` because ORE's source has no table to
> re-derive them from:
>
> - **trade -> pricing engine** (`maps_to_pricing_engine`, 190 edges): the entries
>   serving the trade's `Trade_Type`, or its declared `Pricing_Engine_Type`, or -
>   for a trade that only delegates (`CallableSwap`) - the types it delegates to.
>   19 trades have several candidates (which one applies depends on trade content
>   ORE_Forge does not parse), kept whole at a lower confidence. 3 trades never look
>   an engine up and say so on their node.
> - **trade -> curve config** (`maps_to_curve_config`, 244 edges): from each field's
>   `risk_factor_type` through `SPEC_KINDS`. This is the config *type*, never a
>   curve: a trade names `EUR` or `EUR-EURIBOR-6M`, and ORE reaches the curve in two
>   hops through TodaysMarket. `YieldCurve` is the target of 171 trades (nearly every
>   trade has a currency) - a hub, see below.
> - **curve config -> convention** (`maps_to_convention`, 23 edges): a fixed
>   `linked_convention_type`, or, for a yield-curve segment, the type its own `Type`
>   selects (a table `convention_links.py` keeps in code, mirrored from
>   `yieldcurve.cpp`). Only 16 fields carry the fixed form in the data; the snapshot
>   used to drop it because the resolved nodes do not.
>
> Two things this surfaced. **For ORE_Forge's owner:** 11 trade entries have no
> pricing-engine entry serving them (for example `Commodity Asian Option`,
> `Contract For Difference`, `Equity European Barrier Option`; the `verify` warning
> lists all 11),
> and `risk_factor_type: underlying` (76 fields) has no curve-config type in
> `SPEC_KINDS`, so it is counted, not linked. **For this repo:** the links
> change entry degrees, and graphify seeds the word "fieldmap" on the best-connected
> entry - `Swap`'s pricing engine before, `YieldCurve`'s config after, for any
> question that says "fieldmap". The bench question that required the former (s34)
> was passing on that accident, not on content; it now requires content. Bench is
> otherwise identical on all 50 questions.

---

## STEP 1 — Locate the source

### a) Is the backing repo available locally? Where?

Yes. `C:\Users\Alexis\OneDrive\Documents\repos\ORE_Forge` — a sibling repo
to `ORE-Axon`, confirmed by `git -C ORE_Forge status` succeeding and
`.mcp.json` pointing the `ore-mapping` MCP server's `command` at
`ORE_Forge\.venv\Scripts\python.exe` running
`ORE_Forge\scripts\mcp\ore_mapping_server.py`.

### b) Is it importable as a Python package, or is MCP the only interface?

**Neither cleanly — and MCP is emphatically not the only interface; in fact
it's the weaker one.** Evidence:

- `ORE_Forge/setup.py` declares a package `trade-constructor` v0.2.0, built
  via `find_packages(where="src")` — i.e. only the `src/` tree is packaged.
- It is **not installed anywhere**: `.venv/Scripts/python.exe -m pip show
  trade-constructor` → `WARNING: Package(s) not found`. No `.egg-link`, not
  in `pip list`.
- The actual XPath-building code lives under `scripts/xpath/` (8,477 lines
  across 13 files), which is **outside `src/`** and therefore would not be
  included even by a proper `pip install .` of this repo as it's packaged
  today.
- `scripts/` (and every subfolder, `scripts/xpath/` included) does have
  `__init__.py` files throughout, so it's a valid import tree — just not
  one `pip` would install. The repo's own code reaches it by inserting the
  repo root onto `sys.path` and importing `scripts.xpath...` as if the repo
  checkout itself were the package root. `scripts/mapping/convert_trades.py`
  does exactly this (`sys.path.insert(0, str(PROJECT_ROOT))` then `from
  scripts.mapping.unified_format import ...`), and I used the identical
  pattern to call `UnifiedXPathProvider` directly for Step 2 below — it
  worked with no modification to `ORE_Forge`.
- `src/xpath/__init__.py` exists but is a 3-line stub; the real
  implementation is entirely under `scripts/xpath/`, confirming the
  installable `src/` package does **not** currently expose XPath building
  even in principle.

**So: not pip-installable today; importable via a path-based `sys.path`
insertion (or a git submodule + the same trick), which is what the repo's
own tooling already relies on.** A future `oregraph/fieldmap.py` that needs
to *run inside ORE_Forge's own process* (e.g. contributing to its own
scripts) would still need this. But see the update above: for
`oregraph`/`ORE-Axon` as a *consumer*, this no longer has to be
`oregraph`'s problem — the MCP server now does this exact `sys.path`
insertion itself, server-side, and hands back the resolved result. A
build-time consumer only needs the MCP connection, not a local `ORE_Forge`
checkout or a new env var, **for the resolved-XPath read path
specifically.**

Originally, and still true as a description of the two tools present at
first read (`get_entry` et al., see 1c unchanged rows): **the MCP server
did not expose the XPath-building capability at all.** Those tools read
`data/unified/*.json` directly and return the *raw, unresolved* entry —
`Fields` + `Field_Specs` with flags like `is_component_ref`, not expanded
component references, no positional leg indices, no concrete XML paths.
The resolution logic that turns that raw entry into the flat, concrete
`Trade/SwapData/LegData[1]/...` node list — expanding component refs,
choices, multi-instance legs, optionality rules — lives entirely in
`UnifiedXPathProvider` (`scripts/xpath/unified_xpath_provider.py`), which
at the time the MCP server never called. It now does — see the two new
rows in the Step 1c table. Compare directly (raw vs. resolved, still a
useful comparison for understanding what each tool gives you):

`get_entry(domain="trade", type_name="FX Forward")` via MCP returned (raw,
abbreviated):
```json
{
  "XML_Node_Name": "FxForwardData",
  "Fields": ["BoughtCurrency", "BoughtAmount", "SoldCurrency", "SoldAmount", "ValueDate", "Settlement", "SettlementData"],
  "Field_Specs": {
    "BoughtCurrency": {"data_type": "Double", "description": "The currency to be bought on value date.", "value_set": "Currency", "risk_factor_type": "currency"},
    "SettlementData": {"is_optional": true, "is_container": true, "description": "..."}
  }
}
```
vs. `UnifiedXPathProvider().get_xpath("trade", "FX Forward")` (resolved, see
`docs/FIELDMAP-SAMPLES.md` for the full verbatim output) — concrete paths
like `Trade/FxForwardData/BoughtCurrency`, container/field node distinction,
`level`, `is_activatable`, etc. Note also `SettlementData` (a container in
the raw entry) never appears in the resolved output at all — it has no
resolved node list because it isn't wired into `_expand_trade_fields`'s
dispatch (see Risks).

**If build-time snapshotting is the direction:** MCP is now sufficient for
*reading* resolved data — `get_resolved_xpaths`/
`get_resolved_pricing_engine_xpaths` hand back exactly what
`UnifiedXPathProvider.get_xpath()` produces, verified live, so there's no
need to reimplement resolution or maintain a local checkout just to read
it. What MCP does *not* give a build step is: (a) a version/commit stamp
(Step 5 — unaffected by this update, still nothing exposed), and (b) the
raw `provider.trades` dict as one object — enumeration through MCP is
still `list_types` + N × `get_resolved_xpaths` calls, not one dump call.
Whether "build time depends on an MCP server being reachable" is
preferable to "build time depends on a local `ORE_Forge` checkout on
`sys.path`" is an architecture trade-off, not a capability gap — either
route now reaches the same resolved data.

### c) MCP server's exposed tools

Source: `ORE_Forge/scripts/mcp/ore_mapping_server.py` (read in full). All
five are `@mcp.tool()`-registered on an `MCPServer("ore-mapping")` instance;
all read only `ORE_Forge/data/unified/*.json`, cached in a module-level
dict, never `data/json/*` (the legacy pre-join layer) and never
`scripts/xpath/*`.

| tool | params | returns | docstring (verbatim) |
|---|---|---|---|
| `get_mapping_guide()` | none | `str` | "Return the primer explaining how the ORE mapping system is structured (which layer is canonical, entry/field-spec conventions, referential integrity rules). Read this first." |
| `list_domains()` | none | `list[str]` | "List the mapping domains available (trade, convention, curve_config, pricing_engine)." |
| `list_types(domain: str)` | `domain` | `list[str]` | "List all entry type names defined in a domain (e.g. domain='trade' -> 'Bond', 'Basis Swap', 'Swaption', ...)." |
| `get_entry(domain: str, type_name: str)` | `domain`, `type_name` | `dict` | "Get the RAW mapping-schema entry for one type in a domain... This is the authoring-level entry, unresolved — component refs, leg parameterisation and choice calls are NOT expanded. Use get_resolved_xpaths() to get real, ORE-ready XPaths..." (docstring itself was updated to point at the new tool) |
| **`get_resolved_xpaths(domain: str, type_name: str)`** *(new)* | `domain`, `type_name` | `list[dict]` | "Return the fully resolved, flat list of ORE XPath nodes for one type in a domain — this is what ORE_Forge's own XML generator uses. Unlike get_entry(), shared components are expanded inline, multi-instance legs get real indices (LegData[1], LegData[2], ...), and choice fields ... are resolved into their concrete subtree. ... For domain='pricing_engine' this uses the default Model/Engine combination — use get_resolved_pricing_engine_xpaths() to pick a specific one." Implementation: `_get_provider().get_xpath(domain, type_name)` — a direct call to `UnifiedXPathProvider.get_xpath`, the exact function characterised in Step 1d/2. Verified live: `get_resolved_xpaths(domain="trade", type_name="FX Forward")` returned output byte-identical to the direct-Python-call sample in `docs/FIELDMAP-SAMPLES.md`. |
| **`get_resolved_pricing_engine_xpaths(product_type: str, model=None, engine=None)`** *(new)* | `product_type`, optional `model`, optional `engine` | `list[dict]` | "Same as get_resolved_xpaths(domain='pricing_engine', ...) but for a specific Model/Engine combination... Omit model and/or engine to use ORE_Forge's defaults for that product type." Implementation: `_get_provider().get_pricing_engine_xpath(product_type, model, engine)`, confirmed at `unified_xpath_provider.py:188-191` — a thin wrapper over `_build_pricing_engine` (Step 1d). |
| `get_value_set(domain: str, name: str)` | `domain`, `name` | *annotated* `list` | "Get a named dropdown/enum value set (e.g. domain='trade', name='DayCounter')." |
| `search(query: str, domain: str \| None = None)` | `query`, optional `domain` | `dict[str, list[str]]` | "Case-insensitive substring search across entry type names, XML node names, and field names. Restrict to one domain, or search all four. Returns {domain: [matching type names]}." |

One discrepancy caught by actually calling it, not by reading the
annotation: `get_value_set` is annotated `-> list` but **does not return a
bare list**. A live call —

```
get_value_set(domain="trade", name="Payer")
→ {"description": "Allowed values for Payer", "values": ["true", "false"], "source": "curated"}
```

— returns a dict (`description` / `values` / `source`), matching the
underlying `_value_sets[name]` shape for 69 of the 72 trade value sets; the
other 3 (`KikoType`, `PutCall`, `TRSNotionalType`) really are bare lists
with no `description`/`source`, so the return type is inconsistent
depending on *which* value set you ask for, and the type annotation
describes only the minority case.

The `source` field is worth flagging here since it bears on Step 3's
"confidence/verified marker" question: across the 69 dict-shaped value
sets, `source` takes 4 distinct values — `curated` (36), `xsd` (25),
`registry` (7), `ore_cpp` (1) — a real provenance signal, but it lives on
the **value set**, not on the field/XPath node that references it (see
Step 3).

### d) Functions that build XPath from the mapping table

All in `ORE_Forge/scripts/xpath/unified_xpath_provider.py` (1,289 lines),
class `UnifiedXPathProvider`. This is the canonical builder per the
project's own mapping guide (`data/unified/` = "PRIMARY (canonical)"); a
parallel, older builder for the legacy layer exists at
`scripts/xpath/config_xpath_functions.py` (`ConfigXPathProvider`, 820
lines) but is documented as deprecated and out of scope for trade fields.

| function | file:line | signature | docstring |
|---|---|---|---|
| `get_xpath` | `unified_xpath_provider.py:193` | `get_xpath(self, domain: str, item_name: str) -> List[Dict[str, Any]]` | "Get the XPath node list for an item in the given domain. Returns a flat list of node dicts compatible with the existing GUI. Each dict has: xpath, tag, is_field, value, level, type." |
| `getXpath` (back-compat alias) | `unified_xpath_provider.py:218` | `getXpath(self, trade_type: str) -> List[Dict[str, Any]]` | none (one-line: `return self.get_xpath("trade", trade_type)`) |
| `get_trade_types` | `unified_xpath_provider.py:114` | `get_trade_types(self) -> List[str]` | "Return sorted list of available trade instrument types." |
| `get_trade_types_with_groups` | `unified_xpath_provider.py:121` | `get_trade_types_with_groups(self) -> List[tuple]` | "Return list of (trade_name, asset_class) tuples for the grouped selector. Entries whose key starts with `_TEST_` are excluded. Entries without an `Asset_Class` field fall into the `"Other"` group." |
| `_build_trade` | `unified_xpath_provider.py:340` | `_build_trade(self, name: str) -> list` | none (internal; builds Trade root, TradeType, Envelope, then delegates to `_expand_trade_fields`) |
| `_expand_trade_fields` | `unified_xpath_provider.py:372` | `_expand_trade_fields(self, nodes, entry, parent_path, level)` | "Expand Fields + Field_Specs for a trade entry." |
| `_expand_container_field` | `unified_xpath_provider.py:457` | `_expand_container_field(self, nodes, field_name, spec, parent_path, level, inst_num, total)` | "Expand a container / component reference field." |
| `_resolve_choice_call` | `unified_xpath_provider.py:724` | `_resolve_choice_call(self, nodes, choice_key, param_value, parent_path, level)` | "Resolve a choice call (e.g. LegDataType) with the given param_value." |
| `resolve_optionality` (staticmethod) | `unified_xpath_provider.py:300` | `resolve_optionality(spec: dict, context: Optional[Dict[str, str]] = None) -> bool` | "Evaluate optionality rules on a field spec and return effective `is_optional`. Evaluation order (first match wins): 1. `required_when` ... 2. `optional_when` ... 3. `optionality_rules` ... 4. `is_optional` base flag (default `False` — required). *context* maps sibling field names (or `"parent_param"`) to their current values." |
| `_build_pricing_engine` | `unified_xpath_provider.py:750` | `_build_pricing_engine(self, name, selected_model=None, selected_engine=None) -> list` | "Build node list for a pricing engine Product entry." + an XML-shape example in the docstring |
| `_build_config` | `unified_xpath_provider.py:885` | `_build_config(self, name: str) -> list` | none |
| `_build_convention` | `unified_xpath_provider.py:898` | `_build_convention(self, name: str) -> list` | none |

`get_xpath` is the one entry point; it dispatches to `_build_trade` /
`_build_config` / `_build_convention` / `_build_pricing_engine` by
`domain`. For trades specifically, `_build_trade` → `_expand_trade_fields`
→ (`_expand_container_field` | `_resolve_choice_call` | inline array/field
handling) is the whole resolution path.

---

## STEP 2 — Sample the output

Called directly (not through MCP — see Step 1b for why that route doesn't
reach this method), using `ORE_Forge`'s own venv interpreter with no
modification to the repo:

```python
sys.path.insert(0, r"C:\Users\Alexis\OneDrive\Documents\repos\ORE_Forge")
from scripts.xpath.unified_xpath_provider import UnifiedXPathProvider
provider = UnifiedXPathProvider()
provider.get_xpath("trade", "FX Forward")          # Trade_Type: FxForward — 12 nodes
provider.get_xpath("trade", "Interest Rate Swap")  # Trade_Type: Swap — 84 nodes
provider.get_xpath("trade", "Interest Rate Swaption")  # Trade_Type: Swaption — 113 nodes
```

Full verbatim output (all 209 node dicts, one per line, unmodified) is in
**`docs/FIELDMAP-SAMPLES.md`**.

(There is no entry literally named `"Swap"` or `"Swaption"` — those are
`Trade_Type` values shared by several display-name entries, e.g. `Swap` is
shared by `Interest Rate Swap`, `Basis Swap`, `Cross-Currency Swap`, `OIS
Swap`, etc. `Interest Rate Swap` / `Interest Rate Swaption` are the
entries whose `Trade_Type` is exactly `Swap` / `Swaption`.)

---

## STEP 3 — Characterise the XPaths

**Absolute or relative?** Absolute, rooted at `Trade` (not `/Trade` — no
leading slash in this implementation's string convention, but always
starts from the trade root, never a relative fragment).

**Positional predicates?** Yes, `LegData[1]`, `LegData[2]` — and yes, the
indices are meaningful, not decorative. They appear only when a component
is genuinely multi-instance (both `Interest Rate Swap` and `Interest Rate
Swaption` have two legs: `[1]` is always the leg listed first in the
trade's `Fields` order — here the fixed leg — and `[2]` the second — here
the floating leg). Single-instance containers (`FxForwardData`,
`Envelope`, `OptionData`) get no index at all. The index tracks structural
declaration order, confirmed by `_expand_trade_fields`'s `inst_num`/`total`
tracking (`unified_xpath_provider.py:390-404`).

**Namespace prefixes?** None. Plain tag names throughout (`Trade`,
`SwapData`, `LegData`, ...), no `xmlns` or prefix anywhere in 209 sampled
nodes.

**One XPath per field, or per structural block?** Neither exclusively —
**one node per XML element**, field or container. Every container
(`Envelope`, `LegData[1]`, `ScheduleData`, `Rules`, `Notionals`,
`Exchanges`, `FixedLegData`, arrays like `Rates`/`Spreads`/`Caps`) gets its
own node (`is_field: false`, `type: "container"` or `"array"`) in addition
to every leaf field's own node (`is_field: true`, `type: "field"`). A
consumer that only wants leaf fields must filter on `is_field: true`.

**What accompanies each XPath?**
- `is_optional` — an explicit boolean, present on essentially every field
  node. This is a real improvement over the pre-join legacy layer (where
  no such explicit flag exists at all, only an unused type-suffix
  convention) — here it's a first-class, populated field, and it can be
  *conditional*: `resolve_optionality` supports `required_when` /
  `optional_when` rules keyed on sibling field values, evaluated only when
  a `context` dict is passed (not exercised in the plain `get_xpath` call
  used for sampling — these three samples show only the unconditional
  `is_optional` base flag; a smarter build could resolve those rules if it
  knows a trade instance's field values ahead of time).
- `data_type` — present on most but not all fields; e.g. `Notional` and
  `PayDate` in the samples carry no `data_type` key at all (absence of the
  key, not a null value).
- `value_set` — a **name reference** into `_value_sets` (e.g. `"Currency"`,
  `"DayCounter"`, `"Payer"`, `"BusinessDayConvention"`), not the actual
  allowed values inline. Fetching the real values is a second call
  (`get_value_set` via MCP, or `provider.trades["_value_sets"][name]`
  directly).
- `description` — **absent from every one of the 209 sampled nodes.**
  Confirmed present in the *raw* MCP `get_entry` output for the same trade
  (`FX Forward`'s `BoughtCurrency` field carries `"description": "The
  currency to be bought on value date."` in the raw entry), so this is
  data loss introduced specifically by `get_xpath`'s resolution step, not
  a gap in the source data.
- confidence/verified marker on the node itself — **none.** (`source`
  exists, but one level removed, on the value set the field references —
  see Step 1c.)
- `is_activatable`, `risk_factor_type`, `value` (default), `level`,
  `is_choice_based`, occasionally `is_dated_array` /
  `mutually_exclusive_with` (seen in code, not in these 3 samples) round
  out the shape.

**Is the same field reachable by more than one XPath?** Yes, by design,
whenever a component is multi-instance: `Currency`, `DayCounter`,
`PaymentConvention`, `Payer`, `ScheduleData/Rules/*`, `Notionals/*` all
appear once under `LegData[1]/...` and again under `LegData[2]/...` — two
distinct concrete XPaths for the same field *name*, disambiguated by the
leg index. This is expected, not an ambiguity — but a consumer keying
purely on field name (ignoring the full path) would collide leg 1 and leg
2 data, same risk noted in the earlier (superseded) profile's Step 2a.

---

## STEP 4 — Enumerability

**Can the full mapping be enumerated, or only queried point-wise?**
Fully enumerable, and this is already a well-used pattern in `ORE_Forge`
itself, not something novel being proposed here.

- `provider.get_trade_types()` returns **all** trade type names: **177**,
  confirmed live.
- `provider.get_xpath("trade", name)` returns **all** fields for one trade
  type (that's what Step 2's samples are).
- Looping both together dumps the **whole** mapping table. Measured live:

  ```
  177 trade types → 9,882 total nodes, enumerated in 0.015s, 0 errors
  ```

- This exact loop is not hypothetical — it's already how `ORE_Forge` tests
  and validates itself: `scripts/generate_baselines.py`,
  `scripts/generate_validate_portfolio.py`,
  `scripts/audit/verify_all_trades.py`, and `scripts/audit/xsd_validate.py`
  (and `_v2`) all call `get_trade_types()` then loop `get_xpath("trade",
  name)` for every one, for their own baseline-generation and XSD
  validation purposes.
- The raw dict is also directly available without even calling a method:
  `provider.trades` is the fully parsed `data/unified/trades.json`
  (`_components`, `_choices`, `_value_sets`, `entries` — literally the
  "whole mapping table") — this requires local repo access, same
  constraint as calling `get_xpath` itself (Step 1b).

**Through MCP specifically:** updated finding — enumeration of *resolved*
data is now possible too, not just raw entries. `list_types("trade")`
gives the 177 names, then `get_resolved_xpaths(domain="trade",
type_name=...)` per name gives the same resolved node list
`UnifiedXPathProvider.get_xpath()` would (verified in Step 1c). Still no
single MCP call dumps everything at once — full enumeration is still
`list_types` + N tool calls, not one request — but unlike the original
finding here, those N calls now return resolved data, not raw entries.

---

## STEP 5 — Versioning

- **Git commit is the strongest signal, and it directly covers the file in
  question.** `ORE_Forge` HEAD = `9367ff49bb2819ab71b97ae1450ff8928dd7433b`,
  committed 2026-09-01 17:48:21 +0100, message "Fix ScheduleData fields
  mis-mapped to DirectRulesSchedule component" (notably, in exactly the
  `ScheduleData`/`Rules` area sampled above — this data is under active
  correction). `git log -1 -- data/unified/trades.json` returns the same
  commit, and `git diff HEAD -- data/unified/trades.json` is empty — the
  file used for these samples is exactly what that commit produced, not a
  dirty working-tree variant. (The working tree does have unrelated
  uncommitted changes — `.gitignore`, an untracked `scripts/mcp/` — but
  they don't touch `data/unified/`.)
- **The file's own embedded version is unreliable.**
  `data/unified/trades.json["_metadata"]["version"]` reads `"1.0.0"` — a
  string hardcoded once in `scripts/mapping/convert_trades.py`'s output
  construction, never bumped per change. It does not track content drift;
  the git commit does.
- **The application-level version is internally inconsistent** and should
  not be trusted either: `setup.py` declares `version="0.2.0"` for the
  `trade-constructor` package, while `src/__init__.py` separately declares
  `__version__ = '2.0.0'` — two different numbers for what's nominally one
  version.
- **The MCP server exposes no version at all** — no tool in Step 1c
  returns a version, commit, or revision of any kind. Still true after the
  server update noted above: the two new resolved-XPath tools don't carry
  a version/commit stamp either. If the build route becomes "MCP only,"
  this gap gets *more* load-bearing than under a local-checkout route,
  since a local checkout can at least run `git rev-parse HEAD` itself —
  going through MCP alone gives no way to ask the server what commit it's
  currently serving.

**Conclusion: use the `ORE_Forge` git commit hash as the version stamp**
(the same pattern this repo already uses for ORE's own commit), read via
`git -C <ORE_Forge checkout> rev-parse HEAD` at build time, with a
dirty-working-tree check before trusting it — not the file's own
`_metadata.version` field, and not either of the two disagreeing
application version numbers.

---

## RISKS

1. ~~MCP is not sufficient on its own for build-time use.~~ **Superseded
   the same day** — `ore_mapping_server.py` was updated to add
   `get_resolved_xpaths`/`get_resolved_pricing_engine_xpaths`, direct
   wrappers over `UnifiedXPathProvider` (see the Update note at the top of
   this document). MCP is now sufficient for *reading* resolved XPaths;
   verified by diffing a live MCP call against the direct-Python-call
   sample. What remains true: this is a live-server dependency (the
   consuming build step must be able to reach the MCP server at build
   time) rather than a filesystem dependency (a local checkout on
   `sys.path`) — a different failure mode, not a smaller one. A server
   that's down, unreachable from CI, or serving a stale/uncommitted
   `data/unified/` tree would silently degrade a build the same way a
   stale local checkout would, and Step 5's versioning gap (below) means
   neither route currently tells you *which* commit's data you got.
2. **`get_xpath` silently drops `description`.** Present in the raw
   `Field_Specs` (and returned by MCP's `get_entry`), absent from every
   node `get_xpath` emits (Step 3). A downstream consumer of resolved
   XPaths alone loses all human-readable descriptions unless it separately
   fetches the raw entry too and re-joins by field name.
3. **Confidence/provenance exists, but not where you'd query for it.**
   `source` (`curated` / `xsd` / `registry` / `ore_cpp`) lives on the
   value set, reachable only via a second call
   (`get_value_set`/`provider.trades["_value_sets"]`), not on the field or
   XPath node itself. A field referencing a `registry`-sourced value set
   looks identical, at the node level, to one referencing an `ore_cpp`- or
   `curated`-sourced one.
4. **`SettlementData` (seen in FX Forward's raw entry) never resolves, and
   the exact mechanism is confirmed, not guessed.** In
   `_expand_container_field` (`unified_xpath_provider.py:489-496`), a
   "plain container" field looks up its component by
   `spec.get("component_name", field_name)` — `SettlementData`'s raw spec
   sets neither `component_name` nor `is_component_ref`, so it falls
   through to the plain-container branch and looks itself up in
   `_components["SettlementData"]`. Confirmed live:
   `"SettlementData" in trades.json["_components"]` → `False` (only 75
   components are defined at all). Line 495-496 then reads: `if not comp
   and spec.get("is_optional", False): return` — since the field is also
   `is_optional: true`, it returns **before** the container node itself is
   even appended, so `SettlementData` produces zero nodes, not an empty
   container. This wasn't chased further per the "build nothing"
   constraint, but it means "all fields for a trade type" (Step 4) is
   enumerable and complete for *resolved* fields only — an optional
   container field with a missing component definition disappears
   silently between `get_entry` and `get_xpath`, for the very first sample
   trade type checked. Whether this is unique to `SettlementData` or a
   wider pattern across the 177 trade types was not checked (would require
   its own measurement, not assumption).
5. **`BoughtCurrency`/`SoldCurrency` data-type inconsistency** (`Double`
   vs `String` for what are both currency codes, Step 2 sample) is in the
   source data itself, not introduced by resolution — flagged since it
   would propagate into anything built on top without correction upstream.
6. **Versioning requires a discipline this repo doesn't currently have.**
   The commit-hash approach (Step 5) only works if whoever runs the build
   step checks out a clean `ORE_Forge` tree and reads its HEAD at that
   moment — there's no server-side version endpoint to query remotely, so
   "what version produced this snapshot" is only knowable if the build
   process captures it itself, not something the source hands you for
   free.
7. **`get_value_set`'s return shape is inconsistent** (dict for 69/72
   value sets, bare list for 3 — Step 1c) and disagrees with its own type
   annotation. Any consumer needs to branch on `isinstance(result, dict)`
   rather than trusting the declared `-> list`.
8. **This data has no authority until checked against `fromXML()`,
   per the standing constraint — and that check was out of scope here.**
   Steps 1-5 establish that the source is real, resolvable, and
   enumerable; they say nothing about whether it's *correct* against
   ORE's actual C++ parsing. The one `source: ore_cpp`-tagged value set
   found in Step 1c (out of 72) suggests at most a small fraction of this
   data has ever been cross-checked against the C++ source directly — the
   rest (`curated`, `xsd`, `registry`) are one or more steps removed from
   `fromXML()` itself.
