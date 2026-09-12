# Field-map profile: ORE trade field mapping data

## Scope note — read this first

There is no `fieldmap/` directory anywhere. It does not exist in this repo
(`ORE-Axon`), in the sibling repos (`Engine`, `ORE_Boosted`, `ORE_Forge`), or
under `ORE_ENGINE`. Grepping both `ORE-Axon` and `ORE_Forge` for the string
"fieldmap" returns nothing.

The `ore-mapping` MCP server (registered in `.mcp.json`) is backed by a
different project, `ORE_Forge` (a "Trade Constructor" GUI), and its tools
only expose `ORE_Forge/data/unified/*.json` — an **already-merged** layer.
The user confirmed the intended source is ORE_Forge's JSON mapping data plus
its Python xpath-query functions, so this profile treats
**`ORE_Forge/data/json/`** as the data the task calls `fieldmap/`: five files
that are genuinely normalized and require a join (`data/unified/` is the
*output* of that join, produced by `scripts/mapping/convert_trades.py`, which
this profile also read as ground truth for how the join is actually done
today).

Two things follow from this substitution, both treated as findings rather
than silently resolved:

- **Path is undecided.** If/when `oregraph/fieldmap.py` is built, it needs a
  path into a *different repository* than the one it lives in. Per this
  repo's own rule ("never hardcode a path... `oregraph/config.py` resolves
  them"), this will need a new env var (e.g. `ORE_FIELDMAP`), the same
  pattern as `ORE_ENGINE`. Not decided here.
- **No "A1 trade-type registry" artifact exists in this repo to cross-check
  against.** No file under `docs/`, `labels/`, or `semantic-chunks/` mentions
  a trade-type registry, and nothing named A1 was found. Per the task's own
  instruction ("report it, don't reconcile it"), this is reported as an open
  item, not fabricated or skipped. If a registry exists elsewhere, it needs
  to be pointed to explicitly before Step 4/5 of a future join can claim
  agreement with `fromXML()`.

All counts below were computed by parsing the actual JSON files
programmatically (scripts run against `ORE_Forge/data/json/*.json`), not
estimated by inspection.

---

## STEP 1 — Inventory

| file | size | shape | top-level records |
|---|---|---|---|
| `trades_nodes_mapping_all.json` | 17,917 B | object | 49 |
| `component_structures.json` | 6,673 B | object | 32 (31 component defs + 1 special `ArrayFields` sub-dict) |
| `choice_nodes.json` | 656 B | object | 2 |
| `field_definitions.json` | 41,984 B | object | 83 (field names) → 113 (field, context) leaf entries |
| `value_mappings.json` | 7,995 B | object | 23 (heterogeneous — see below) |
| `data_types.json` | 1,995 B | object | 2 (`data_types`, `type_conversion`) — **not read by the join script** |

None of these files has a fixed record schema. `trades_nodes_mapping_all.json`
and `component_structures.json` both encode variable-length ordered lists as
flat `"Level N - Component <i>"` keys, so record key-count varies per record
(e.g. `FX Forward` has 5 Level-2 keys, `FX Digital Barrier Option` has 10).
`value_mappings.json` mixes at least four distinct record *kinds* under one
flat namespace with no discriminator field: enum/lookup tables (`"allowed_values"`
or `"mappings"`), alias tables (`"variations"`), a nested regional table
(`"regions"`), and a rules table (`"rules"`). A consumer must special-case by
key name/shape; nothing marks which kind a given top-level key is.

### Representative examples, verbatim

**`trades_nodes_mapping_all.json`** — key `"Interest Rate Swap"`:
```json
{
  "Instrument Type": "Interest Rate Swap",
  "Trade Type": "Swap",
  "Level 1 - Trade Node": "SwapData{}",
  "Level 2 - Component 1": "LegData{Fixed}",
  "Level 2 - Component 2": "LegData{Floating}"
}
```

**`component_structures.json`** — key `"LegData{#value}"` (the most-shared block):
```json
{
  "Level 3 - Sub Component 1": "LegType=#value",
  "Level 3 - Sub Component 2": "Payer",
  "Level 3 - Sub Component 3": "Currency",
  "Level 3 - Sub Component 4": "PaymentConvention",
  "Level 3 - Sub Component 5": "DayCounter",
  "Level 3 - Sub Component 6": "ScheduleData{Rules}",
  "Level 3 - Sub Component 7": "Notionals{}",
  "Level 3 - Sub Component 8": "LegDataType(#value)"
}
```

**`choice_nodes.json`** — key `"LegDataType(#value)"`:
```json
{
  "description": "Choice node for different types of leg data structures",
  "choices": {
    "Floating": "FloatingLegData{}",
    "Fixed": "FixedLegData{}",
    "Equity": "EquityLegData{}",
    "CMS": "CMSLegData{}",
    "CMSSpread": "CMSSpreadLegData{}",
    "CPI": "CPILegData{}",
    "YY": "YYLegData{}",
    "ZeroCoupon": "ZeroCouponFixed{}",
    "Cashflows": "CashFlows{}"
  }
}
```

**`field_definitions.json`** — key `"Calendar"` (chosen because it has 4
contexts — see Step 2d for why that matters):
```json
{
  "Dates{}": {
    "type": "Field", "mapping_type": "Direct",
    "main_input_file_field": "Calendar",
    "additional_input_file_tab": "", "additional_input_file_field": "",
    "description": "", "default_value": "",
    "data_type": "String", "example_value": "abcde"
  },
  "Rules{}": { "...": "same shape, main_input_file_field: Calendar, default_value: \"\"" },
  "Trade Level Data": {
    "type": "Field", "mapping_type": "Default",
    "main_input_file_field": "", "additional_input_file_tab": "",
    "additional_input_file_field": "", "description": "",
    "default_value": "TARGET", "data_type": "String", "example_value": "TARGET"
  },
  "ValuationSchedule{}": { "...": "same shape as Dates{}" }
}
```

**`value_mappings.json`** — key `"day_count_conventions"`:
```json
{
  "description": "Mapping of input day count conventions to ORE conventions",
  "mappings": {
    "30/360": "30/360",
    "ACT/360": "A360",
    "ACT/365": "A365",
    "ACT/365.FIXED": "A365F",
    "ACT/ACT": "ACT"
  }
}
```

**`data_types.json`** — key `"String?"` under `data_types`:
```json
{
  "description": "Optional string value",
  "example_value": "abcde",
  "default_value": "",
  "validation_pattern": ".*"
}
```

---

## STEP 2 — Join keys, measured

### 2a. `trades_nodes_mapping_all` → `component_structures`, via `"Level 2 - Component N"`

Each trade record's `Level 2 - Component N` values are a DSL: plain field
names, `Name{}` / `Name{Param}` containers, `Name{}[]` container-arrays,
`Name[]` arrays, or `Name=value` field assignments. Containers are the join:
`Name{Param}` resolves against `component_structures["Name{#value}"]`
(parameterised template) first, then plain `"Name"`; `Name{}` resolves
against plain `"Name"`.

- 226 total `Level 2 - Component` entries across 49 trades
- 72 are container-type (candidate joins); 154 are plain fields (no join)
- **71 / 72 resolve**, **1 dangles**: trade `"Credit Default Swaption"` has
  `Level 2 - Component 2: "IndexCreditDefaultSwapData{}"`, and no key named
  `IndexCreditDefaultSwapData` or `IndexCreditDefaultSwapData{#value}` exists
  anywhere in `component_structures.json`. This trade type's mapping is
  incomplete as it stands — it references a block that was never defined.
- Only **11 of 31** component_structures entries are referenced *directly*
  from a trade's Level-2 (see Step 3 for the fan-out per block).

**Many-to-many, with actual row-multiplication risk:** 11 trades reference
the *same* resolved component (`LegData{#value}`) **twice** in one record
(two legs) — `Basis Swap`, `CMS Spread Options`, `Callable Swap`,
`Cross-Currency Swap`, `Equity Index Swap`, `Equity Swap`, `Inflation Swap`,
`Inflation Swap Year-On-Year`, `Interest Rate Swap`, `Interest Rate
Swaption`, `OIS Swap`. A naive join on component name alone (rather than on
component name *and Level-2 slot index*) will silently union the two legs'
fields into one undifferentiated bag, losing which leg is fixed vs floating.

### 2b. Transitive reachability of `component_structures` (through Level-3 nesting + choice resolution)

Following the join recursively (Level-2 container → Level-3 sub-components →
further containers → `choice_nodes` resolution for `Name(#value)` calls):

- **30 / 31** component_structures entries (excl. `ArrayFields`) are reached
  from at least one trade, transitively.
- **1 true orphan, never reachable from any trade even transitively:**
  `ScheduleRules`. (Not to be confused with `Rules`, which *is* reached, via
  the `ScheduleDataType(#value)` choice.)

This matters because a direct-reference-only join (2a) would have wrongly
flagged 20 components as orphaned; 19 of those 20 are real, just reached
through a choice or a second-level container, not directly from a trade.

### 2c. `choice_nodes.json` → `component_structures`

- 2 choice groups, 11 individual `choice_name → target` mappings.
- **11 / 11 resolve.** Zero dangling.
- This is the many-to-one "polymorphic leg" pattern by design: one Level-2
  position (`LegData{Param}`) fans out to 9 mutually-exclusive shapes
  (`Fixed`, `Floating`, `Equity`, `CMS`, `CMSSpread`, `CPI`, `YY`,
  `ZeroCoupon`, `Cashflows`); `ScheduleData{Param}` fans out to 2 (`Rules`,
  `Dates`). A join that doesn't carry the chosen variant as a discriminator
  in the field path will conflate fields that only apply to one variant
  (e.g. `FloatingLegData.FixingDays` vs `FixedLegData.Rates`) under the same
  parent path.

### 2d. Leaf field names (from trades + components) ↔ `field_definitions.json`

Walking every plain field/array leaf reached in 2a/2b gives 85 distinct leaf
field names.

- **73 / 85 resolve** to a `field_definitions.json` key.
- **12 / 85 dangle** (leaf field used in a trade/component, no definition
  exists): `Caps`, `ConversionDates`, `Dates`, `ExerciseDates`, `Floors`,
  `Gearings`, `IndexCreditDefaultSwapData`, `Levels`, `Notionals`, `Rates`,
  `ScheduleData`, `Spreads`. Several of these are plural array-container
  names (`Caps`, `Floors`, `Rates`, `Spreads`, `Gearings`) whose *singular
  item* (`Cap`, `Floor`, `Rate`, `Spread`, `Gearing`) **is** defined in
  `field_definitions.json` — the definitions exist, just keyed one level
  down from where the join needs them.
- **10 / 83** `field_definitions.json` keys are never used as a leaf field
  anywhere in trades/components: `Cap`, `ExerciseDate`, `FirstDate`,
  `Floor`, `Gearing`, `LastDate`, `Level`, `Rate`, `Spread`, `Trade`. These
  are exactly the singular counterparts to the dangling plurals above —
  i.e. **the array-element naming convention is inconsistent between
  `component_structures.json` (defines `ArrayFields.Caps → "Cap"` as the
  element tag) and `field_definitions.json` (keys the definition under the
  plural `Caps`, not singular `Cap`)**, except `field_definitions.json` also
  separately has entries for the singular forms that go unused. Both the
  plural and singular exist for the same concept, defined in different
  files, joined to neither.

**Many-to-one, with a real data-loss risk:** field_definitions.json keys a
field name to a dict of *contexts* (the structural container it appears in),
not a single definition. **20 of 83** field names have more than one context;
**43 of the 85 leaf names** appear at more than one structural *site* across
trades/components. The current join script (`convert_trades.py
_get_field_def_meta`) takes `contexts.items()` and returns on the **first**
one, i.e. whichever context happens to be first in JSON key order — not a
deliberate choice. Concretely, for `Calendar` (4 contexts: `Dates{}`,
`Rules{}`, `Trade Level Data`, `ValuationSchedule{}`), only `Dates{}` survives
today; the `Trade Level Data` context — the one with an actual default value,
`"TARGET"` — is silently discarded, and any trade-level `Calendar` field ends
up with no default at all. A second data-quality issue turned up in the same
scan: `field_definitions.json["IssueDate"]`'s only context is labeled
`YYLegData{}`, but `IssueDate` is only ever used in `Bond`/`BondData` — the
context label itself looks mislabeled in the source data, independent of any
join logic.

### 2e. `value_mappings.json` alias/lookup tables

`value_mappings.json` contains three different *kinds* of table, each
measured separately against `trades_nodes_mapping_all.json` keys:

| table | alias→canonical pairs | resolve | dangle |
|---|---|---|---|
| `trade_type_variations` | 51 | 42 | **9** |
| `regional_variations` | 11 | 11 | 0 |
| `business_unit_variations` | 12 | 12 | 0 |

The 9 dangling `trade_type_variations` pairs collapse to **3 distinct
dangling canonical targets** (each with 3 aliases pointing at it):
`European Swaption` (aliased from `Swaption`, `Swap Option`, `IR Swaption`),
`TRS` (aliased from `Total Return Swap`, `Equity Swap`, `Total Return`), and
`Forward Rate Agreement` (aliased from `FRA`, `Forward Rate`, `Rate
Agreement`) — none of these three target strings exist as a key in
`trades_nodes_mapping_all.json` (the closest real keys are `Interest Rate
Swaption`, `Bond Swap`/nothing named TRS, and `FRA` respectively).

**Worse than a plain dangle — 3 self-conflicting entries:** the *alias* side
of three pairs is itself already a valid, distinct canonical trade key:
- `"Equity Swap"` is both its own canonical key **and** an alias redirecting
  to the (nonexistent) `"TRS"`.
- `"Variance Swap"` is both its own canonical key **and** an alias
  redirecting to `"Volatility Swap"` (which is also its own separate,
  slightly-different canonical key — see the fan-in table in Step 3).
- `"FRA"` is both its own canonical key **and** an alias redirecting to the
  (nonexistent) `"Forward Rate Agreement"`.

A consumer that resolves aliases before checking canonical keys will silently
misroute real trade data for these three names.

Separately, `value_mappings.json` defines 16 enum/lookup tables
(`leg_types`, `day_count_conventions`, `reset_payment_conventions`,
`exercise_styles`, `exercise_types`, `optionality_types`,
`optionality_directions`, `trade_positions`, `cap_floor_types`,
`return_types`, `price_types`, `optionality_features`, `moment_types`,
`frequencies`, `settlement_types`, `barrier_data_types`). Cross-checking
against every `list_values` string actually present in
`field_definitions.json`: **only 7 of 16 are ever referenced by name**
(`day_count_conventions`, `exercise_styles`, `exercise_types`,
`optionality_types`, `optionality_directions`, `reset_payment_conventions`,
`return_types`). The other 9 — including `leg_types`, the table that would
seem most obviously relevant to `LegData` — have **no join key anywhere**
linking them to a specific field. Attaching them to a field would be a
guess, not a join.

---

## STEP 3 — Composition: reference or inline

**(a) Trade records REFERENCE shared block definitions by name; the blocks
live in `component_structures.json`.** Confirmed both by the data (Step
2a/2b) and by the existing join code (`convert_trades.py`'s
`is_component_ref` / `_ensure_component`, which explicitly looks up a
component by name rather than copying its fields inline).

Distinct blocks referenced **directly** from a trade's Level-2, and by how
many trade display-name records:

| block | referenced by |
|---|---|
| `LegData` | 22 |
| `OptionData` | 18 |
| `BarrierData` | 6 |
| `BondData` | 3 |
| `BasketData` | 3 |
| `Underlyings` | 3 |
| `ConvertibleBondData` | 1 |
| `ReferenceSwapData` | 1 |
| `TotalReturnData` | 1 |
| `FundingLegData` | 1 |
| `ConversionData` | 1 |

19 further blocks (`FixedLegData`, `FloatingLegData`, `EquityLegData`,
`CMSLegData`, `CMSSpreadLegData`, `CPILegData`, `YYLegData`,
`ZeroCouponFixed`, `CashFlows`, `Rules`, `Dates`, `Notionals`, `Exchanges`,
`Cashflow`, `Convertibility`, `Underlying`, `Name`, `ValuationSchedule`,
`ScheduleData`) are reached only transitively, one level down, mostly through
the `LegDataType`/`ScheduleDataType` choices — real blocks, just not visible
to a join that only looks at Level-2.

**Naming collision worth flagging on its own:** `Name` is simultaneously a
*component* (`BasketData`'s element, with sub-fields `IssuerId`,
`Qualifier`, `CreditCurveId`) and a *plain field* (the underlying/symbol
name in `Commodity Future`, `Equity Forward`, `Equity Option`, etc.). The
string `"Name"` means two structurally different things depending on where
it's encountered, with no type marker distinguishing them outside of DSL
syntax context (`Name{}[]` vs bare `Name`).

---

## STEP 4 — Attribute completeness

Measured across the 113 `(field, context)` leaf entries in
`field_definitions.json` — this is the finest grain at which the source data
actually carries per-attribute metadata:

| attribute | present | % |
|---|---|---|
| trade type | n/a — attributable via the walk, not stored per-field | — |
| field name | 113 / 113 | 100% (it's the dict key) |
| XML path / nesting | 0 / 113 | **0%** — not stored anywhere as a string; only reconstructable by walking Level 1→2→3 + choice resolution, and that reconstruction is exactly what's unverified (see Risks) |
| data type | 113 / 113 | 100% |
| required vs optional | 0 / 113 explicit | **0%** explicit. `data_types.json` defines the mechanism (type names ending `?` = optional), but **0 of 113** entries actually use a `?`-suffixed `data_type` — every entry is nominally "required" only because the optional variant is never invoked, not because anyone marked it required. Treat this column as *unknown*, not *required=true*. |
| description | 36 / 113 | 32% |
| default_value | 12 / 113 | 11% |
| enumerated allowed values (`list_values`) | 8 / 113 | 7% |
| source column (`main_input_file_field`) | 88 / 113 | 78% |
| verified-vs-guessed marker | 0 / 113 | **0%** — no such field exists anywhere in any of the 6 files (grepped `verified\|guessed\|confidence\|reviewed` across all of `data/json/`: zero hits) |

`mapping_type` distribution (a proxy for how directly each value maps to a
source column, not asked for explicitly but relevant to trust): Direct 73%,
Function (derived/computed) 12%, Default (hardcoded, no source column) 10%,
Choice 4%, Combination 1%.

---

## PROPOSED JOIN SPEC

### Prose

1. Load `trades_nodes_mapping_all.json`, `component_structures.json`,
   `choice_nodes.json`, `field_definitions.json`. Load `value_mappings.json`
   only for the 7 enum tables that are actually named via `list_values`
   (Step 2e); the other 9 tables and all 3 alias sub-tables are *not*
   auto-joined (see below). `data_types.json` is loaded only as a static
   lookup to interpret the `?`-suffix optionality convention — it is not
   keyed against anything else, so there's nothing to join it on.
2. For each trade record, walk its `Level 2 - Component N` specs in numeric
   order, recursing into `component_structures` for every container, and
   into `choice_nodes` for every choice call, exactly as `convert_trades.py`
   already does — except:
   - carry the **Level-2 slot index** through recursion so that two
     instances of the same component (e.g. two `LegData` legs) stay
     distinguishable in the output path, instead of colliding (2a).
   - carry the **chosen choice variant name** through the path when
     recursing through a `choice_nodes` resolution, so fields that only
     apply to one variant aren't conflated with another (2c).
   - when a container reference dangles (2a: 1 case) or a leaf field has no
     `field_definitions` entry (2d: 12 cases), **emit an unresolved record**
     rather than dropping the field silently. The whole point of profiling
     first was to make loss visible.
3. For every leaf field, resolve its `field_definitions` context by
   *structural match* first (the immediate container name, e.g. `"Rules{}"`
   when inside `ScheduleData{Rules}`), then `"Trade Level Data"`, then
   whatever context is first in the file — in that priority order, not
   insertion order as today's script does. This fixes the `Calendar`
   data-loss case in 2d without needing new source data.
4. `required` is derived from whether the chosen context's `data_type` ends
   in `?`. Since that's 0/113 today, this will emit `required=None`
   (unknown) for everything until someone actually marks fields optional in
   the source data — do not default it to `True`.
5. Attach a `value_set` only when the field's context explicitly names one
   of the 7 verified `value_mappings` tables via `list_values`. Do not
   attach any of the other 9 tables, and do not resolve
   `trade_type_variations`/`regional_variations`/`business_unit_variations`
   automatically — flag the 3 dangling targets and 3 self-conflicting
   aliases (2e) for a human to resolve first.
6. Emit one canonical record per resolved leaf:
   `(trade_type, field_path, required, type, source_file, source_record_id)`.
   `trade_type` = the record's `"Trade Type"` value (not the display name —
   but see Risks: 49 display names collapse to 33 Trade Types, 7 of which
   have genuinely different field sets, so `trade_type` alone is not a safe
   grouping key without also carrying the display name or an equivalent
   discriminator). `field_path` = `/` joined path built in step 2.
   `source_file`/`source_record_id` track **where the type/required
   metadata came from** (`field_definitions.json` + `field@context`), which
   is a different provenance question than where the *path* came from
   (`trades_nodes_mapping_all.json` + `component_structures.json` +
   `choice_nodes.json`, composed across up to 4 files for one path) — see
   Risks for why a single source_file/source_record_id pair is a
   simplification.

### Pseudocode

```
def build_canonical_records():
    trades      = load(trades_nodes_mapping_all.json)
    components  = load(component_structures.json)
    choices     = load(choice_nodes.json)
    field_defs  = load(field_definitions.json)
    value_sets  = { name: load(value_mappings.json)[name]
                    for name in VERIFIED_LIST_VALUE_TABLES }  # the 7, not 16

    records, unresolved = [], []

    for display_name, cfg in trades.items():
        trade_type = cfg["Trade Type"]
        xml_node   = base_name(cfg["Level 1 - Trade Node"])
        for slot_index, spec in ordered(cfg, "Level 2 - Component"):
            walk(spec, path=[xml_node], slot_index, trade_type, display_name,
                 records, unresolved, components, choices, field_defs)

    return records, unresolved


def walk(spec, path, slot_index, trade_type, display_name,
         records, unresolved, components, choices, field_defs):
    parsed = parse_spec(spec)   # field | array | container | container_array | choice_call

    if parsed.type in ("field",):
        emit_leaf(parsed.base_name, path, trade_type, display_name, records, field_defs)

    elif parsed.type == "array":
        item_tag = array_item_tag(parsed.base_name, components)   # ArrayFields lookup
        emit_leaf(parsed.base_name, path + [item_tag, "*"], trade_type, display_name, records, field_defs)

    elif parsed.type in ("container", "container_array"):
        target = resolve_component(parsed, components)   # tries "Name{#value}" then "Name"
        if target is None:
            unresolved.append((trade_type, display_name, path, spec))
            return
        # slot_index disambiguates repeated components (2 legs, etc.)
        new_path = path + [f"{parsed.base_name}[{slot_index}]"]
        for sub_spec in ordered(components[target], "Level 3 - Sub Component"):
            walk(sub_spec, new_path, slot_index, trade_type, display_name,
                 records, unresolved, components, choices, field_defs)

    elif parsed.type == "choice_call":
        choice_def = choices.get(f"{parsed.base_name}(#value)")
        if choice_def is None:
            unresolved.append((trade_type, display_name, path, spec))
            return
        for variant_name, variant_target in choice_def["choices"].items():
            target = strip_braces(variant_target)
            if target not in components:
                unresolved.append((trade_type, display_name, path, f"{spec} -> {variant_target}"))
                continue
            variant_path = path + [f"{parsed.base_name}={variant_name}"]
            for sub_spec in ordered(components[target], "Level 3 - Sub Component"):
                walk(sub_spec, variant_path, slot_index, trade_type, display_name,
                     records, unresolved, components, choices, field_defs)


def emit_leaf(field_name, path, trade_type, display_name, records, field_defs):
    contexts = field_defs.get(field_name, {})
    ctx_key, meta = choose_context(contexts, path)   # structural match -> "Trade Level Data" -> first
    if meta is None:
        records.append(CanonicalRecord(
            trade_type=trade_type, field_path=join(path, field_name),
            required=None, type="UNVERIFIED",
            source_file="trades_nodes_mapping_all.json / component_structures.json",
            source_record_id=f"{display_name}:{field_name}",
        ))
        return
    data_type = meta.get("data_type", "")
    records.append(CanonicalRecord(
        trade_type=trade_type, field_path=join(path, field_name),
        required=(None if not data_type else not data_type.endswith("?")),
        type=data_type or "UNVERIFIED",
        source_file="field_definitions.json",
        source_record_id=f"{field_name}@{ctx_key}",
    ))
```

---

## RISKS

1. **The `fieldmap/` name doesn't refer to anything that exists.** This
   entire profile is built on a substitution (`ORE_Forge/data/json/`) that
   the user confirmed verbally, not something discoverable from this repo.
   If that's wrong, everything downstream is profiling the wrong data.
2. **No A1 trade-type registry was found to cross-check against**, so the
   constraint "if a trade type is present in one and absent from the other,
   report it" could not be executed — there was nothing to compare to. This
   needs to be pointed to explicitly (a file, a path, or `fromXML()`'s
   actual dispatch table in the ORE C++ source under `ORE_ENGINE`) before
   that check can run.
3. **`ORE_Forge/data/json/` is documented as "legacy fallback"** by that
   project's own mapping guide, not the layer its README calls canonical.
   It is still the only layer that's normalized-and-needs-a-join (the
   "primary" layer is already merged), but it's worth knowing this join
   spec targets data the source project itself is trying to move away from.
4. **1 dangling component reference** (`Credit Default Swaption` →
   `IndexCreditDefaultSwapData{}`, Step 2a) means that trade type cannot
   produce a complete canonical record set no matter how the join is
   written — the source data is missing a definition, not just
   under-linked.
5. **The `Calendar` field-loss case (Step 2d) is not hypothetical** — it's
   the exact bug the proposed join spec's step 3 is designed to fix, and a
   concrete instance of "picking a join order matters" that the naive
   first-context approach gets wrong today, silently, with no error.
6. **`IssueDate`'s only field_definitions context is labeled
   `YYLegData{}`** even though `IssueDate` is only used on `Bond`/`BondData`
   — this looks like a labeling mistake in the source data itself, not a
   cross-file join ambiguity. A structural-match join (proposed step 3)
   would fail to find a match for `IssueDate` under `BondData{}` and fall
   through to "Trade Level Data" or "first available" — i.e. it would use
   the mislabeled context anyway, just via a different fallback path. This
   can't be fixed by the join; it needs a source-data correction upstream.
7. **9 of 16 `value_mappings.json` enum tables have no join key at all**
   (Step 2e), including `leg_types`, which intuitively should attach to
   `LegData`/`LegDataType` but doesn't via any string anyone can point to.
   Attaching it would be inference, which the task explicitly asked to
   avoid ("evidence, not inference").
8. **3 self-conflicting trade-type aliases** (`Equity Swap`, `Variance
   Swap`, `FRA` — Step 2e) actively contradict themselves: each is both a
   valid canonical key and an alias pointing somewhere else (in 2 of 3
   cases, somewhere that doesn't exist). Any alias-resolution step run
   before a canonical-key lookup will misroute these three.
9. **49 display-name trade records collapse to 33 distinct `Trade Type`
   values, and 7 of those 33 have members with genuinely different field
   lists** (Step 3's `by_trade_type` table — e.g. `CapFloor` covers `Cap
   Trade`, `Floor Trade`, `Collar`, `CMS Cap`, `CMS Floor`, each with a
   different subset of `Caps[]`/`Floors[]`/leg type). The canonical record
   shape the task specifies keys on `trade_type` — using `Trade Type` alone
   as that key will silently union incompatible field sets for these 7
   groups unless the display name (or equivalent) rides along as a second
   key. 3 other Trade Type groups (`EquityOption`, `EquitySwap`,
   `EquityVarianceSwap`) have members with *identical* field lists — safe
   to collapse, and worth distinguishing from the unsafe 7 rather than
   treating "has more than one display name" as uniformly risky.
10. **`data_types.json` is not read by the existing join at all** — it's
    consumed by a separate legacy XML-generation path
    (`scripts/xpath/xml_generator.py`, `xpath_lib.py`), not by
    `convert_trades.py`. Its optionality convention (`String?` etc.) is
    exactly what Step 4's "required vs optional" column would need, but
    nothing in the trade/component/field-definition graph currently uses
    it — it's a live file, just not on this join's path today.
11. **`source_file`/`source_record_id` as single scalar fields is a
    simplification.** A canonical record's `field_path` is typically
    composed across 3-4 files (trade + one or more components + possibly a
    choice), while its `type`/`required` come from a single
    `field_definitions.json` entry. The proposed spec tracks provenance for
    the latter only; if full path provenance is needed later, the schema
    will need to grow beyond one source_file/source_record_id pair.
