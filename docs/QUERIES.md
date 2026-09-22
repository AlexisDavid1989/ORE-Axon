# Querying the graph

`oregraph query-*` answers questions from the merged graph directly, no MCP
client required - the same render path `oregraph mcp` exposes to Claude Code.

```bash
python -m oregraph query-symbol "FdDefaultableEquityJumpDiffusionConvertibleBondEngine" --limit 40
python -m oregraph query-flow ConvertibleBond --max-hops 4 --per-category 3
python -m oregraph query-path "ConvertibleBond::build" ConvertibleBond2
python -m oregraph query-batch ConvertibleBond ConvertibleBond2 --limit 40
python -m oregraph query-impact ConvertibleBond2 --limit 40
python -m oregraph query-example EquityOption --depth 2 --limit 80
python -m oregraph query-fields FxForward --limit 40
python -m oregraph query-fields BermudanSwaption --xpath EngineParameters
python -m oregraph query "What builds ConvertibleBond?" --mode bfs --depth 2
```

- `query-symbol` - a ranked exact-symbol neighborhood (all incoming/outgoing
  edges for one name).
- `query-flow` - discover concrete pricing/build endpoints from a trade
  symbol without guessing their names.
- `query-path` - a compact, relation-ranked corridor between two or more
  known symbols.
- `query-batch` - several exact symbols with one graph load.
- `query-impact` - direct callers, callees, and typed dependencies (blast
  radius).
- `query-example` - a categorized source bundle around an existing analogue,
  for "show me how a similar type is implemented" before writing new code.
- `query-fields` - ORE_Forge's field mapping for an entry (a trade type, curve
  config, convention or pricing-engine product), named by entry, TradeType, XML
  node or class: its fields with required/optional, data type and value set,
  the XSD type that validates it and the C++ class that parses it, each link
  with its confidence and how it was established. Needs the opt-in fieldmap
  (README, "Field mapping"); `--xpath TEXT` filters the fields, and a pricing
  product lists one field set per Model/Engine pair. Fields are not nodes, so
  this - not `query` - is how to look one up.
- `query` - free-text BFS/DFS over the graph, same engine as the MCP server.

All of these need a real symbol as the entry point - `"portfolio/swap.hpp"`
finds nothing, `"TradeFactory"` works. Start from a class or function name,
not a path. See README.md's "What it answers well, and what it doesn't" for
the current gaps (documentation-to-code questions are unfounded; DFS on
broad questions returns thousands of loosely related nodes).

## Limitations

**The XSD layer validates structure only, and is known incomplete.** XSD
nodes (`OREXsd`, built from `xsd/*.xsd`) are linked to the OREData/
OREAnalytics classes that implement them (`implements`/`schema_for` edges -
see `oregraph/xsd_link.py` and `oregraph/link_schema.py`), so a query *can*
traverse from a schema type to its implementing class. But the schema itself
is not the authority on what ORE accepts: it is missing coverage for real,
buildable TradeTypes entirely, and at least one case
(`CommoditySwap`/`SwapData` vs. the schema's `CommoditySwapData`) has the
schema naming the wrong XML element outright. See `docs/XSD-DRIFT.md` for
the full measured gap, regenerated on every `oregraph merge`.

**`fromXML()` in the C++ is authoritative for what a trade type actually
accepts.** If the question is "what fields does this type take, and which
are required", read the implementing class's `fromXML()` - do not infer it
from the XSD. `docs/XSD-DRIFT.md`'s field-level section shows this isn't
theoretical: even among a small sample of trade types, the code reads fields
the schema doesn't declare, ignores fields the schema does declare, and in
one case looks for an entirely different element name than the schema
specifies.
