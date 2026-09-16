"""Link XSD schema types to the C++ classes that implement them, and measure
where the schema falls short of the code - in both directions.

Why this exists
----------------
ORE's XSDs validate XML *structure* only. The authority on what ORE actually
accepts for a given trade or config type is the C++ `fromXML()` implementation,
not the schema - the schema is known to be incomplete (see docs/XSD-DRIFT.md).
This module does two jobs, deliberately kept together because they share the
same join key:

1. Link OREXsd (a semantic chunk built by LLM extraction over `Engine/xsd/*.xsd`,
   a curated subset, not an exhaustive parse) to OREData/OREAnalytics classes,
   with a `schema_for` relation distinct from `references`/`includes` so a
   query can tell "this XML shape is validated by this schema type" apart from
   an ordinary C++ dependency.
2. Measure the gap: XSD types nothing implements, and - the actionable
   direction - trade types ORE will happily build that the schema cannot
   validate at all.

Two ground-truth extractions feed the join, both read straight from the
Engine source tree (never from `semantic-chunks/`, which is an LLM's curated
opinion of what's interesting, not a census):

- `build_trade_registry`: every TradeType string ORE's TradeFactory will
  actually build, from `OREData/ored/portfolio/*.{hpp,cpp}` and
  `.../utilities/databuilders.cpp` (see that function's docstring for why
  both are needed - a naive scan of portfolio/ alone cannot tell a real,
  independently-buildable trade type from an abstract intermediate class that
  only exists to share code between several real ones).
- `extract_xsd_types`: every `xs:complexType`/`xs:simpleType`/`xs:element`
  name declared anywhere in `xsd/*.xsd`, parsed directly - independent of
  which of those the semantic chunk happened to extract a node for.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from .chunks import Chunk

#: Relation used for every edge this module produces. Never "references" or
#: "includes" - those are C++ dependency relations; this is a schema-to-
#: implementation link, and a query needs to be able to tell them apart.
SCHEMA_FOR = "schema_for"

#: Recorded baseline for verify.py's "schema links not regressed" check -
#: the schema_for edge count from the run this module was landed with
#: (2026-09, against the ORE Engine checkout current at the time). Update
#: this deliberately when a corpus change or a genuine improvement to the
#: join moves the count, the same way labels/*.anchors.json gets re-pinned -
#: never let it drift silently just to make a warning go away. Dropped from
#: 268 to 261 across two fixes (see link_schema()'s Tier 2/3 guards): a
#: registry-trade-class collision guard (conventions.xsd/ore_types.xsd short
#: names colliding with unrelated trade class names) and a conventions.xsd
#: dispatch-alternative guard (short convention tags colliding with other,
#: non-trade classes) - both confirmed wrong on inspection, not guessed at.
SCHEMA_LINKS_BASELINE = 261


# ---------------------------------------------------------------------------
# A1: the trade-type registry - the join key, built from source
# ---------------------------------------------------------------------------

_CLASS_HEADER_RE = re.compile(
    r"class\s+(?P<cls>[A-Za-z_]\w*)\s*(?:final\s*)?:\s*(?P<bases>[^{;]+)\{")
_BASE_TOKEN_RE = re.compile(
    r"public\s+(?:virtual\s+)?(?:[A-Za-z_]\w*::)*(?P<base>[A-Za-z_]\w*)")
_REGISTER_TRADE_RE = re.compile(
    r'ORE_REGISTER_TRADE_BUILDER\(\s*"([^"]+)"\s*,\s*([A-Za-z_:]+)\s*,')


def _portfolio_inheritance(portfolio_dir: Path) -> tuple[dict[str, list[str]], dict[str, str]]:
    """class name -> its direct public base names; class name -> declaring
    file's bare name. Files are scanned in sorted order so that if a class is
    ever declared twice in the corpus, the alphabetically-first file wins the
    same way on every build (A4 determinism) - graphify itself never sees
    this data, so nothing upstream enforces uniqueness for us.
    """
    files = sorted(portfolio_dir.glob("*.hpp")) + sorted(portfolio_dir.glob("*.cpp"))
    files.sort()
    inherit_map: dict[str, list[str]] = defaultdict(list)
    class_file: dict[str, str] = {}
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        for m in _CLASS_HEADER_RE.finditer(text):
            cls = m.group("cls")
            bases = _BASE_TOKEN_RE.findall(m.group("bases"))
            if not bases:
                continue
            inherit_map[cls].extend(bases)
            class_file.setdefault(cls, f.name)
    return inherit_map, class_file


def _trade_family(inherit_map: dict[str, list[str]]) -> set[str]:
    """Transitive closure of every portfolio class descending from Trade -
    not just its direct children (Swap, CapFloor, ...) but multi-level chains
    too (CrossCurrencySwap -> Swap -> Trade; EquityAccumulator -> Accumulator
    -> ScriptedTrade -> Trade). A direct-only count badly under-represents
    the corpus: see build_trade_registry()'s stats for the cross-check this
    supports against the graph's own "inherits" edges.
    """
    reachable = {"Trade"}
    changed = True
    while changed:
        changed = False
        for cls, bases in sorted(inherit_map.items()):
            if cls in reachable:
                continue
            if any(base in reachable for base in bases):
                reachable.add(cls)
                changed = True
    return reachable


def build_trade_registry(engine: Path, chunks_by_name: dict[str, Chunk]) -> tuple[list[dict], dict]:
    """Return (registry, stats). registry is a sorted list of
    {"type", "class", "file"} - the trade-type string each buildable Trade
    subclass registers, its implementing class, and the source file it's
    declared in.

    Both facts combined here come from source, not docs:

    - `ORE_REGISTER_TRADE_BUILDER("Type", Class, ...)` in
      `OREData/ored/utilities/databuilders.cpp` is TradeFactory's actual
      runtime dispatch table - the unambiguous answer to "what TradeType
      strings does ORE build, and with which class". It is used as the
      primary source of (type, class) pairs.
    - `OREData/ored/portfolio/*.{hpp,cpp}` is scanned (as directed) to
      classify every class that inherits from Trade, directly or
      transitively, and supply each registered class's source file.

    Why not just regex `Trade("X")` calls in portfolio/ as the sole source,
    as the task literally describes: tried first, and it doesn't distinguish
    a real, independently-buildable trade type from an abstract intermediate
    class that exists purely to share code between several real ones. E.g.
    `Accumulator` has its own default constructor passing "Accumulator" to
    ScriptedTrade - syntactically identical to `Swap`'s own passthrough - but
    `Accumulator` is never registered; only its concrete children
    (`EquityAccumulator`, `FxAccumulator`, `CommodityAccumulator`) are. No
    purely-syntactic rule over portfolio/ alone reliably tells these apart
    (self-referential defaults, out-of-line .cpp constructors, and a
    `tradeType_ = "..."` body assignment instead of a base-constructor
    argument are all real patterns in this corpus, on top of the plain
    `Trade("X")` case). The registration table is what ORE itself uses to
    make that same distinction at runtime, so it is used here as the
    authoritative filter, and the portfolio scan is kept as required for
    sourcing file paths and for the cross-check below.
    """
    portfolio_dir = engine / chunks_by_name["OREData"].root / "portfolio"
    inherit_map, class_file = _portfolio_inheritance(portfolio_dir)
    trade_family = _trade_family(inherit_map)

    databuilders = engine / chunks_by_name["OREData"].root / "utilities" / "databuilders.cpp"
    confirmed: dict[str, str] = {}
    if databuilders.exists():
        text = databuilders.read_text(encoding="utf-8", errors="ignore")
        for trade_type, cls in _REGISTER_TRADE_RE.findall(text):
            confirmed[trade_type] = cls.rsplit("::", 1)[-1]

    registry: list[dict] = []
    unresolved: list[list[str]] = []
    for trade_type, cls in sorted(confirmed.items()):
        source_file = class_file.get(cls)
        if source_file is None:
            unresolved.append([trade_type, cls])
            continue
        registry.append({"type": trade_type, "class": cls, "file": source_file})
    registry.sort(key=lambda r: (r["type"], r["class"], r["file"]))

    direct_children = sorted(cls for cls, bases in inherit_map.items() if "Trade" in bases)
    not_independently_registered = sorted(
        (trade_family - {"Trade"}) - {r["class"] for r in registry})

    return registry, {
        "portfolio_files_scanned": len(list(portfolio_dir.glob("*.hpp")))
                                   + len(list(portfolio_dir.glob("*.cpp"))),
        "trade_family_classes_in_source": len(trade_family) - 1,
        "direct_trade_children_in_source": direct_children,
        "confirmed_registrations": len(confirmed),
        "registry_size": len(registry),
        "unresolved_confirmed": unresolved,
        "trade_family_not_independently_registered": not_independently_registered,
    }


# ---------------------------------------------------------------------------
# A2: every named XSD type/element, parsed directly from xsd/*.xsd
# ---------------------------------------------------------------------------

_XS_NS = "{http://www.w3.org/2001/XMLSchema}"
_NAMED_TAGS = {
    f"{_XS_NS}complexType": "complexType",
    f"{_XS_NS}simpleType": "simpleType",
    f"{_XS_NS}element": "element",
}


def _named_join_candidate_elements(root: ET.Element) -> tuple[set[int], set[int]]:
    """(root_elements, dispatch_elements) - id()s of every xs:element that
    names a reusable, globally-referenceable concept, as opposed to an
    ordinary struct field, split by which of two shapes it comes from:

    - root_elements: a direct child of xs:schema (a genuine top-level/root
      element, e.g. conventions.xsd's own `<xs:element name="Conventions"
      type="conventions"/>`) - unambiguous, names exactly one concept.
    - dispatch_elements: an alternative inside a NAMED dispatch xs:choice - a
      group or complexType whose content is one xs:choice of element
      alternatives, e.g. instruments.xsd's `<xs:group name="oreTradeData">
      <xs:choice><xs:element type="swapData" name="SwapData"/>...` - each
      such element names a distinct XML tag bound to a shared type, which is
      exactly what Tier 1 needs (the "<T>Data" names). conventions.xsd's
      `<xs:complexType name="conventions"><xs:choice>...` follows the same
      shape, but its alternatives (Swap, FX, Deposit, CDS, ...) are short,
      generic business words with a real collision risk against unrelated
      code (see link_schema()'s Tier 2/3 guard) that root_elements doesn't
      share - keeping the two sets distinct is what lets that guard target
      dispatch alternatives specifically, without also excluding a file's
      own unambiguous root element.

    An element inside a plain xs:sequence/xs:all (curveconfig.xsd's
    `<xs:element type="bool" name="AddBasis"/>` deep in a field list) is
    neither: it's a struct field, one of thousands corpus-wide, and treating
    each as its own "type" would swamp A5's orphan list with fields nobody
    ever expected a dedicated class for.
    """
    element_tag = f"{_XS_NS}element"
    root_elements = {id(child) for child in root if child.tag == element_tag}
    dispatch_elements: set[int] = set()
    parent_of = {child: parent for parent in root.iter() for child in parent}
    for choice in root.iter(f"{_XS_NS}choice"):
        container = parent_of.get(choice)
        if container is not None and container.get("name"):
            dispatch_elements.update(id(el) for el in choice if el.tag == element_tag)
    return root_elements, dispatch_elements


def extract_xsd_types(engine: Path, xsd_root: str) -> tuple[list[dict], dict]:
    """Every xs:complexType/xs:simpleType name, plus every join-candidate
    xs:element name (see _named_join_candidate_elements), declared anywhere
    in xsd/*.xsd - direct from the schema files, the full census A5(a) is
    measured against. Deliberately independent of the OREXsd semantic
    chunk's nodes, which are an LLM's curated subset (see link_schema()).
    """
    xsd_dir = engine / xsd_root
    files = sorted(xsd_dir.glob("*.xsd"))
    types: list[dict] = []
    parse_errors: list[list[str]] = []
    for f in files:
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError as exc:
            parse_errors.append([f.name, str(exc)])
            continue
        rel = f"{xsd_root}/{f.name}"
        root_elements, dispatch_elements = _named_join_candidate_elements(root)
        for el in root.iter():
            kind = _NAMED_TAGS.get(el.tag)
            if kind is None:
                continue
            is_dispatch = id(el) in dispatch_elements
            if kind == "element" and not is_dispatch and id(el) not in root_elements:
                continue
            name = el.get("name")
            if not name:
                continue  # anonymous inline type/element - not a join key
            types.append({"name": name, "kind": kind, "file": rel,
                          "dispatch": is_dispatch})
    types.sort(key=lambda t: (t["file"], t["name"], t["kind"]))
    return types, {
        "xsd_files_scanned": len(files),
        "parse_errors": parse_errors,
        "named_types_total": len(types),
        "distinct_names": len({t["name"] for t in types}),
    }


# ---------------------------------------------------------------------------
# A3: the tiered join
# ---------------------------------------------------------------------------

_NORMALIZE_SUFFIXES = ("parameters", "config", "data")


def _normalize(name: str) -> str:
    """casefold, drop underscores, strip one trailing Data/Config/Parameters -
    the Tier 3 fallback key, checked longest-suffix-first so "...Parameters"
    isn't left with a dangling "...eters" by a premature shorter match."""
    n = name.replace("_", "").casefold()
    for suffix in _NORMALIZE_SUFFIXES:
        if n.endswith(suffix) and len(n) > len(suffix):
            return n[: -len(suffix)]
    return n


#: "name (complexType)", "name (top-level complexType)", "name (element, ...)"
#: or the parenthesis-free "name complexType" - the label shapes the LLM
#: extraction actually used when it kept a literal schema name (mainly
#: instruments.xsd/curveconfig.xsd/simulation.xsd/ore_types.xsd; most other
#: files paraphrase, e.g. "Zero Rate Convention", and simply won't match).
_XSD_TYPE_LABEL_RE = re.compile(
    r"^([A-Za-z][\w]*)\s*(?:\((?:top-level )?(?:complexType|simpleType|element)|"
    r"(?:complexType|simpleType|element)\b)")
#: Every one of the 23 xsd/*.xsd files gets a per-file summary node labelled
#: "<Something> Schema (<file>.xsd)" - the fallback anchor for any matched
#: type name that didn't get its own curated node.
_XSD_SCHEMA_LABEL_RE = re.compile(r"Schema\s*\(([\w.]+\.xsd)\)")


def _index_xsd_nodes(xsd_nodes: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """xsd type/element name -> local node id (curated subset only); xsd file
    path -> that file's summary node id (all 23 files - the edge anchor for
    every matched name the curated extraction didn't give its own node)."""
    by_name: dict[str, str] = {}
    by_file: dict[str, str] = {}
    for n in xsd_nodes:
        label = str(n.get("label", ""))
        m = _XSD_TYPE_LABEL_RE.match(label)
        if m:
            by_name.setdefault(m.group(1), n["id"])
        m = _XSD_SCHEMA_LABEL_RE.search(label)
        if m:
            by_file.setdefault(f"xsd/{m.group(1)}", n["id"])
    return by_name, by_file


def _index_code_labels(graphs: dict[str, dict], repos: tuple[str, ...]) -> dict[str, list[dict]]:
    """Exact class label -> candidate OREData/OREAnalytics nodes with a real
    source file. Excludes nodes with no source_file: the AST extractor emits
    a stub node for every *reference* to a type (a forward declaration, a
    member, a template argument), not just its definition - only a node
    carrying real source info is a plausible definition site.
    """
    by_label: dict[str, list[dict]] = defaultdict(list)
    for repo in repos:
        g = graphs.get(repo)
        if not g:
            continue
        for n in g.get("nodes", []):
            if not n.get("_callable_class") or not n.get("source_file"):
                continue
            entry = dict(n)
            entry["_repo"] = repo
            by_label[n["label"]].append(entry)
    return by_label


def _resolve_code_node(name: str, by_label: dict[str, list[dict]],
                       preferred_file: str | None = None) -> dict | None:
    """A single candidate node for *name*, or None (no match / unresolved
    ambiguity). Ties are broken by preferring the candidate whose source file
    stem equals the expected file's stem - the file a class is declared in is
    overwhelmingly likely to be named after the class itself."""
    candidates = by_label.get(name, [])
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1 and preferred_file:
        stem = PurePosixPath(preferred_file).stem.lower()
        exact = [c for c in candidates
                if PurePosixPath(str(c["source_file"])).stem.lower() == stem]
        if len(exact) == 1:
            return exact[0]
    return None


def link_schema(engine: Path, chunks: list[Chunk], graphs: dict[str, dict],
                engine_roots: dict[str, str]) -> tuple[list[dict], dict]:
    """Return (schema_for edges, stats). Same shape as link.py's link():
    edges use local (pre-namespace) node ids - merge.py remaps them onto the
    merged graph exactly as it does for link()'s cross-module edges.

    Must be called with *graphs* in its pre-namespacing form (local ids and
    each chunk's own "links"/"edges" still present) - merge.py calls this
    before its namespacing loop mutates node/edge ids in place, the same
    graphs dict link()'s local_view is reconstructed from afterward.
    """
    chunks_by_name = {c.name: c for c in chunks}
    registry, registry_stats = build_trade_registry(engine, chunks_by_name)

    xsd_root = chunks_by_name["OREXsd"].root
    xsd_types, xsd_stats = extract_xsd_types(engine, xsd_root)
    xsd_names = sorted({t["name"] for t in xsd_types})
    xsd_name_files: dict[str, str] = {}
    xsd_name_dispatch: dict[str, bool] = {}
    for t in xsd_types:
        xsd_name_files.setdefault(t["name"], t["file"])
        xsd_name_dispatch.setdefault(t["name"], t["dispatch"])

    xsd_by_name, xsd_by_file = _index_xsd_nodes(graphs.get("OREXsd", {}).get("nodes", []))
    code_by_label = _index_code_labels(graphs, ("OREData", "OREAnalytics"))
    normalized_code: dict[str, list[str]] = defaultdict(list)
    for label in sorted(code_by_label):
        normalized_code[_normalize(label)].append(label)

    matched: dict[str, dict] = {}
    tier_counts: Counter[int] = Counter()

    # Tier 1 (EXTRACTED): "<T>Data" where <T> is a registry trade type.
    for entry in registry:
        candidate = f"{entry['type']}Data"
        if candidate not in xsd_name_files or candidate in matched:
            continue
        node = _resolve_code_node(entry["class"], code_by_label, entry["file"])
        if node is None:
            continue
        matched[candidate] = {"tier": 1, "code_node": node, "via": entry["type"]}
        tier_counts[1] += 1

    # Tier 2/3 guards against two confirmed collision patterns - both found
    # by spot-checking real edges, not hypothesised:
    #
    # 1. A registry trade class's *real* schema binding is always Tier 1,
    #    from instruments.xsd - conventions.xsd/ore_types.xsd/etc.
    #    legitimately reuse the same short business word for an unrelated
    #    concept (conventions.xsd's dispatch element
    #    `<xs:element type="swapType" name="Swap"/>` names a *convention*,
    #    not the Swap trade; ore_types.xsd's `capFloor` is a two-value
    #    Cap/Floor enum, not the CapFloor trade). A Tier 2/3 candidate
    #    landing on a registry class from any OTHER file is this collision,
    #    confirmed for every case found (Swap, FxOption, InflationSwap,
    #    CommodityForward via conventions.xsd; CapFloor via ore_types.xsd).
    # 2. conventions.xsd's dispatch elements *specifically* (Zero, CDS,
    #    Deposit, FX, ... - the xs:choice alternatives inside its
    #    `conventions` complexType, not its own unambiguous root element) are
    #    short, generic tags with no structure of their own - high collision
    #    risk against ANY unrelated class, not just trade classes
    #    (`<xs:element type="fxType" name="FX"/>` - an FX rate convention -
    #    matched OREData's cross-asset-model `FxData` purely because
    #    "FX".normalize() == "FxData".normalize() == "fx"; the real target is
    #    `FXConvention`). These are already resolved correctly by
    #    xsd_link.py's dedicated conventions.xsd<->conventions.cpp
    #    dispatch-table pass (25/25 exact), so generic name matching adds
    #    nothing but false positives here and is skipped entirely - but only
    #    for dispatch alternatives, not the file's own root element (which
    #    IS an unambiguous, correct Tier 2 match: `<xs:element name=
    #    "Conventions" type="conventions"/>` -> the `Conventions` class).
    #
    # Both are rejected outright rather than kept as a lower-confidence
    # guess - a wrong edge corrupts the A5(b) "actionable" gap list, which
    # is worse than a missed one that just shows up honestly in A5(a).
    registry_classes = {entry["class"] for entry in registry}
    conventions_file = f"{xsd_root}/conventions.xsd"

    def _rejected(name: str, node: dict) -> bool:
        source_file = xsd_name_files.get(name, "")
        if node["label"] in registry_classes and source_file != f"{xsd_root}/instruments.xsd":
            return True
        if source_file == conventions_file and xsd_name_dispatch.get(name):
            return True
        return False

    # Tier 2 (EXTRACTED): exact label match against OREData/OREAnalytics.
    for name in xsd_names:
        if name in matched:
            continue
        node = _resolve_code_node(name, code_by_label, xsd_name_files.get(name))
        if node is not None and not _rejected(name, node):
            matched[name] = {"tier": 2, "code_node": node, "via": name}
            tier_counts[2] += 1

    # Tier 3 (INFERRED): normalised match, only where 1 and 2 found nothing.
    for name in xsd_names:
        if name in matched:
            continue
        candidates = normalized_code.get(_normalize(name), [])
        if len(candidates) != 1:
            continue
        node = _resolve_code_node(candidates[0], code_by_label, xsd_name_files.get(name))
        if node is not None and not _rejected(name, node):
            matched[name] = {"tier": 3, "code_node": node, "via": candidates[0]}
            tier_counts[3] += 1

    confidence = {1: ("EXTRACTED", 0.95), 2: ("EXTRACTED", 0.9), 3: ("INFERRED", 0.6)}
    edges: list[dict] = []
    unanchored: list[str] = []
    for name in sorted(matched):
        m = matched[name]
        xsd_node_id = xsd_by_name.get(name) or xsd_by_file.get(xsd_name_files.get(name, ""))
        if xsd_node_id is None:
            unanchored.append(name)
            continue
        conf, score = confidence[m["tier"]]
        edges.append({
            "source": xsd_node_id,
            "target": m["code_node"]["id"],
            "relation": SCHEMA_FOR,
            "context": f"xsd_schema_join_tier{m['tier']}",
            "confidence": conf,
            "confidence_score": score,
            "weight": 1.0,
            "source_file": xsd_name_files.get(name),
            "_origin": "schema_link",
            "_tier": m["tier"],
        })
    edges.sort(key=lambda e: (e["source"], e["target"]))

    # ---- A5: drift, in both directions -------------------------------------
    xsd_orphans = sorted(
        ({"name": n, "file": xsd_name_files.get(n, "")} for n in xsd_names if n not in matched),
        key=lambda d: (d["file"], d["name"]))

    covered_classes = {m["code_node"]["label"] for m in matched.values()}
    code_trade_gaps = sorted(
        (dict(r) for r in registry if r["class"] not in covered_classes),
        key=lambda r: (r["type"], r["class"], r["file"]))

    # ---- A1 cross-check: registry vs. the graph's own "inherits" edges.
    # graphify emits one unresolved-reference placeholder node per file that
    # mentions an external base class (e.g. "portfolio_ascot_hpp_trade")
    # rather than resolving to the single canonical Trade definition node, so
    # this matches on label, not id - and even so only sees DIRECT
    # "class X : public Trade" edges, not the multi-level chains
    # (CrossCurrencySwap -> Swap -> Trade) the registry above also covers by
    # construction. A large gap here is expected for that reason; see
    # docs/XSD-DRIFT.md for the reconciliation.
    ore_data = graphs.get("OREData", {})
    label_of = {n["id"]: n.get("label") for n in ore_data.get("nodes", [])}
    trade_ids = {node_id for node_id, label in label_of.items() if label == "Trade"}
    direct_children_in_graph = sorted({
        label_of.get(e.get("source"))
        for e in ore_data.get("links", ore_data.get("edges", []))
        if e.get("relation") == "inherits" and e.get("target") in trade_ids
        and label_of.get(e.get("source"))
    })

    stats = {
        "trade_registry": registry_stats,
        "xsd_census": xsd_stats,
        "tier_counts": {str(k): v for k, v in sorted(tier_counts.items())},
        "matched_total": len(matched),
        "unanchored_matches": sorted(unanchored),
        "xsd_orphans": xsd_orphans,
        "code_trade_gaps": code_trade_gaps,
        "schema_for_edges": len(edges),
        "direct_trade_children_in_graph": direct_children_in_graph,
        "direct_trade_children_in_graph_count": len(direct_children_in_graph),
    }
    return edges, stats


# ---------------------------------------------------------------------------
# A5: the drift report - the primary output of this module, not a side effect
# ---------------------------------------------------------------------------

#: format_drift_report()'s output goes between these two markers in
#: docs/XSD-DRIFT.md; everything outside them (the A6 field-level findings,
#: any hand-written intro) survives a re-run of `oregraph merge` untouched.
DRIFT_REPORT_BEGIN = "<!-- BEGIN XSD-DRIFT AUTO-GENERATED (oregraph merge) -->"
DRIFT_REPORT_END = "<!-- END XSD-DRIFT AUTO-GENERATED -->"


def format_drift_report(stats: dict) -> str:
    """Render (a) xsd orphans, (b) code trade gaps, (c) tier counts as
    markdown, between DRIFT_REPORT_BEGIN/END markers - the content
    `oregraph merge` writes into docs/XSD-DRIFT.md on every run."""
    reg = stats.get("trade_registry", {})
    census = stats.get("xsd_census", {})
    lines = [DRIFT_REPORT_BEGIN, ""]

    lines.append("## (c) Match counts by tier")
    lines.append("")
    tiers = stats.get("tier_counts", {})
    lines.append(f"- Tier 1 (EXTRACTED, `<T>Data` from the trade-type registry): "
                f"{tiers.get('1', 0)}")
    lines.append(f"- Tier 2 (EXTRACTED, exact class-label match): {tiers.get('2', 0)}")
    lines.append(f"- Tier 3 (INFERRED, normalised match): {tiers.get('3', 0)}")
    lines.append(f"- Total matched xsd type names: {stats.get('matched_total', 0)} / "
                f"{census.get('distinct_names', 0)}")
    lines.append(f"- `schema_for` edges written: {stats.get('schema_for_edges', 0)}"
                + (f" ({len(stats.get('unanchored_matches', []))} matches had no "
                   "graph node on the xsd side to anchor an edge to - name-level "
                   "match still counted above)" if stats.get("unanchored_matches") else ""))
    lines.append("")
    lines.append(f"Trade-type registry: {reg.get('registry_size', 0)} confirmed "
                f"TradeType registrations (`ORE_REGISTER_TRADE_BUILDER` in "
                f"databuilders.cpp), cross-referenced against "
                f"{reg.get('trade_family_classes_in_source', 0)} classes found in "
                f"portfolio/*.{{hpp,cpp}} transitively inheriting from Trade.")
    not_reg = reg.get("trade_family_not_independently_registered", [])
    if not_reg:
        lines.append(f"{len(not_reg)} of those classes are not independently "
                    "registered TradeTypes (abstract intermediates used only to "
                    f"share code, e.g. scaffolding base classes, or scripted-trade "
                    f"example payloads dispatched generically under `ScriptedTrade`): "
                    + ", ".join(f"`{c}`" for c in not_reg))
    direct_graph = stats.get("direct_trade_children_in_graph", [])
    lines.append("")
    lines.append(f"Cross-check: the merged graph's own `inherits` edges into any "
                f"node labelled `Trade` show {stats.get('direct_trade_children_in_graph_count', 0)} "
                f"direct subclasses ({', '.join(f'`{c}`' for c in direct_graph[:20])}"
                + (f", +{len(direct_graph) - 20} more" if len(direct_graph) > 20 else "")
                + f"), against {len(reg.get('direct_trade_children_in_source', []))} found by "
                "scanning portfolio/*.{hpp,cpp} directly for `class X : public Trade`. "
                "graphify emits one unresolved-reference placeholder node per file that "
                "mentions the external `Trade` base rather than one canonical node, and "
                "even a perfect match only sees *direct* inheritance - not the multi-level "
                "chains (e.g. `CrossCurrencySwap -> Swap -> Trade`) the registry above "
                "also covers - so a large gap here is expected, not a bug.")
    lines.append("")

    lines.append("## (a) XSD types with no matching code")
    lines.append("")
    orphans = stats.get("xsd_orphans", [])
    lines.append(f"{len(orphans)} of {census.get('distinct_names', 0)} named xsd types/elements "
                "across all xsd/*.xsd files matched no code at any tier - schema for "
                "something renamed, removed, or never implemented (or, for many "
                "non-instruments.xsd files, a config/enum type with no dedicated "
                "parsing class of its own, e.g. a nested value type). Not all of "
                "these are bugs; each is worth a human look.")
    lines.append("")
    if orphans:
        by_file: dict[str, list[str]] = defaultdict(list)
        for o in orphans:
            by_file[o["file"]].append(o["name"])
        for f in sorted(by_file):
            lines.append(f"- `{f}`: " + ", ".join(f"`{n}`" for n in sorted(by_file[f])))
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## (b) Code trade types with no XSD type")
    lines.append("")
    gaps = stats.get("code_trade_gaps", [])
    lines.append(f"{len(gaps)} of {reg.get('registry_size', 0)} registered TradeTypes have "
                "no matching xsd type at any tier - **this is the validation coverage "
                "gap**: ORE will build every one of these from XML with no schema check "
                "on its fields at all.")
    lines.append("")
    if gaps:
        for g in gaps:
            lines.append(f"- `{g['type']}` - `{g['class']}` ({g['file']})")
    else:
        lines.append("(none)")
    lines.append("")
    lines.append(DRIFT_REPORT_END)
    return "\n".join(lines)
