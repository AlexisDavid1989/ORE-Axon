"""Put ORE_Forge's field mapping into the merged graph.

Why this exists
----------------
ORE_Forge maps every trade type, curve config, convention and pricing-engine
product to the XML fields ORE reads, and audits that mapping against the C++
`fromXML()`. Before this module, none of it was in the graph: fieldmap.py wrote
a JSON snapshot and stopped, so "which fields does this trade take, and which
class parses them?" - the question the mapping exists to answer - had no answer
in the graph, and nothing said so.

What is emitted (all under repo `OREFieldmap`)
-----------------------------------------------
One **entry node** per mapping entry - a trade type, curve config, convention or
pricing-engine product - labelled "FX Forward [trade mapping]", and two links
out of it, deliberately *not* `references`/`schema_for`, which mean something
else (a query has to tell "this XML shape is parsed by this class" from a C++
dependency, as schema_for already does):

- `maps_to_class`  entry -> the C++ class that parses it (for a pricing
  product: the trade it prices and the engine builders it selects);
- `maps_to_schema` entry -> the XSD type that validates it.

Cross-domain links
------------------
ORE_Forge also records how the four domains refer to one another, and its GUI
follows those references. fieldmap.py captures them with ORE_Forge's own
resolvers (`cross_links`) and they become edges between entry nodes:

- `maps_to_pricing_engine` trade -> the pricing-engine entries that serve it -
  by its `Pricing_Engine_Type` or `Trade_Type`, or, for a trade that only
  delegates (CallableSwap), those of the types it delegates to. More than one
  candidate is kept whole (a Swaption is European or Bermudan; which applies
  depends on trade content ORE_Forge does not parse) and marked with a lower
  confidence. A trade that never looks one up (`Pricing_Engine_Required: false`)
  has no edge and says so on its node; one with no entry is listed as unresolved;
- `maps_to_curve_config` trade -> the curve-config *type* its market-data fields
  resolve to, from each field's `risk_factor_type`. A trade names a market object
  (EUR, EUR-EURIBOR-6M), never a curve config, so this is the type
  (YieldCurve, DefaultCurve, ...) and never a particular curve. A field kind
  ORE_Forge has no config type for (`underlying`) is counted, not guessed;
- `maps_to_convention` curve config -> the convention types its fields refer
  to: a fixed `linked_convention_type`, or, for a yield-curve segment, the type
  its own `Type` selects.

All three are ORE_Forge's word - ORE's source has no table to re-derive them
from - so every one is INFERRED. Each carries the fields that gave rise to it.

The entry's resolved fields ride on the node as a `fields` attribute - XPath,
optionality, data type, value set, default - and a pricing product carries
`combinations`, one per valid (Model, Engine) pair with its own parameter
fields, because its parameter set depends on the pair. `query-fields` renders
the whole chain: fields -> entry -> schema type -> class.

Why the fields are not nodes of their own
-----------------------------------------
They were, first: 12,135 field nodes labelled with their XPath, plus a node per
pricing combination. Measured against `oregraph bench` (the same eight questions,
before and after) that broke retrieval - four of the eight answers changed, the
sensitivity question fell from 16 source files to 4 because a
`Risk Participation Agreement` entry and its 29 field nodes took the seeds and
the token budget, and the SABR answer grew from 1,448 to 3,178 tokens - and not
only where mapping nodes surfaced: adding that many nodes shifts graphify's
global term weights (IDF), which alone changed the SABR seeds with no mapping
node in the result. Combination nodes alone reproduced the SABR regression,
because "... / SABR / ..." is a legitimate match for a SABR question and
outranks the code that answers it. One node per entry (386) is bench-neutral:
identical token cost and source-file sets on all eight questions.

Authority, and why the edges carry a confidence
-----------------------------------------------
The mapping is ORE_Forge's claim. Wherever ORE's own source can say the same
thing independently, the link is re-derived from it and marked EXTRACTED:

- trade -> class: the TradeType registry, `ORE_REGISTER_TRADE_BUILDER` in
  databuilders.cpp (the runtime dispatch table itself);
- convention -> class: the `type == "X"` dispatch chain in conventions.cpp;
- pricing product -> builder: an `ORE_REGISTER_ENGINE_BUILDER` registration
  already in the graph (symbol_links.py);
- entry -> XSD type: the schema's own dispatch block (`oreTradeData`,
  `conventions`) or, for the other schemas, an element declaration of that name -
  and, when curveconfig.xsd declares that name more than once with different
  types depending on the parent (`Segments` under `YieldCurve` vs. under
  `InflationCurve`), narrowed by the entry's own `Parent_Node`: its own type is
  resolved the same way, and the element is looked up as that type's direct
  child. Still never a guess - ambiguous either way is unresolved, not chosen;
- entry -> class, where no dispatch table exists (a curve config's
  `Cpp_Class_Name`): the class's own header or .cpp names the entry's XML tag as
  a string literal - `checkNode(node, "BondSpread")`. That is a mention, not a
  proof of a parse, so it earns a lower score than a dispatch table.

Where only ORE_Forge's word is left - the class exists in the graph but its
source never names the tag - the link is INFERRED and the entry is listed in the
stats as unsupported. Where the two sources disagree the source wins and the
disagreement is reported in the stats (and by `verify`), never resolved
silently. A name that resolves to no node is reported, not guessed at - the same
rule link_schema.py follows.

Limits
------
Links are per entry, not per field: nothing here says which line of `fromXML()`
reads a given field. An XSD link anchors at the type's own node when the
OREXsd extraction produced one and at the schema file's summary node when it did
not (the same fallback link_schema.py uses); the edge's `anchor` says which.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from .fieldmap import DOMAINS, FieldmapSnapshot
from .link_schema import (_XS_NS, _XSD_SCHEMA_LABEL_RE, _XSD_TYPE_LABEL_RE,
                          _defines_class, _read_cached)
from .xsd_link import (_lookup_xsd_node, _parse_convention_dispatch,
                       _parse_dispatch_block, _parse_trade_builder_registrations,
                       _xsd_node_index)

FIELDMAP_REPO = "OREFieldmap"
MAPS_TO_CLASS = "maps_to_class"
MAPS_TO_SCHEMA = "maps_to_schema"
#: Between two entries of different domains (see "Cross-domain links" above).
MAPS_TO_PRICING_ENGINE = "maps_to_pricing_engine"     # trade -> pricing engine
MAPS_TO_CURVE_CONFIG = "maps_to_curve_config"         # trade -> curve config
MAPS_TO_CONVENTION = "maps_to_convention"             # curve config -> convention
CROSS_RELATIONS = frozenset({MAPS_TO_PRICING_ENGINE, MAPS_TO_CURVE_CONFIG,
                             MAPS_TO_CONVENTION})
FIELDMAP_RELATIONS = frozenset({MAPS_TO_CLASS, MAPS_TO_SCHEMA}) | CROSS_RELATIONS

#: `_origin` stamped on every edge/node this module adds - verify.py counts them
#: the way it counts symbol_link / xsd_link / schema_link.
ORIGIN = "fieldmap_link"

_DOMAIN_LABEL = {"trade": "trade", "curve_config": "curve config",
                 "convention": "convention", "pricing_engine": "pricing engine"}

#: The schema each domain's entries live in - the tie-break when an element
#: name is declared in more than one xsd file.
_DOMAIN_XSD = {"trade": "instruments.xsd", "curve_config": "curveconfig.xsd",
               "convention": "conventions.xsd", "pricing_engine": "pricingengines.xsd"}

#: Repos whose classes an entry can map to; the first is home - every mapped
#: class in practice lives in OREData, and preferring it is what discards the
#: stub nodes other repos carry for a class they merely mention.
_CODE_REPOS = ("OREData", "OREAnalytics", "QuantExt")
_HOME_REPO = "OREData"

# (confidence, score) by how a link was established.
_EXTRACTED_SOURCE = ("EXTRACTED", 0.95)     # re-derived from a source dispatch table
_EXTRACTED_ELEMENT = ("EXTRACTED", 0.9)     # an xsd element declaration of that name
_EXTRACTED_LITERAL = ("EXTRACTED", 0.85)    # the class's source names the entry's XML tag
_INFERRED_CLAIM = ("INFERRED", 0.75)        # ORE_Forge's claim; the target exists
_INFERRED_NESTED = ("INFERRED", 0.6)        # claim names a nested class; linked to its enclosing class
_INFERRED_AMBIGUOUS = ("INFERRED", 0.5)     # the claim names several candidates; which applies is not stated


# ---------------------------------------------------------------------------
# Indexes over the merged graph and the Engine source
# ---------------------------------------------------------------------------

def _index_definitions(nodes: list[dict]) -> dict[str, list[dict]]:
    """Exact class label -> definition-site nodes. A node with no source_file is
    the AST extractor's stub for a *reference* to a type, not its definition
    (see xsd_link._index_ore_classes), so it is excluded."""
    by_label: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        if (n.get("repo") in _CODE_REPOS and n.get("_callable_class")
                and n.get("source_file")):
            by_label[n["label"]].append(n)
    return by_label


def _pick(candidates: list[dict], name: str, engine: Path) -> dict | None:
    """The one node for class *name*, or None when there is no single answer.

    The home repo wins outright: OREAnalytics's inputparameters.hpp carries a
    node for CurrencyConfig, Conventions, IborFallbackConfig and others that
    merely mention them, and it made every one of those look ambiguous. Within
    a pool, prefer the file whose stem is the class name, then a header over
    its .cpp, then - the same hardening link_schema._resolve_code_node applies,
    reused here rather than duplicated - whichever single candidate's own
    source is a real definition (`class Name {`) rather than a forward
    declaration (`class Name;`): the same inputparameters.hpp also
    forward-declares classes it never defines, which graphify's extractor
    gives the identical node shape a real definition gets."""
    home = [c for c in candidates if c["repo"] == _HOME_REPO]
    for pool in (home, candidates):
        if len(pool) == 1:
            return pool[0]
        if len(pool) > 1:
            stem = name.lower()
            exact = [c for c in pool
                     if PurePosixPath(str(c["source_file"])).stem.lower() == stem]
            headers = [c for c in (exact or pool)
                       if str(c["source_file"]).endswith((".hpp", ".h"))]
            if len(exact) == 1:
                return exact[0]
            if len(headers) == 1:
                return headers[0]
            defining = [c for c in pool
                       if c.get("repo_path")
                       and _defines_class(_read_cached(engine, c["repo_path"]), name)]
            if len(defining) == 1:
                return defining[0]
            return None
    return None


def _resolve_class(name: str, by_label: dict[str, list[dict]],
                   engine: Path) -> tuple[dict | None, str]:
    """(node, how). `how` is "exact", "nested" (an Outer::Inner class that has
    a node of its own in Outer's file) or "nested_outer" (it has none - the
    AST does not always emit nested types - so the enclosing class, which
    declares it, stands in and the edge says so). ("" when unresolved.)"""
    parts = name.split("::")
    if len(parts) == 1:
        node = _pick(by_label.get(name, []), name, engine)
        return (node, "exact") if node else (None, "")
    outer = _pick(by_label.get(parts[0], []), parts[0], engine)
    if outer is None:
        return None, ""
    same_file = [c for c in by_label.get(parts[-1], [])
                 if c["source_file"] == outer["source_file"]]
    inner = _pick(same_file, parts[-1], engine)
    if inner is not None:
        return inner, "nested"
    return outer, "nested_outer"


class _XsdIndex:
    """OREXsd graph nodes, findable by (schema file, type name).

    Two lookups because the extraction names nodes two ways: instruments.xsd
    and curveconfig.xsd nodes carry the literal "name (complexType)" label,
    while conventions.xsd's are paraphrased prose whose *id* still ends in the
    slugged type name (xsd_link._xsd_node_index). The schema file's summary
    node is the fallback anchor - every one of the 23 files has one."""

    def __init__(self, nodes: list[dict]):
        xsd_nodes = [n for n in nodes if n.get("repo") == "OREXsd"]
        self._slug = {f: _xsd_node_index(xsd_nodes, f)
                      for f in {n.get("source_file") for n in xsd_nodes}}
        self._by_label: dict[tuple[str, str], str] = {}
        self._summary: dict[str, str] = {}
        for n in xsd_nodes:
            label = str(n.get("label", ""))
            m = _XSD_TYPE_LABEL_RE.match(label)
            if m:
                self._by_label.setdefault((n.get("source_file"), m.group(1)), n["id"])
            m = _XSD_SCHEMA_LABEL_RE.search(label)
            if m:
                self._summary.setdefault(f"xsd/{m.group(1)}", n["id"])

    def anchor(self, xsd_file: str, type_name: str) -> tuple[str | None, str]:
        node_id = (_lookup_xsd_node(self._slug.get(xsd_file, {}), type_name)
                   or self._by_label.get((xsd_file, type_name)))
        if node_id:
            return node_id, "type"
        summary = self._summary.get(xsd_file)
        return (summary, "file") if summary else (None, "")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore") if path.exists() else ""


class _Sources:
    """Engine source files, each read at most once."""

    def __init__(self, engine: Path):
        self._engine = engine
        self._cache: dict[PurePosixPath, str] = {}

    def _text(self, rel: PurePosixPath) -> str:
        if rel not in self._cache:
            self._cache[rel] = _read(self._engine / rel)
        return self._cache[rel]

    def mentions(self, node: dict, literal: str) -> bool:
        """Does the class's header or its .cpp contain `"<literal>"`? A class's
        fromXML() names the node it parses as a string literal
        (`XMLUtils::checkNode(node, "YieldCurve")`), so this is source evidence
        for an entry -> class link that no dispatch table covers. It is a
        mention, not proof: a tag like `Source` can appear for other reasons."""
        rel = node.get("repo_path")
        if not rel:
            return False
        header = PurePosixPath(rel)
        return any(f'"{literal}"' in self._text(p)
                   for p in (header, header.with_suffix(".cpp")))


#: Built-in schema value types (`xs:string`, ...) mark a leaf value, not a
#: structured type an entry could map to; `DefaultCurve` is both a leaf string
#: in one type and a real complex type elsewhere, and counting the leaf made
#: the real one look ambiguous.
_BUILTIN_PREFIXES = ("xs:", "xsd:")


def _element_types(xsd_dir: Path, xsd_root: str) -> dict[str, set[tuple[str, str]]]:
    """element name -> {(xsd file, declared type)} for every named xs:element
    that declares a structured type, at any nesting depth. Broader than
    link_schema.extract_xsd_types, which keeps only root and dispatch elements
    because it wants *type* names - here the question is the reverse: what type
    does an element called `YieldCurve` carry? That is answered by the element,
    wherever it is declared. An element with an inline anonymous complexType
    (a schema's own root element, typically) has no type name and is recorded
    with "" - it can still anchor at its schema file."""
    out: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for f in sorted(xsd_dir.glob("*.xsd")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        rel = f"{xsd_root}/{f.name}"
        for el in root.iter(f"{_XS_NS}element"):
            name, type_name = el.get("name"), el.get("type")
            if not name:
                continue
            if type_name is None:
                if el.find(f"{_XS_NS}complexType") is not None:
                    out[name].add((rel, ""))
            elif not type_name.startswith(_BUILTIN_PREFIXES):
                out[name].add((rel, type_name.split(":")[-1]))
    return out


def _nested_element_types(xsd_dir: Path, xsd_root: str) -> dict[tuple[str, str], set[tuple[str, str]]]:
    """(named complexType, its direct child element name) -> {(xsd file, child's
    declared type)}. Lets a Parent_Node claim ("Segments"'s parent is "YieldCurve")
    disambiguate an element name the schema declares several times at different
    nesting depths - curveconfig.xsd declares "Segments" once as a child of the
    `yieldCurve` complexType and once as a child of `inflationCurve`, each with
    its own type: resolve the parent element's own type through `_element_types`,
    then look up the child here by (that type, xml_node).

    A child inside an *anonymous* nested complexType is deliberately not
    attributed to the enclosing named one - same "don't guess" rule
    `_element_types` follows for an element with no type name at all."""
    out: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    element_tag, complex_tag = f"{_XS_NS}element", f"{_XS_NS}complexType"

    def walk(el: ET.Element, enclosing: str | None, rel: str) -> None:
        for child in el:
            if child.tag == complex_tag:
                walk(child, child.get("name"), rel)
            elif child.tag == element_tag:
                name, type_name = child.get("name"), child.get("type")
                if (name and enclosing and type_name
                        and not type_name.startswith(_BUILTIN_PREFIXES)):
                    out[(enclosing, name)].add((rel, type_name.split(":")[-1]))
                walk(child, None, rel)
            else:
                walk(child, enclosing, rel)

    for f in sorted(xsd_dir.glob("*.xsd")):
        try:
            root = ET.parse(f).getroot()
        except ET.ParseError:
            continue
        walk(root, None, f"{xsd_root}/{f.name}")
    return out


def _parent_narrowed_type(domain: str, xml_node: str, parent_node: str | None,
                          elements: dict[str, set[tuple[str, str]]],
                          nested: dict[tuple[str, str], set[tuple[str, str]]],
                          xsd_root: str) -> tuple[tuple[str, str] | None, str]:
    """(xsd file, type name) for *xml_node* found as a direct child of its
    claimed parent's own type, when that narrows an otherwise-ambiguous element
    name to exactly one declaration. (None, "") - never a guess - when the
    parent has no Parent_Node, the parent itself doesn't resolve to a single
    type, or that type declares no such child."""
    if not parent_node:
        return None, ""
    own_file = {t for t in elements.get(parent_node, set())
               if t[0] == f"{xsd_root}/{_DOMAIN_XSD[domain]}"}
    parent_types = own_file or elements.get(parent_node, set())
    if len(parent_types) != 1:
        return None, ""
    _, parent_type = next(iter(parent_types))
    if not parent_type:
        return None, ""
    candidates = nested.get((parent_type, xml_node), set())
    return (next(iter(candidates)), "parent") if len(candidates) == 1 else (None, "")


def _xsd_type_for(domain: str, xml_node: str, dispatch: dict[str, tuple[str, str]],
                  elements: dict[str, set[tuple[str, str]]],
                  xsd_root: str) -> tuple[tuple[str, str] | None, str]:
    """(xsd file, type name) for an entry's XML node, plus how it was found:
    "dispatch" (the schema's own dispatch block), "element" (a unique element
    declaration) or "" (none, or ambiguous - never a guess)."""
    hit = dispatch.get(xml_node)
    if hit:
        return hit, "dispatch"
    candidates = elements.get(xml_node, set())
    if len(candidates) == 1:
        return next(iter(candidates)), "element"
    preferred = {c for c in candidates if c[0] == f"{xsd_root}/{_DOMAIN_XSD[domain]}"}
    if len(preferred) == 1:
        return next(iter(preferred)), "element"
    return None, ""


# ---------------------------------------------------------------------------
# Node and edge construction
# ---------------------------------------------------------------------------

def _virtual_path(domain: str, entry: str) -> str:
    """A `source_file` for a node that lives in no file of this repo. It has no
    extension on purpose: graphify's analysis treats a node whose source_file
    has none as a concept node and leaves it out of god_nodes and surprising
    connections, which is right - a generated mapping entry is not an
    architectural abstraction, and those lists should keep pointing at code."""
    return f"fieldmap/{domain}/{re.sub(r'[./]', '_', entry)}"


def _entry_node(domain: str, name: str, community: int, **attrs: Any) -> dict:
    label = f"{name} [{_DOMAIN_LABEL[domain]} mapping]"
    local_id = f"{domain}/{name}"
    node = {
        "id": f"{FIELDMAP_REPO}::{local_id}",
        "local_id": local_id,
        "label": label,
        "norm_label": label.lower(),
        "file_type": "concept",
        "source_file": _virtual_path(domain, name),
        "repo": FIELDMAP_REPO,
        "community": community,
        "community_key": f"{FIELDMAP_REPO}:{local_id}",
        "community_name": f"{name} ({_DOMAIN_LABEL[domain]} mapping)",
        "_origin": ORIGIN,
        "kind": "entry",
        "domain": domain,
        "entry": name,
    }
    node.update({k: v for k, v in attrs.items() if v is not None})
    return node


def _edge(source: str, target: str, relation: str, context: str,
          confidence: tuple[str, float], **attrs: Any) -> dict:
    edge = {"source": source, "target": target, "relation": relation,
            "context": context, "confidence": confidence[0],
            "confidence_score": confidence[1], "weight": 1.0, "_origin": ORIGIN}
    edge.update({k: v for k, v in attrs.items() if v is not None})
    return edge


def _field_records(nodes: list[dict], where: str,
                   duplicates: list[str]) -> list[dict]:
    """The leaf fields of a resolved node list, as the compact records an entry
    carries. Containers are the structure the XPaths already encode, so only
    `is_field` nodes are kept. A repeated XPath is reported, not silently kept
    or dropped - the resolver emitting one twice is a finding about the mapping."""
    records: list[dict] = []
    seen: set[str] = set()
    for field in nodes:
        if not (field.get("is_field") and field.get("xpath")):
            continue
        xpath = field["xpath"]
        if xpath in seen:
            duplicates.append(f"{where}#{xpath}")
            continue
        seen.add(xpath)
        record = {"xpath": xpath, "optional": field.get("is_optional"),
                  "data_type": field.get("data_type"),
                  "value_set": field.get("value_set"),
                  "default": field.get("value") or None}
        records.append({k: v for k, v in record.items() if v is not None})
    return records


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def link_fieldmap(snapshot: FieldmapSnapshot, nodes: list[dict], links: list[dict],
                  engine: Path, community_base: int) -> tuple[list[dict], list[dict], dict]:
    """Return (new nodes, new edges, stats).

    *nodes*/*links* are the fully namespaced merged graph (post-namespacing, as
    link_xsd receives it) and are only read. *community_base* is the first
    community id to hand out - merge.py passes the offset past the last chunk's
    range, so ids stay unique (and, like every community id, ephemeral).
    """
    xsd_root = "xsd"
    code = _index_definitions(nodes)
    xsd = _XsdIndex(nodes)

    # ORE's own dispatch tables, read straight from source (see module docstring).
    databuilders = engine / "OREData" / "ored" / "utilities" / "databuilders.cpp"
    conventions_cpp = engine / "OREData" / "ored" / "configuration" / "conventions.cpp"
    trade_registry = _parse_trade_builder_registrations(_read(databuilders))
    convention_dispatch = _parse_convention_dispatch(_read(conventions_cpp))
    xsd_dir = engine / xsd_root
    xsd_dispatch = {
        "trade": {el: (f"{xsd_root}/instruments.xsd", ty) for el, ty in _parse_dispatch_block(
            _read(xsd_dir / "instruments.xsd"), "oreTradeData").items()},
        "convention": {el: (f"{xsd_root}/conventions.xsd", ty) for el, ty in _parse_dispatch_block(
            _read(xsd_dir / "conventions.xsd"), "conventions").items()},
    }
    elements = _element_types(xsd_dir, xsd_root)
    nested = _nested_element_types(xsd_dir, xsd_root)
    xsd_type_files = {ty: f for found in elements.values() for f, ty in found if ty}
    sources = _Sources(engine)

    label_of = {n["id"]: n.get("label") for n in nodes}
    registered_builders = {label_of.get(e["target"]) for e in links
                           if e.get("context") == "ore_engine_registration"}

    out_nodes: list[dict] = []
    out_edges: list[dict] = []
    entry_ids: dict[tuple[str, str], str] = {}
    per_domain: dict[str, dict[str, Any]] = {}
    unresolved_class: dict[str, list[str]] = defaultdict(list)
    unresolved_schema: dict[str, list[str]] = defaultdict(list)
    class_disagreements: list[str] = []
    schema_disagreements: list[str] = []
    unsupported_claims: list[str] = []
    substituted: list[str] = []
    duplicate_xpaths: list[str] = []
    anchors: Counter[str] = Counter()
    community = community_base

    def link_class(domain: str, entry_id: str, entry: str, class_name: str, role: str,
                   context: str, confidence: tuple[str, float], via: str,
                   evidence_literal: str | None = None) -> bool:
        """Add a maps_to_class edge. *evidence_literal*, for a claim-only link,
        is the XML tag the class's own source should name to corroborate it."""
        node, how = _resolve_class(class_name, code, engine)
        if node is None:
            unresolved_class[domain].append(f"{entry}: {class_name}")
            return False
        if evidence_literal and confidence == _INFERRED_CLAIM:
            if sources.mentions(node, evidence_literal):
                context, confidence = "fieldmap_class_source", _EXTRACTED_LITERAL
            else:
                unsupported_claims.append(
                    f"{domain}/{entry}: {class_name}'s source never names {evidence_literal!r}")
        if how == "nested_outer":
            context, confidence = f"{context}_nested_outer", _INFERRED_NESTED
        out_edges.append(_edge(entry_id, node["id"], MAPS_TO_CLASS, context, confidence,
                               role=role, via=via, class_name=class_name,
                               source_file=node.get("source_file")))
        per_domain[domain]["confidence"][confidence[0]] += 1
        return True

    for domain in DOMAINS:
        entries = snapshot.domains.get(domain, {})
        stats = per_domain[domain] = {"entries": 0, "fields": 0, "combinations": 0,
                                      "class_linked": 0, "schema_linked": 0,
                                      "confidence": Counter()}
        for name in sorted(entries):
            record = entries[name]
            meta = record["meta"]
            entry_node = _entry_node(domain, name, community,
                                     xml_node=meta.get("XML_Node_Name"),
                                     asset_class=meta.get("Asset_Class"),
                                     trade_type=meta.get("Trade_Type"),
                                     cpp_class_name=meta.get("Cpp_Class_Name"),
                                     top_level=meta.get("Is_Top_Level"))
            entry_id = entry_node["id"]
            entry_ids[(domain, name)] = entry_id
            plan = ((record.get("links") or {}).get("pricing_engine")
                    if domain == "trade" else None)
            if plan and plan["kind"] in ("not_required", "delegates", "unknown"):
                entry_node["pricing_engine_kind"] = plan["kind"]
                entry_node["pricing_engine_note"] = plan.get("note")
            out_nodes.append(entry_node)
            stats["entries"] += 1

            # ---- fields, carried on the entry --------------------------------
            if domain == "pricing_engine":
                # A product's parameter set differs per (Model, Engine), so it
                # carries one field list per pair rather than a single total.
                combos = []
                for combo in record["combinations"]:
                    pair = f"{combo['Model']} / {combo['Engine']}"
                    fields = _field_records(combo["nodes"], f"{domain}/{name}/{pair}",
                                            duplicate_xpaths)
                    item: dict[str, Any] = {"model": combo["Model"],
                                            "engine": combo["Engine"], "fields": fields}
                    if combo.get("substituted"):
                        item["substituted"] = combo["substituted"]
                        substituted.append(f"{name} / {pair} -> {combo['substituted']}")
                    combos.append(item)
                    stats["fields"] += len(fields)
                stats["combinations"] += len(combos)
                entry_node["combinations"] = combos
                entry_node["combination_count"] = len(combos)
            else:
                fields = _field_records(record["nodes"], f"{domain}/{name}",
                                        duplicate_xpaths)
                entry_node["fields"] = fields
                entry_node["field_count"] = len(fields)
                entry_node["required_count"] = sum(1 for f in fields if not f.get("optional"))
                stats["fields"] += len(fields)

            # ---- class links ----------------------------------------------
            classed = False
            if domain == "trade":
                cls = trade_registry.get(meta.get("Trade_Type"))
                if cls:
                    classed = link_class(domain, entry_id, name, cls, "parser",
                                         "fieldmap_trade_registry", _EXTRACTED_SOURCE,
                                         f"Trade_Type={meta.get('Trade_Type')}")
                else:
                    unresolved_class[domain].append(
                        f"{name}: Trade_Type {meta.get('Trade_Type')!r} is not in "
                        "TradeFactory's registry")
            elif domain == "convention":
                claim = meta.get("Cpp_Class_Name")
                source_cls = convention_dispatch.get(meta.get("XML_Node_Name"))
                if source_cls:
                    if claim and claim != source_cls:
                        class_disagreements.append(
                            f"{domain}/{name}: ORE_Forge says {claim}, conventions.cpp "
                            f"dispatches {meta.get('XML_Node_Name')!r} to {source_cls}")
                    classed = link_class(domain, entry_id, name, source_cls, "parser",
                                         "fieldmap_convention_dispatch", _EXTRACTED_SOURCE,
                                         f"type == {meta.get('XML_Node_Name')!r}")
                elif claim:
                    classed = link_class(domain, entry_id, name, claim, "parser",
                                         "fieldmap_claim", _INFERRED_CLAIM,
                                         f"Cpp_Class_Name={claim}",
                                         evidence_literal=meta.get("XML_Node_Name"))
            elif domain == "curve_config":
                claim = meta.get("Cpp_Class_Name")
                if claim:
                    classed = link_class(domain, entry_id, name, claim, "parser",
                                         "fieldmap_claim", _INFERRED_CLAIM,
                                         f"Cpp_Class_Name={claim}",
                                         evidence_literal=meta.get("XML_Node_Name"))
                else:
                    unresolved_class[domain].append(f"{name}: ORE_Forge lists no Cpp_Class_Name")
            else:  # pricing_engine: the trade it prices, then the builders it selects
                cls = trade_registry.get(meta.get("Trade_Type"))
                if cls:
                    classed |= link_class(domain, entry_id, name, cls, "trade",
                                          "fieldmap_trade_registry", _EXTRACTED_SOURCE,
                                          f"Trade_Type={meta.get('Trade_Type')}")
                builders = meta.get("Cpp_Builders") or []
                for builder in builders:
                    corroborated = builder in registered_builders
                    classed |= link_class(
                        domain, entry_id, name, builder, "engine_builder",
                        "fieldmap_builder_registration" if corroborated else "fieldmap_claim",
                        _EXTRACTED_SOURCE if corroborated else _INFERRED_CLAIM,
                        f"Cpp_Builders={builder}")
                if not cls and not builders:
                    unresolved_class[domain].append(
                        f"{name}: Trade_Type {meta.get('Trade_Type')!r} is not in "
                        "TradeFactory's registry and no Cpp_Builders are listed")
            stats["class_linked"] += classed

            # ---- schema link ----------------------------------------------
            xml_node = meta.get("XML_Node_Name")
            found, how = _xsd_type_for(domain, xml_node, xsd_dispatch.get(domain, {}),
                                       elements, xsd_root)
            if found is None and domain == "curve_config":
                found, how = _parent_narrowed_type(
                    domain, xml_node, meta.get("Parent_Node"), elements, nested, xsd_root)
            claimed = meta.get("XSD_Type")
            if found and found[1] and claimed and claimed != found[1]:
                schema_disagreements.append(
                    f"{domain}/{name}: ORE_Forge says XSD_Type {claimed!r}, the schema's "
                    f"{xml_node!r} declares {found[1]!r}")
            confidence = _EXTRACTED_SOURCE if how == "dispatch" else _EXTRACTED_ELEMENT
            if found is None and claimed and claimed in xsd_type_files:
                found, how, confidence = (xsd_type_files[claimed], claimed), "claim", _INFERRED_CLAIM
            if found is None:
                unresolved_schema[domain].append(f"{name}: {xml_node}")
            else:
                xsd_file, type_name = found
                target, anchor = xsd.anchor(xsd_file, type_name)
                if target is None:
                    unresolved_schema[domain].append(f"{name}: {type_name} (no node for {xsd_file})")
                else:
                    out_edges.append(_edge(
                        entry_id, target, MAPS_TO_SCHEMA, f"fieldmap_xsd_{how}",
                        confidence, xsd_type=type_name or None, anchor=anchor,
                        source_file=xsd_file))
                    anchors[anchor] += 1
                    stats["confidence"][confidence[0]] += 1
                    stats["schema_linked"] += 1
            community += 1

    # ---- cross-domain links --------------------------------------------
    # A second pass: a link's target is another domain's entry, so every entry
    # node has to exist first. A target that is not an entry is reported, never
    # dropped silently - the same rule the class and schema links follow.
    cross_edges: Counter[str] = Counter()
    unresolved_cross: dict[str, list[str]] = defaultdict(list)
    unmapped_risk: Counter[str] = Counter()
    plan_kinds: Counter[str] = Counter()

    def link_entries(source_domain: str, source: str, target_domain: str, target: str,
                     relation: str, context: str, confidence: tuple[str, float],
                     **attrs: Any) -> bool:
        target_id = entry_ids.get((target_domain, target))
        if target_id is None:
            unresolved_cross[relation].append(
                f"{source_domain}/{source} -> {target_domain}/{target}")
            return False
        out_edges.append(_edge(entry_ids[(source_domain, source)], target_id, relation,
                               context, confidence, **attrs))
        cross_edges[relation] += 1
        return True

    for name, record in sorted(snapshot.domains.get("trade", {}).items()):
        links = record.get("links") or {}
        plan = links.get("pricing_engine")
        if plan:
            plan_kinds[plan["kind"]] += 1
            if plan["kind"] == "delegates":
                for delegate in plan["delegates"]:
                    for candidate in delegate["candidates"]:
                        link_entries("trade", name, "pricing_engine", candidate,
                                     MAPS_TO_PRICING_ENGINE, "fieldmap_pricing_engine_delegate",
                                     _INFERRED_CLAIM, via="delegates_to",
                                     delegate=delegate["trade_type"])
            elif plan["candidates"]:
                confidence = (_INFERRED_CLAIM if len(plan["candidates"]) == 1
                              else _INFERRED_AMBIGUOUS)
                for candidate in plan["candidates"]:
                    link_entries("trade", name, "pricing_engine", candidate,
                                 MAPS_TO_PRICING_ENGINE, "fieldmap_pricing_engine",
                                 confidence, via=plan["via"],
                                 lookup_type=plan["lookup_type"],
                                 candidates=len(plan["candidates"]))
            elif plan["kind"] == "unknown":
                unresolved_cross[MAPS_TO_PRICING_ENGINE].append(
                    f"trade/{name}: no pricing-engine entry serves {plan['lookup_type']!r}")
        for config_type, info in (links.get("curve_config") or {}).items():
            link_entries("trade", name, "curve_config", config_type, MAPS_TO_CURVE_CONFIG,
                         "fieldmap_risk_factor", _INFERRED_CLAIM,
                         risk_factor_types=info["risk_factor_types"], fields=info["fields"])
        unmapped_risk.update(links.get("unmapped_risk_factor_types") or {})

    for name, record in sorted(snapshot.domains.get("curve_config", {}).items()):
        for conv_type, info in ((record.get("links") or {}).get("convention") or {}).items():
            link_entries("curve_config", name, "convention", conv_type, MAPS_TO_CONVENTION,
                         "fieldmap_linked_convention", _INFERRED_CLAIM,
                         via=info["via"], fields=info["fields"])

    for d in per_domain.values():
        d["confidence"] = dict(d["confidence"])

    out_edges.sort(key=lambda e: (e["source"], e["target"], e["relation"]))
    stats_out = {
        "snapshot": {"source": snapshot.source, **snapshot.version},
        "domains": per_domain,
        "nodes": len(out_nodes),
        "edges": len(out_edges),
        "relations": dict(Counter(e["relation"] for e in out_edges)),
        "schema_anchor": dict(anchors),
        "unresolved_class": {d: sorted(v) for d, v in unresolved_class.items()},
        "unresolved_schema": {d: sorted(v) for d, v in unresolved_schema.items()},
        "class_disagreements": sorted(class_disagreements),
        "schema_disagreements": sorted(schema_disagreements),
        "unsupported_claims": sorted(unsupported_claims),
        "substituted_combinations": sorted(substituted),
        "duplicate_xpaths": sorted(duplicate_xpaths),
        "cross_links": {"relations": dict(cross_edges),
                        "pricing_plans": dict(plan_kinds),
                        "unresolved": {r: sorted(v) for r, v in unresolved_cross.items()},
                        "unmapped_risk_factors": dict(unmapped_risk)},
        "sources": {"trade_registry": len(trade_registry),
                    "convention_dispatch": len(convention_dispatch),
                    "xsd_dispatch": {d: len(v) for d, v in xsd_dispatch.items()}},
    }
    return out_nodes, out_edges, stats_out
