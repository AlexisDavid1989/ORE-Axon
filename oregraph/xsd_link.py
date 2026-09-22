"""Link XSD schema definitions to the C++ classes that implement their fromXML().

Why this exists
----------------
OREXsd (a semantic chunk built by LLM extraction over Engine/xsd/*.xsd) and
OREData (an AST chunk covering Engine/OREData, where every trade type's
fromXML()/toXML() actually lives) both land in the merged graph, but nothing
connects them - link.py only resolves C++ #include directives and
symbol_links.py only recovers C++ symbol usage, so an XSD element and the
class that parses it are disconnected islands even though a human reading
the code immediately sees the relationship (e.g. instruments.xsd's `legData`
complexType and OREData's `LegData` class are obviously "the same thing").

Two independent strategies, run as separate passes
----------------------------------------------------
1. **Name matching** (`_legacy_class_name_pass`): match an xsd complexType/
   simpleType/element's literal name straight against OREData class names.
   A heuristic - nothing in either XSD or C++ explicitly declares "this
   class implements this schema element" this way, so confidence is scored
   lower and a name that matches more than one class is left unmatched
   rather than guessed at (see LINK_CONFIDENCE). Scoped to instruments.xsd:
   conventions.xsd, curveconfig.xsd etc. have far more paraphrased,
   non-literal LLM labels and would need their own matching strategy (see
   pass 2).
2. **Dispatch-table matching** (`_authoritative_pass`, run once each for
   instruments.xsd against databuilders.cpp's `ORE_REGISTER_TRADE_BUILDER`
   table, conventions.xsd against conventions.cpp's `type == "X"` chain, and
   referencedata.xsd against databuilders.cpp's `ORE_REGISTER_REFERENCE_DATUM`
   table): several of ORE's xsd files declare a literal,
   complete enumeration mapping every concrete XML element name to its
   shared structural type - e.g. instruments.xsd's `oreTradeData` group has
   one `<xs:element type="eqBarrierOptionData" name="EquityBarrierOptionData"/>`
   line per trade type, and OREData's `databuilders.cpp` has one
   `ORE_REGISTER_TRADE_BUILDER("EquityBarrierOption", EquityBarrierOption, ...)`
   line per registered class. Both are literal ground truth, not
   extraction - joining them on the shared name (`EquityBarrierOptionData`
   minus `Data` == the registered TradeType string) needs no guessing and
   produces exact many-to-one edges (several asset-class variants sharing
   one complexType, e.g. `eqBarrierOptionData` shared by
   EquityBarrierOption/EquityDoubleBarrierOption/EquityEuropeanBarrierOption)
   that pass 1's one-name-one-class matching structurally cannot represent.
   This pass reads the two source files directly rather than going through
   the semantic-chunk graph nodes, because the graph's LLM-summarized
   OREXsd nodes are known to be incomplete for exactly this repeated
   "type X aliased under many names" declaration shape (spot-checked: none
   of instruments.xsd's ~180 oreTradeData element aliases got their own
   graph node, only the complexTypes they point at did).

Both strategies only add an edge where they can point at a real graph node on
each side; anything that doesn't resolve is reported, not guessed at.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

#: "name (complexType)", "name (top-level complexType)", "name (element, ...)"
#: or the parenthesis-free "name complexType" - the two label shapes actually
#: observed in semantic-chunks/xsd/*.json for instruments.xsd nodes.
_TYPE_LABEL_RE = re.compile(
    r"^([A-Za-z][\w]*)\s*(?:\((?:top-level )?(?:complexType|simpleType|element)|"
    r"(?:complexType|simpleType|element)\b)")

LINK_CONFIDENCE = "MATCHED"
LINK_CONFIDENCE_SCORE = 0.85
#: pass 2 joins two literal, authoritative source files (an xsd's own
#: dispatch enumeration and a C++ registration table) rather than guessing
#: from an xsd type's name alone, so it earns a higher score.
AUTHORITATIVE_CONFIDENCE_SCORE = 0.95
AUTHORITATIVE_CONFIDENCE_SCORE_NORMALIZED = 0.9


def _extract_type_names(nodes: list[dict], source_file: str) -> dict[str, str]:
    """xsd node id -> literal type/element name, for nodes from *source_file*."""
    names: dict[str, str] = {}
    for n in nodes:
        if n.get("repo") != "OREXsd":
            continue
        if n.get("source_file") != source_file:
            continue
        m = _TYPE_LABEL_RE.match(n.get("label", ""))
        if m:
            names[n["id"]] = m.group(1)
    return names


def _index_ore_classes(nodes: list[dict]) -> dict[str, list[dict]]:
    """lowercased class name -> OREData class/struct nodes with a real source file.

    Excludes nodes with no source_file: the AST extractor emits a stub node
    for every *reference* to a type (a forward declaration, a member of that
    type, a template argument) in whichever file mentions it, not just its
    definition - e.g. "LegData" appears 40+ times across OREData, almost all
    with source_file "". Only a node that carries real source info is a
    plausible definition site.
    """
    by_name: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        if n.get("repo") != "OREData":
            continue
        if not n.get("_callable_class"):
            continue
        if not n.get("source_file"):
            continue
        by_name[n.get("label", "").lower()].append(n)
    return by_name


def _file_stem(node: dict) -> str:
    sf = str(node["source_file"]).replace("\\", "/").rsplit("/", 1)[-1]
    return sf.rsplit(".", 1)[0].lower()


def _resolve_one(name: str, by_name: dict[str, list[dict]]) -> dict | None:
    """A single candidate name -> its OREData node, or None (no match / ambiguous
    with no tie-break). Ambiguity is broken by preferring the candidate whose
    source file stem equals the name - the file a class's own definition
    lives in is overwhelmingly likely to be named after the class itself."""
    candidates = by_name.get(name.lower(), [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        exact_file = [c for c in candidates if _file_stem(c) == name.lower()]
        if len(exact_file) == 1:
            return exact_file[0]
    return None


def _resolve(name: str, by_name: dict[str, list[dict]]) -> tuple[dict, str] | tuple[None, None]:
    """Try the literal name, then - for XSD's ubiquitous <Class>Data element-
    wrapper convention (e.g. `swapData` naming OREData's `Swap` class, not a
    class called "SwapData") - the name with a trailing "Data" stripped."""
    node = _resolve_one(name, by_name)
    if node is not None:
        return node, name
    if name.lower().endswith("data") and len(name) > 4:
        stripped = name[:-4]
        node = _resolve_one(stripped, by_name)
        if node is not None:
            return node, stripped
    return None, None


def _normalize(s: str) -> str:
    """Case/punctuation-insensitive key, for matching a dispatch string
    against a registration string that differ only in underscores/case -
    e.g. xsd element `Autocallable01Data` (-> candidate "Autocallable01")
    against databuilders.cpp's registered TradeType string "Autocallable_01"."""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _slugify_xsd_name(name: str) -> str:
    """camelCase/PascalCase xsd type name -> the snake_case suffix the
    semantic-chunk builder used for this node's id (e.g. "eqBarrierOptionData"
    -> "eq_barrier_option_data", "averageOISType" -> "average_ois_type") -
    reverse-engineered empirically from real node ids across multiple xsd
    files. A handful of ids also drop a disambiguating trailing digit the
    type name keeps (e.g. "worstOfBasketSwapData2" -> id suffix
    "...swap_data", no "2") - see `_lookup_xsd_node`."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", s)
    return s.lower()


def _xsd_node_index(nodes: list[dict], source_file: str) -> dict[str, str]:
    """slug(type-name suffix of node id) -> node id, for every OREXsd node
    from *source_file*. Keyed off the node id (always a slugified literal
    type name) rather than the label, so it works even where labels are
    paraphrased prose (conventions.xsd) instead of the literal
    "name (complexType)" shape instruments.xsd happens to use."""
    stem = source_file.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    prefix = f"OREXsd::xsd_{stem}_"
    index: dict[str, str] = {}
    for n in nodes:
        if n.get("repo") != "OREXsd" or n.get("source_file") != source_file:
            continue
        nid = n["id"]
        if nid.startswith(prefix):
            index[nid[len(prefix):]] = nid
    return index


def _lookup_xsd_node(index: dict[str, str], type_name: str) -> str | None:
    slug = _slugify_xsd_name(type_name)
    if slug in index:
        return index[slug]
    if slug and slug[-1].isdigit() and slug[:-1] in index:
        return index[slug[:-1]]
    return None


def _parse_dispatch_block(xsd_text: str, container_name: str) -> dict[str, str]:
    """element `name` -> `type` for every self-closing <xs:element .../> in
    the named top-level xs:group/xs:complexType's dispatch block (e.g.
    instruments.xsd's `oreTradeData` group, conventions.xsd's `conventions`
    complexType) - a literal, complete enumeration of every concrete element
    name and the shared structural type it aliases."""
    start = re.search(rf'<xs:(?:group|complexType)\s+name="{re.escape(container_name)}"',
                       xsd_text)
    if not start:
        return {}
    end = re.search(r"</xs:(?:group|complexType)>", xsd_text[start.end():])
    block = xsd_text[start.end(): start.end() + end.start()] if end else xsd_text[start.end():]
    return {em.group(2): em.group(1)
            for em in re.finditer(r'<xs:element\s+type="(\w+)"\s+name="(\w+)"', block)}


def _parse_trade_builder_registrations(cpp_text: str) -> dict[str, str]:
    """TradeType string -> registered C++ class name, from
    `ORE_REGISTER_TRADE_BUILDER("Type", ClassName, ...)` calls in
    databuilders.cpp - the literal table ORE's own TradeFactory dispatches
    on, so it is ground truth for "which class parses this TradeType",
    same discipline the ORE_Forge trade-mapping audit relies on."""
    return dict(re.findall(
        r'ORE_REGISTER_TRADE_BUILDER\(\s*"([^"]+)"\s*,\s*(\w+)\s*,', cpp_text))


def _parse_convention_dispatch(cpp_text: str) -> dict[str, str]:
    """dispatch-string -> class name, from conventions.cpp's
    `if (type == "X") { ... = make_shared<ClassName>` / `else if (...)`
    chain - Convention's own runtime dispatch, parsed the same way
    databuilders.cpp's macro table is."""
    return dict(re.findall(
        r'type\s*==\s*"([^"]+)"\)\s*\{\s*\w[\w:]*\s*=\s*'
        r'(?:QuantLib::ext::)?make_shared<(\w+)>', cpp_text))


def _parse_reference_datum_registrations(cpp_text: str) -> dict[str, str]:
    """ReferenceDatum type string -> registered C++ class name, from
    `ORE_REGISTER_REFERENCE_DATUM("Type", ClassName, ...)` calls in
    databuilders.cpp - `ReferenceDatumFactory`'s own registration table,
    the same discipline `_parse_trade_builder_registrations` already gets
    for `TradeFactory`."""
    return dict(re.findall(
        r'ORE_REGISTER_REFERENCE_DATUM\(\s*"([^"]+)"\s*,\s*([A-Za-z_:]+)\s*,', cpp_text))


def _legacy_class_name_pass(nodes: list[dict], by_name: dict[str, list[dict]]) -> tuple[list[dict], dict]:
    """Pass 1: literal xsd type name vs. OREData class name, instruments.xsd only."""
    xsd_names = _extract_type_names(nodes, "xsd/instruments.xsd")
    edges: list[dict] = []
    matched_via_stem = 0
    unmatched: list[str] = []
    for xsd_id, name in sorted(xsd_names.items()):
        node, used_name = _resolve(name, by_name)
        if node is None:
            unmatched.append(name)
            continue
        if used_name != name:
            matched_via_stem += 1
        edges.append({
            "source": node["id"],
            "target": xsd_id,
            "relation": "implements",
            "context": "xsd_class_name_match",
            "confidence": LINK_CONFIDENCE,
            "confidence_score": LINK_CONFIDENCE_SCORE,
            "weight": 1.0,
            "source_file": node.get("source_file"),
            "_origin": "xsd_link",
        })
    stats = {
        "instruments_xsd_type_names": len(xsd_names),
        "matched_exact": len(edges) - matched_via_stem,
        "matched_via_stripped_data_suffix": matched_via_stem,
        "unmatched": len(unmatched),
        "unmatched_names": sorted(unmatched),
    }
    return edges, stats


def _authoritative_pass(nodes: list[dict], by_name: dict[str, list[dict]],
                         *, xsd_path: Path, container_name: str, xsd_source_file: str,
                         cpp_path: Path, cpp_parser, strip_suffixes: tuple[str, ...] | None,
                         context_label: str) -> tuple[list[dict], dict]:
    """Join an xsd's literal element-name dispatch enumeration against a C++
    dispatch table (registration macro or if/else chain), both parsed from
    their real source files. See module docstring for why this exists
    alongside (not instead of) the name-guessing pass.

    *strip_suffixes*: candidate dispatch strings are the element name minus
    each of these trailing suffixes, in order, longest/most-specific first -
    trades use `<TradeType>Data` (`("Data",)`); reference data mostly uses
    `<Type>ReferenceData` but one entry (`BondBasketData`) only has the bare
    `Data` suffix, so both are tried (`("ReferenceData", "Data")`) and the
    first that resolves wins, so a genuine `...ReferenceData` entry is never
    mismatched against the shorter suffix by trying it first. Conventions'
    dispatch elements (`Zero`, `CDS`, ...) already equal the dispatch string
    with nothing to strip (pass None)."""
    stats = {"attempted": 0, "matched_exact": 0, "matched_normalized": 0,
             "unmatched_names": []}
    if not xsd_path.exists() or not cpp_path.exists():
        stats["error"] = f"missing source file: {xsd_path if not xsd_path.exists() else cpp_path}"
        return [], stats

    dispatch = _parse_dispatch_block(xsd_path.read_text(encoding="utf-8"), container_name)
    registrations = cpp_parser(cpp_path.read_text(encoding="utf-8"))
    norm_registrations: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for dispatch_string, cls in registrations.items():
        norm_registrations[_normalize(dispatch_string)].append((dispatch_string, cls))
    xsd_index = _xsd_node_index(nodes, xsd_source_file)

    edges: list[dict] = []
    for elem_name, type_name in sorted(dispatch.items()):
        if strip_suffixes:
            candidates = [elem_name[: -len(suffix)] for suffix in strip_suffixes
                         if elem_name.endswith(suffix)]
        else:
            candidates = [elem_name]
        if not candidates:
            continue
        stats["attempted"] += 1

        xsd_id = _lookup_xsd_node(xsd_index, type_name)
        if xsd_id is None:
            stats["unmatched_names"].append(elem_name)
            continue

        cls_name = None
        score = AUTHORITATIVE_CONFIDENCE_SCORE
        via_normalized = False
        for candidate in candidates:
            cls_name = registrations.get(candidate)
            if cls_name is not None:
                break
        if cls_name is None:
            for candidate in candidates:
                hits = norm_registrations.get(_normalize(candidate), [])
                if len(hits) == 1:
                    cls_name = hits[0][1]
                    via_normalized = True
                    score = AUTHORITATIVE_CONFIDENCE_SCORE_NORMALIZED
                    break
        if cls_name is None:
            stats["unmatched_names"].append(elem_name)
            continue

        class_node = _resolve_one(cls_name, by_name)
        if class_node is None:
            stats["unmatched_names"].append(elem_name)
            continue

        edges.append({
            "source": class_node["id"],
            "target": xsd_id,
            "relation": "implements",
            "context": context_label + ("_normalized" if via_normalized else ""),
            "confidence": LINK_CONFIDENCE,
            "confidence_score": score,
            "weight": 1.0,
            "source_file": class_node.get("source_file"),
            "_origin": "xsd_link",
        })
        if via_normalized:
            stats["matched_normalized"] += 1
        else:
            stats["matched_exact"] += 1

    stats["unmatched_names"].sort()
    return edges, stats


def link_xsd(nodes: list[dict], engine_root: Path | None = None) -> tuple[list[dict], dict]:
    """Return (edges, stats). *nodes* is the fully namespaced merged node list
    (post-merge.py-namespacing, same convention as symbol_links.link_symbols) -
    ids on returned edges are ready to use as-is, no remapping needed.
    *engine_root* is the Engine checkout root; pass 2/3 (dispatch-table
    matching) are skipped without it, since they read xsd/C++ source files
    directly rather than going through the graph."""
    by_name = _index_ore_classes(nodes)

    legacy_edges, legacy_stats = _legacy_class_name_pass(nodes, by_name)

    trade_edges: list[dict] = []
    trade_stats: dict = {"skipped": "no engine_root"}
    convention_edges: list[dict] = []
    convention_stats: dict = {"skipped": "no engine_root"}
    refdata_edges: list[dict] = []
    refdata_stats: dict = {"skipped": "no engine_root"}

    if engine_root is not None:
        trade_edges, trade_stats = _authoritative_pass(
            nodes, by_name,
            xsd_path=engine_root / "xsd" / "instruments.xsd",
            container_name="oreTradeData",
            xsd_source_file="xsd/instruments.xsd",
            cpp_path=engine_root / "OREData" / "ored" / "utilities" / "databuilders.cpp",
            cpp_parser=_parse_trade_builder_registrations,
            strip_suffixes=("Data",),
            context_label="xsd_tradedata_registration_match",
        )
        convention_edges, convention_stats = _authoritative_pass(
            nodes, by_name,
            xsd_path=engine_root / "xsd" / "conventions.xsd",
            container_name="conventions",
            xsd_source_file="xsd/conventions.xsd",
            cpp_path=engine_root / "OREData" / "ored" / "configuration" / "conventions.cpp",
            cpp_parser=_parse_convention_dispatch,
            strip_suffixes=None,
            context_label="xsd_convention_dispatch_match",
        )
        # referencedata.xsd's `referenceDataTypes` group is the same shape as
        # instruments.xsd's `oreTradeData` (a literal element->type dispatch
        # enumeration), and `ReferenceDatumFactory` is registered the same way
        # `TradeFactory` is (`ORE_REGISTER_REFERENCE_DATUM` in the same
        # databuilders.cpp) - the difference is the suffix the element name
        # wraps the registered string in: almost always "ReferenceData" (e.g.
        # element `BondReferenceData` -> registered string "Bond"), but one
        # entry (`BondBasketData`) only has the bare "Data" suffix - both are
        # tried, longest first, so a genuine "...ReferenceData" entry is never
        # mismatched against the shorter suffix.
        refdata_edges, refdata_stats = _authoritative_pass(
            nodes, by_name,
            xsd_path=engine_root / "xsd" / "referencedata.xsd",
            container_name="referenceDataTypes",
            xsd_source_file="xsd/referencedata.xsd",
            cpp_path=engine_root / "OREData" / "ored" / "utilities" / "databuilders.cpp",
            cpp_parser=_parse_reference_datum_registrations,
            strip_suffixes=("ReferenceData", "Data"),
            context_label="xsd_referencedata_registration_match",
        )

    # Merge all four passes, de-duplicating (source, target) pairs - a
    # name can legitimately resolve through more than one pass (e.g. the
    # legacy pass already gets `Swap` from complexType `swapData` directly;
    # pass 2 would add the same edge again via element `SwapData`).
    edges: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for edge in legacy_edges + trade_edges + convention_edges + refdata_edges:
        key = (edge["source"], edge["target"])
        if key in seen:
            continue
        seen.add(key)
        edges.append(edge)
    edges.sort(key=lambda e: (e["source"], e["target"]))

    stats = {
        **legacy_stats,
        "xsd_edges": len(edges),
        "trade_dispatch": trade_stats,
        "convention_dispatch": convention_stats,
        "reference_data_dispatch": refdata_stats,
    }
    return edges, stats
