"""Task-oriented retrieval over a merged ORE graph."""
from __future__ import annotations

import json
import heapq
import re
from itertools import product
from pathlib import PurePosixPath
from pathlib import Path


RELATION_COST = {
    "calls": 1.0,
    "constructs": 1.0,
    "registers": 1.0,
    "returns": 1.0,
    "uses": 1.2,
    "inherits": 1.3,
    "schema_for": 1.5,
    "implements": 1.5,
    "maps_to_schema": 1.5,
    "references": 1.8,
    # A mapping entry names the class that parses it; costlier than a code
    # edge so a path between two code symbols does not cut through a mapping
    # entry that happens to name both.
    "maps_to_class": 2.0,
    "defines": 2.2,
    "includes": 3.0,
    "contains": 3.5,
}
CONFIDENCE_COST = {"RESOLVED": 0.0, "EXTRACTED": 0.2, "INFERRED": 2.5}

IMPACT_RELATIONS = {"calls", "constructs", "registers", "returns", "uses",
                    "inherits", "references"}
# schema_for/implements (oregraph/link_schema.py, oregraph/xsd_link.py) are
# XSD<->code links, not code-to-code impact edges - deliberately excluded
# from IMPACT_RELATIONS (and so from FLOW_RELATIONS, which builds on it) but
# included in BUNDLE_RELATIONS so query_example's "gather everything relevant
# to this analogue" traversal can reach the schema type a class implements,
# instead of reporting "SCHEMA: MISSING FROM CONNECTED GRAPH CONTEXT" for a
# link that actually exists in the graph.
SCHEMA_RELATIONS = {"schema_for", "implements"}
# ORE_Forge's field mapping (oregraph/fieldmap_link.py): an entry maps to the
# class that parses it and the XSD type that validates it, so a bundle around
# a class should reach both. The entry's fields are attributes on the node, not
# nodes of their own, so there is nothing further to traverse - query-fields
# renders them.
FIELDMAP_RELATIONS = {"maps_to_class", "maps_to_schema"}
BUNDLE_RELATIONS = (IMPACT_RELATIONS | {"defines", "imports"} | SCHEMA_RELATIONS
                    | FIELDMAP_RELATIONS)
FLOW_RELATIONS = {"calls", "constructs", "registers", "uses", "inherits",
                  "references"}


def load_path_graph(path: Path):
    """Load merged JSON without collapsing parallel semantic relations."""
    import networkx as nx

    raw = json.loads(path.read_text(encoding="utf-8"))
    # Merged artifacts declare themselves undirected for Graphify traversal,
    # but every stored edge still has meaningful source/target provenance.
    graph = nx.MultiDiGraph()
    for node in raw.get("nodes", []):
        data = dict(node)
        node_id = data.pop("id")
        graph.add_node(node_id, **data)
    for edge in raw.get("links", raw.get("edges", [])):
        data = dict(edge)
        source = data.pop("source")
        target = data.pop("target")
        graph.add_edge(source, target, **data)
    return graph


def _label(node_id, data: dict) -> str:
    for key in ("label", "name", "title", "local_id"):
        value = data.get(key)
        if value:
            return str(value)
    return str(node_id).rsplit("::", 1)[-1]


def _source(data: dict) -> str:
    return str(data.get("repo_path") or data.get("source_file") or "")


def _source_stem(source: str) -> str:
    return str(PurePosixPath(source).with_suffix("")) if source else ""


def resolve_exact(graph, symbol: str) -> list:
    """Return deterministic exact-label candidates for *symbol*."""
    if "::" in symbol:
        owner, member = symbol.rsplit("::", 1)
        owners = resolve_exact(graph, owner)
        owner_sources = {_source_stem(_source(graph.nodes[node_id]))
                         for node_id in owners}
        members = resolve_exact(graph, member)
        qualified = [node_id for node_id in members
                     if _source_stem(_source(graph.nodes[node_id])) in owner_sources]
        if qualified:
            return qualified

    wanted = symbol.casefold()
    matches = [
        node_id for node_id, data in graph.nodes(data=True)
        if _label(node_id, data).casefold() == wanted
        or str(data.get("local_id", "")).rsplit("::", 1)[-1].casefold() == wanted
    ]
    return sorted(matches, key=lambda node_id: (
        not bool(_source(graph.nodes[node_id])),
        len(str(node_id)),
        str(node_id),
    ))


def _edge_data(graph, source, target) -> tuple[dict, bool]:
    data = graph.get_edge_data(source, target)
    reversed_edge = data is None
    if reversed_edge:
        data = graph.get_edge_data(target, source)
    data = data or {}
    if graph.is_multigraph():
        candidates = list(data.values())
    else:
        candidates = [data]
    edge = min(candidates, key=lambda edge: (
        RELATION_COST.get(str(edge.get("relation", "")).lower(), 2.5)
        + CONFIDENCE_COST.get(str(edge.get("confidence", "")).upper(), 0.5),
        str(edge.get("relation", "")),
    ))
    return edge, reversed_edge


def _weight(source, target, data) -> float:
    if data and all(isinstance(value, dict) for value in data.values()):
        candidates = list(data.values())
    else:
        candidates = [data or {}]
    return min(
        RELATION_COST.get(str(edge.get("relation", "")).lower(), 2.5)
        + CONFIDENCE_COST.get(str(edge.get("confidence", "")).upper(), 0.5)
        for edge in candidates)


def _best_path(graph, starts: list, ends: list) -> list:
    import networkx as nx

    search_graph = graph.to_undirected(as_view=True) if graph.is_directed() else graph
    best = None
    for start, end in product(starts, ends):
        try:
            path = nx.shortest_path(search_graph, start, end, weight=_weight)
            cost = sum(_weight(source, target,
                               search_graph.get_edge_data(source, target) or {})
                       for source, target in zip(path, path[1:]))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            continue
        candidate = (cost, len(path), tuple(map(str, path)), path)
        if best is None or candidate[:3] < best[:3]:
            best = candidate
    if best is None:
        return []
    return best[3]


def query_path(graph, symbols: list[str], max_hops: int = 12) -> str:
    """Render compact, ranked paths connecting each consecutive symbol."""
    if len(symbols) < 2:
        raise ValueError("query-path needs at least two symbols")

    resolved = []
    for symbol in symbols:
        candidates = resolve_exact(graph, symbol)
        if not candidates:
            return f"NO EXACT MATCH: {symbol}"
        resolved.append(candidates)

    paths = []
    for index in range(len(resolved) - 1):
        path = _best_path(graph, resolved[index], resolved[index + 1])
        if not path:
            return f"NO PATH: {symbols[index]} -> {symbols[index + 1]}"
        if len(path) - 1 > max_hops:
            return (f"PATH TOO LONG: {symbols[index]} -> {symbols[index + 1]} "
                    f"({len(path) - 1} hops; limit {max_hops})")
        paths.append(path)

    lines = [f"Path corridor: {' -> '.join(symbols)}"]
    for segment, path in enumerate(paths, 1):
        if len(paths) > 1:
            lines.append(f"SEGMENT {segment}")
        first = graph.nodes[path[0]]
        lines.append(f"NODE {_label(path[0], first)} [src={_source(first)}]")
        for source, target in zip(path, path[1:]):
            edge, reversed_edge = _edge_data(graph, source, target)
            relation = edge.get("relation", "related")
            confidence = edge.get("confidence", "")
            target_data = graph.nodes[target]
            suffix = f" [{confidence}]" if confidence else ""
            arrow = "<--" if reversed_edge else "--"
            end = "--" if reversed_edge else "-->"
            lines.append(f"  {arrow}{relation}{suffix}{end} {_label(target, target_data)} "
                         f"[src={_source(target_data)}]")
    return "\n".join(lines)


def query_impact(graph, symbol: str, limit: int = 40) -> str:
    """Render direct incoming and outgoing semantic dependencies."""
    candidates = resolve_exact(graph, symbol)
    if not candidates:
        return f"NO EXACT MATCH: {symbol}"

    records = []
    seen = set()
    for node_id in candidates:
        for source, target, data, direction in (
                [(source, node_id, data, "IN")
                 for source, _target, _key, data in graph.in_edges(
                     node_id, keys=True, data=True)]
                + [(node_id, target, data, "OUT")
                   for _source, target, _key, data in graph.out_edges(
                       node_id, keys=True, data=True)]):
            relation = str(data.get("relation", "")).lower()
            if relation not in IMPACT_RELATIONS:
                continue
            other = source if direction == "IN" else target
            key = (direction, relation, other)
            if key in seen:
                continue
            seen.add(key)
            records.append((RELATION_COST.get(relation, 2.5), direction,
                            relation, str(other), other, data))

    records.sort()
    lines = [f"Impact neighborhood: {symbol}"]
    for _cost, direction, relation, _other_id, other, data in records[:limit]:
        other_data = graph.nodes[other]
        confidence = data.get("confidence", "")
        suffix = f" [{confidence}]" if confidence else ""
        arrow = f"--{relation}{suffix}-->" if direction == "OUT" else f"<--{relation}{suffix}--"
        lines.append(f"{direction} {arrow} {_label(other, other_data)} "
                     f"[src={_source(other_data)}]")
    if len(records) > limit:
        lines.append(f"TRUNCATED: {len(records) - limit} more semantic links")
    if not records:
        lines.append("NO DIRECT SEMANTIC LINKS")
    return "\n".join(lines)


def _bundle_category(source: str) -> str:
    lowered = source.casefold()
    if lowered.startswith("fieldmap/"):
        return "fieldmap"
    if "/test" in lowered or "test-suite" in lowered:
        return "tests"
    if lowered.endswith(".xsd") or "/xsd/" in lowered:
        return "schema"
    if "/portfolio/builders/" in lowered:
        return "builder"
    if "/pricingengines/" in lowered or "/models/" in lowered:
        return "pricing/model"
    if "/portfolio/" in lowered:
        return "trade/data"
    return "support"


def query_example(graph, symbol: str, depth: int = 2, limit: int = 80) -> str:
    """Return a categorized source bundle around an existing analogue."""
    starts = resolve_exact(graph, symbol)
    if not starts:
        return f"NO EXACT MATCH: {symbol}"
    search_graph = graph.to_undirected(as_view=True)
    frontier = [(node_id, 0) for node_id in starts]
    seen = set(starts)
    files: dict[str, set[str]] = {}
    for node_id, hops in frontier:
        data = graph.nodes[node_id]
        source = _source(data)
        if source:
            files.setdefault(source, set()).add(_label(node_id, data))
        if hops >= depth:
            continue
        for neighbor in search_graph.neighbors(node_id):
            edge, _reversed = _edge_data(graph, node_id, neighbor)
            if str(edge.get("relation", "")).lower() not in BUNDLE_RELATIONS:
                continue
            # A mapping entry whose XSD type has no node of its own anchors at
            # the schema file's summary node - one hub shared by ~150 entries.
            # Crossing it would bundle every unrelated trade's entry with this
            # one; the edge says "described somewhere in instruments.xsd", not
            # "related to this analogue".
            if edge.get("anchor") == "file":
                continue
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append((neighbor, hops + 1))

    categories = ["trade/data", "builder", "pricing/model", "schema", "tests", "support"]
    # Only a graph that carries a fieldmap can be "missing" one: for any other
    # graph a FIELDMAP section would report an absence that is not a finding.
    # It goes first: `limit` is shared across sections in order, and the mapping
    # entry is the smallest and most specific - a large TRADE/DATA section
    # (a class reaching every trade class through the instruments.xsd summary
    # node) would otherwise spend the whole budget before it.
    if any(data.get("repo") == "OREFieldmap" for _, data in graph.nodes(data=True)):
        categories.insert(0, "fieldmap")
    grouped: dict[str, list[tuple[str, set[str]]]] = {
        category: [] for category in categories}
    for source, labels in sorted(files.items()):
        grouped.setdefault(_bundle_category(source), []).append((source, labels))

    lines = [f"Implementation example bundle: {symbol}"]
    written = 0
    for category, entries in grouped.items():
        lines.append(f"{category.upper()}:")
        if not entries:
            lines.append("  MISSING FROM CONNECTED GRAPH CONTEXT")
            continue
        for source, labels in entries:
            if written >= limit:
                lines.append("  TRUNCATED")
                break
            summary = ", ".join(sorted(labels)[:5])
            lines.append(f"  {source} [{summary}]")
            written += 1
    return "\n".join(lines)


def query_symbol(graph, symbol: str, limit: int = 40) -> str:
    """Render a compact exact-symbol neighborhood without collapsing edges."""
    candidates = resolve_exact(graph, symbol)
    if not candidates:
        return f"NO EXACT MATCH: {symbol}"
    records = []
    seen = set()
    for node_id in candidates:
        node_data = graph.nodes[node_id]
        incoming = (graph.in_edges(node_id, keys=True, data=True)
                    if graph.is_directed() else ())
        outgoing = (graph.out_edges(node_id, keys=True, data=True)
                    if graph.is_directed()
                    else graph.edges(node_id, keys=True, data=True))
        for source, target, _key, data in incoming:
            relation = str(data.get("relation", "related")).lower()
            key = ("IN", relation, source)
            if key not in seen:
                seen.add(key)
                records.append((RELATION_COST.get(relation, 2.5), "IN", relation,
                                str(source), source, data))
        for source, target, _key, data in outgoing:
            relation = str(data.get("relation", "related")).lower()
            other = target if source == node_id else source
            key = ("OUT", relation, other)
            if key not in seen:
                seen.add(key)
                records.append((RELATION_COST.get(relation, 2.5), "OUT", relation,
                                str(other), other, data))

    records.sort()
    lines = [f"Exact symbol: {symbol}"]
    for node_id in candidates[:5]:
        data = graph.nodes[node_id]
        lines.append(f"NODE {_label(node_id, data)} [src={_source(data)}]")
    for _cost, direction, relation, _other_id, other, data in records[:limit]:
        other_data = graph.nodes[other]
        confidence = data.get("confidence", "")
        suffix = f" [{confidence}]" if confidence else ""
        arrow = f"--{relation}{suffix}-->" if direction == "OUT" else f"<--{relation}{suffix}--"
        lines.append(f"{direction} {arrow} {_label(other, other_data)} "
                     f"[src={_source(other_data)}]")
    if len(records) > limit:
        lines.append(f"TRUNCATED: {len(records) - limit} more links")
    return "\n".join(lines)


def _out_edges(graph, node_id) -> list[tuple]:
    """(source, target, data) for every edge leaving *node_id* (every incident
    edge, for an undirected graph)."""
    if graph.is_directed():
        return list(graph.out_edges(node_id, data=True))
    return list(graph.edges(node_id, data=True))


def _field_line(field: dict) -> str:
    extras = [str(field[k]) for k in ("data_type",) if field.get(k)]
    if field.get("value_set"):
        extras.append(f"value_set={field['value_set']}")
    if field.get("default") is not None:
        extras.append(f"default={field['default']}")
    flag = "O" if field.get("optional") else "R"
    return f"    {flag}  {field['xpath']}" + (f"  ({', '.join(extras)})" if extras else "")


def query_fields(graph, symbol: str, xpath: str | None = None, limit: int = 60) -> str:
    """Render ORE_Forge's field mapping for *symbol*, with its links: the
    fields the entry takes, the XSD type that validates them and the class
    that parses them (fieldmap_link.py).

    *symbol* names an entry (its name, TradeType, XML node or class name) or a
    class an entry maps to - `FxForward` finds the FX Forward entry either way.
    *xpath* keeps only the fields whose XPath contains it. R/O is required/
    optional; every link carries its confidence, so a class that only ORE_Forge
    vouches for (INFERRED) reads differently from one ORE's own registry
    confirms (EXTRACTED)."""
    wanted = symbol.casefold()
    entries = []
    for node_id, data in graph.nodes(data=True):
        if data.get("repo") != "OREFieldmap" or data.get("kind") != "entry":
            continue
        names = {str(data.get(key, "")).casefold()
                 for key in ("entry", "trade_type", "xml_node", "cpp_class_name")}
        linked = {_label(target, graph.nodes[target]).casefold()
                  for _s, target, edge in _out_edges(graph, node_id)
                  if str(edge.get("relation", "")).lower() == "maps_to_class"}
        if wanted in names or wanted in linked:
            entries.append((data.get("label", node_id), node_id, data))
    if not entries:
        return f"NO FIELD MAPPING: {symbol}"

    lines = [f"Field mapping for: {symbol}"]
    remaining = limit
    truncated = False
    for label, node_id, data in sorted(entries):
        header = f"ENTRY {label}  ({data.get('domain')}"
        if data.get("xml_node"):
            header += f"; XML node {data['xml_node']}"
        if data.get("asset_class"):
            header += f"; {data['asset_class']}"
        lines.append(header + ")")
        for _s, target, edge in sorted(_out_edges(graph, node_id),
                                       key=lambda e: (str(e[2].get("relation")), str(e[1]))):
            relation = str(edge.get("relation", "")).lower()
            if relation not in FIELDMAP_RELATIONS:
                continue
            target_data = graph.nodes[target]
            kind = "class " if relation == "maps_to_class" else "schema"
            detail = edge.get("via") or edge.get("xsd_type") or ""
            anchor = " (file-level anchor)" if edge.get("anchor") == "file" else ""
            lines.append(
                f"  {kind}: {_label(target, target_data)} [src={_source(target_data)}]  "
                f"{edge.get('confidence', '')} via {edge.get('context', '')}"
                + (f" ({detail})" if detail else "") + anchor
                + (f" [{edge['role']}]" if edge.get("role") else ""))

        groups = ([("", data.get("fields") or [])] if "fields" in data else
                  [(f"{c['model']} / {c['engine']}", c.get("fields") or [])
                   for c in data.get("combinations") or []])
        for name, fields in groups:
            shown = [f for f in fields if not xpath or xpath.casefold() in f["xpath"].casefold()]
            required = sum(1 for f in shown if not f.get("optional"))
            title = (f"  {name}: " if name else "  ") + \
                f"{len(shown)} field(s), {required} required" + \
                (f" (of {len(fields)}; filtered on {xpath!r})" if xpath else "")
            lines.append(title)
            printed = shown[:remaining] if remaining > 0 else []
            lines.extend(_field_line(field) for field in printed)
            remaining -= len(printed)
            truncated = truncated or len(printed) < len(shown)
    if truncated:
        lines.append(f"TRUNCATED: more than {limit} fields - narrow with --xpath, a more "
                     "specific symbol, or raise --limit")
    return "\n".join(lines)


def _flow_category(label: str, source: str) -> str | None:
    lowered_label = label.casefold()
    lowered_source = source.casefold()
    if lowered_label.endswith("engine"):
        return "pricing engines"
    if lowered_label.endswith(("builder", "model")):
        return "builders/models"
    if ("/instruments/" in lowered_source and label[:1].isupper()
            and "::" not in label):
        return "instruments"
    return None


def query_flow(graph, symbol: str, max_hops: int = 4,
               per_category: int = 3) -> str:
    """Discover implementation endpoints and paths without guessing labels."""
    qualified = f"{symbol}::build" if "::" not in symbol else symbol
    starts = resolve_exact(graph, qualified)
    start_name = qualified
    if not starts:
        starts = resolve_exact(graph, symbol)
        start_name = symbol
    if not starts:
        return f"NO EXACT MATCH: {symbol}"

    search_graph = graph.to_undirected(as_view=True)
    frontier = [(0.0, 0, str(node_id), node_id, [node_id], False)
                for node_id in starts]
    heapq.heapify(frontier)
    best = {node_id: (0.0, 0) for node_id in starts}
    candidates: dict[str, list[tuple[float, int, str, list]]] = {
        "instruments": [], "builders/models": [], "pricing engines": []}
    while frontier:
        cost, hops, _order, node_id, path, meaningful = heapq.heappop(frontier)
        if (cost, hops) > best.get(node_id, (float("inf"), max_hops + 1)):
            continue
        if hops and meaningful:
            data = graph.nodes[node_id]
            label = _label(node_id, data)
            category = _flow_category(label, _source(data))
            if category:
                candidates[category].append(
                    (cost, len(path), str(node_id), path))
        if hops >= max_hops:
            continue
        for neighbor in search_graph.neighbors(node_id):
            edge, _reversed = _edge_data(graph, node_id, neighbor)
            relation = str(edge.get("relation", "")).lower()
            if relation not in FLOW_RELATIONS:
                continue
            next_cost = cost + _weight(
                node_id, neighbor,
                search_graph.get_edge_data(node_id, neighbor) or {})
            next_state = (next_cost, hops + 1)
            if next_state >= best.get(neighbor, (float("inf"), max_hops + 1)):
                continue
            best[neighbor] = next_state
            next_meaningful = meaningful or relation in (
                "constructs", "uses", "registers")
            heapq.heappush(frontier, (
                next_cost, hops + 1, str(neighbor), neighbor,
                path + [neighbor], next_meaningful))

    lines = [f"Implementation flow from: {start_name}"]
    for category in ("instruments", "builders/models", "pricing engines"):
        lines.append(f"{category.upper()}:")
        ranked = sorted(candidates[category])[:per_category]
        if not ranked:
            lines.append("  NO ENDPOINT FOUND")
            continue
        for _cost, _length, _node_id, path in ranked:
            first = graph.nodes[path[0]]
            lines.append(f"  NODE {_label(path[0], first)} [src={_source(first)}]")
            for source, target in zip(path, path[1:]):
                edge, reversed_edge = _edge_data(graph, source, target)
                relation = edge.get("relation", "related")
                confidence = edge.get("confidence", "")
                suffix = f" [{confidence}]" if confidence else ""
                target_data = graph.nodes[target]
                arrow = "<--" if reversed_edge else "--"
                end = "--" if reversed_edge else "-->"
                lines.append(
                    f"    {arrow}{relation}{suffix}{end} "
                    f"{_label(target, target_data)} [src={_source(target_data)}]")
    return "\n".join(lines)

# --- answering a prose question ------------------------------------------
#
# Why this exists rather than delegating to graphify's `query_graph`: that
# seeder matches question words against node labels one token at a time and
# never composes adjacent ones, so "yield curve" cannot reach `YieldCurve`,
# and an exact hit on a common member name (`engine`, `validate`, `yield` are
# all real symbols here) outranks a substring hit on the class that actually
# answers the question. Measured over the bench rubric, that accounted for 60
# of 68 unreachable nodes. The fix below inverts the two: adjacent words are
# joined before matching, and a match on a class outranks a match on a member.

_QUESTION_STOPWORDS = frozenset("""
a an the and or of for to in on is are was were be been being do does did done
how what which who whom whose when where why it its this that these those with
from by as at into about over under can could should would will shall may not
""".split())

_WORD_RE = re.compile(r"\w+")
_TOKEN_RE = re.compile(r"\w+|[^\w\s]")

#: (tier, node is class-like) -> seed score. The ordering is the whole point:
#: a class reached by a prefix (`sensitivity` -> `SensitivityAnalysis`) must
#: beat a member matched exactly (`sensitivity` the field), which is the
#: inversion graphify's exact-match bonus gets wrong for prose questions.
_TIER_SCORE = {
    ("phrase", True): 120, ("phrase", False): 90,
    ("token", True): 60, ("token", False): 12,
    ("prefix", True): 40, ("prefix", False): 10,
    ("infix", True): 15, ("infix", False): 4,
    # A question can name a place rather than a symbol ("core math utilities"),
    # where the only handle is the path the answer lives under.
    ("source", True): 30, ("source", False): 25,
    ("alias", True): 200, ("alias", False): 200,
}
_MAX_PHRASE = 4
_SOURCE_SEEDS_PER_PROBE = 5

#: Domain concepts whose name shares no substring with the code that implements
#: them, so no lexical rule can bridge them: ORE computes XVA in `PostProcess`,
#: not in anything called "xva". Keys are word runs in the question; values are
#: labels to seed. This is ORE knowledge, not a per-question answer key - a
#: concept here should hold for any phrasing that mentions it, which is what
#: `tests/test_query_alias.py` checks against paraphrases.
_CONCEPT_SEEDS = {
    "xva": ("PostProcess", "ValuationEngine", "NettingSetManager"),
    "cva": ("PostProcess", "ValuationEngine"),
    "exposure": ("PostProcess", "ValuationEngine"),
    "initial margin": ("DynamicInitialMarginCalculator", "SimmCalculator"),
    "simm": ("SimmCalculator", "SimmConfiguration", "CrifRecord"),
    "sensitivity": ("SensitivityAnalysis", "SensitivityScenarioGenerator",
                    "SensitivityScenarioData"),
    "scenario": ("ScenarioGenerator", "ScenarioSimMarket"),
    "simulation": ("ScenarioSimMarket", "CrossAssetModelScenarioGenerator"),
    "stress": ("StressScenarioGenerator", "StressTestScenarioData"),
    "american monte carlo": ("AmcCalculator", "McMultiLegBaseEngine",
                             "AMCValuationEngine"),
    "amc": ("AmcCalculator", "AMCValuationEngine"),
    "bootstrap": ("PiecewiseYieldCurve", "IterativeBootstrap", "YieldCurve"),
    "yield curve": ("YieldCurve", "YieldCurveConfig", "YieldCurveSegment"),
    "default curve": ("DefaultCurve", "DefaultCurveConfig"),
    "day count": ("DayCounter",),
    "calendar": ("Calendar", "TARGET"),
    "payment dates": ("Schedule", "MakeSchedule", "DateGeneration"),
    "cms spread": ("CmsSpreadCoupon", "LognormalCmsSpreadPricer"),
    "bermudan": ("NumericLgmSwaptionEngine", "TreeSwaptionEngine"),
    "lgm": ("LgmBuilder", "IrLgm1fParametrization"),
    "hull white": ("HullWhite", "HullWhiteProcess"),
    "sabr": ("SABRInterpolation", "SabrSmileSection",
             "SabrInterpolatedSmileSection"),
    "binomial": ("BinomialTree", "BinomialVanillaEngine"),
    "stochastic process": ("StochasticProcess", "PathGenerator",
                           "EulerDiscretization"),
    "interpolate": ("Interpolation", "InterpolatedZeroCurve"),
    "leg convention": ("IRSwapConvention", "Convention"),
    "netting set": ("NettingSetDefinition", "CollateralExposureHelper"),
    "collateral": ("CollateralExposureHelper", "NettingSetDefinition"),
    "csa": ("NettingSetDefinition", "CollateralExposureHelper"),
    "pnl explain": ("PnlExplainReport", "PnlExplainAnalytic"),
    "entry point": ("OREApp",),
}


def _norm_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def _is_class(data: dict) -> bool:
    return bool(data.get("_callable_class"))


def _question_terms(question: str) -> list[str]:
    terms = _WORD_RE.findall(question.lower())
    content = [t for t in terms if t not in _QUESTION_STOPWORDS and len(t) > 1]
    return content or terms


def _norm_index(graph) -> dict[str, list]:
    index = graph.graph.get("_norm_index")
    if index is None:
        index = {}
        for node_id, data in graph.nodes(data=True):
            key = _norm_key(data.get("norm_label") or _label(node_id, data))
            if key:
                index.setdefault(key, []).append(node_id)
        graph.graph["_norm_index"] = index
    return index


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


def _word_matches(term: str, word: str) -> bool:
    if len(word) < 4:
        return term == word
    return term.startswith(word) or _stem(term) == _stem(word)


def _mentions(terms: list[str], concept: str) -> bool:
    """Whether the question says *concept*, allowing inflected words.

    Whole-word matching would miss "sensitivities" for `sensitivity` (the plural
    is not a prefix - y becomes ies) and "bootstrapping" for `bootstrap`, which
    is how the paraphrase suite caught this. Keys shorter than four characters
    match exactly, so `amc` does not fire on `amcalculator`.
    """
    wanted = concept.split()
    return any(
        all(_word_matches(term, word)
            for term, word in zip(terms[start:start + len(wanted)], wanted))
        for start in range(len(terms) - len(wanted) + 1))


def _source_index(graph) -> dict[str, list]:
    """Path-component stem -> node ids, for questions that name a place."""
    index = graph.graph.get("_source_index")
    if index is None:
        index = {}
        for node_id, data in graph.nodes(data=True):
            source = str(data.get("source_file") or "")
            for part in re.split(r"[^A-Za-z0-9]+", source):
                key = part.lower()
                if len(key) >= 3:
                    index.setdefault(key, []).append(node_id)
        graph.graph["_source_index"] = index
    return index


def _probes(terms: list[str]) -> list[tuple[str, str]]:
    """Every word run in the question, longest first, as (tier, joined)."""
    out = []
    for size in range(min(_MAX_PHRASE, len(terms)), 1, -1):
        for i in range(len(terms) - size + 1):
            out.append(("phrase", "".join(terms[i:i + size])))
    out += [("token", t) for t in terms]
    return out


def resolve_question(graph, question: str, limit: int = 6) -> list:
    """Seed nodes for a prose question, best first."""
    index = _norm_index(graph)
    terms = _question_terms(question)
    probes = _probes(terms)
    if not probes:
        return []

    scored: dict = {}

    def offer(node_id, tier: str, key: str):
        data = graph.nodes[node_id]
        score = _TIER_SCORE[(tier, _is_class(data))]
        if data.get("source_file"):
            score += 2
        if len(key) >= 10:
            score += 2
        if scored.get(node_id, (0,))[0] < score:
            scored[node_id] = (score, key)

    for concept, wanted in _CONCEPT_SEEDS.items():
        if not _mentions(terms, concept):
            continue
        for label in wanted:
            for node_id in index.get(_norm_key(label), ()):
                offer(node_id, "alias", _norm_key(label))

    exact = {p for _tier, p in probes}
    for tier, probe in probes:
        for node_id in index.get(probe, ()):
            offer(node_id, tier, probe)
    # One pass for the fuzzy tiers, since scanning ~90k keys per probe is the
    # only expensive part of seeding.
    for key, node_ids in index.items():
        if key in exact:
            continue
        for _tier, probe in probes:
            if len(probe) < 4 or len(key) <= len(probe):
                continue
            if key.startswith(probe):
                tier = "prefix"
            elif probe in key:
                tier = "infix"
            else:
                continue
            for node_id in node_ids:
                offer(node_id, tier, key)
            break

    sources = _source_index(graph)
    for _tier, probe in probes:
        hits = sources.get(probe)
        if not hits:
            continue
        best = sorted(hits, key=lambda n: (
            not _is_class(graph.nodes[n]),
            len(str(graph.nodes[n].get("source_file") or "")),
            str(n)))[:_SOURCE_SEEDS_PER_PROBE]
        for node_id in best:
            offer(node_id, "source", probe)

    if not scored:
        return []
    ranked = sorted(scored.items(),
                    key=lambda kv: (-kv[1][0], len(kv[1][1]), str(kv[0])))
    floor = ranked[0][1][0] * 0.25
    seeds, seen = [], set()
    for node_id, (score, key) in ranked:
        if len(seeds) >= limit or score < floor:
            break
        if key in seen:
            continue
        seen.add(key)
        seeds.append(node_id)
    return seeds


def _neighbours(graph, node_id) -> list:
    """Adjacency regardless of direction, so this works on the merged graph as
    graphify loads it (undirected) and as `load_path_graph` does (directed)."""
    if graph.is_directed():
        return list(graph.successors(node_id)) + list(graph.predecessors(node_id))
    return list(graph.neighbors(node_id))


def _reach(graph, seeds: list, depth: int, mode: str) -> dict:
    """node id -> hops from the nearest seed, over edges in either direction."""
    seen = {node_id: 0 for node_id in seeds}
    frontier = list(seeds)
    for hop in range(1, depth + 1):
        nxt = []
        for node_id in frontier:
            neighbours = _neighbours(graph, node_id)
            if mode == "dfs":
                neighbours.sort(key=str)
            for neighbour in neighbours:
                if neighbour not in seen:
                    seen[neighbour] = hop
                    nxt.append(neighbour)
        frontier = nxt
        if not frontier:
            break
    return seen


def query_question(graph, question: str, *, mode: str = "bfs", depth: int = 3,
                   token_budget: int = 2000) -> str:
    """Answer a prose question as a compact, budgeted list of nodes.

    Output is the same `NODE <label> [src=... loc=... community=...]` shape
    graphify's `query_graph` emits, so callers and the bench rubric parse both
    identically.
    """
    seeds = resolve_question(graph, question)
    if not seeds:
        return f"NO MATCH for {question!r}"
    reached = _reach(graph, seeds, max(1, min(int(depth), 6)), mode)

    # Discovery order, not "classes first": a question like "how is a swap
    # priced" needs `Swap::build` and `Swap::fromXML` as much as the class, and
    # promoting every class ahead of them pushes the methods past the budget.
    ordered = list(reached)
    head = (f"Traversal: {mode.upper()} depth={depth} | Start: "
            f"{[_label(s, graph.nodes[s]) for s in seeds]} | "
            f"{len(ordered)} nodes found")
    lines, used, shown = [], len(_TOKEN_RE.findall(head)), 0
    for node_id in ordered:
        data = graph.nodes[node_id]
        line = (f"NODE {_label(node_id, data)} "
                f"[src={data.get('source_file', '')} "
                f"loc={data.get('source_location', '')} "
                f"community={data.get('community_name', '')}]")
        cost = len(_TOKEN_RE.findall(line))
        if used + cost > token_budget and shown:
            break
        lines.append(line)
        used += cost
        shown += 1
    out = [head, ""]
    if shown < len(ordered):
        out += [f"[!] TRUNCATED: showing {shown} of {len(ordered)} nodes "
                f"(~{token_budget}-token budget).", ""]
    out += lines
    return "\n".join(out)


def merge_answers(primary: str, secondary: str, token_budget: int = 2000) -> str:
    """Interleave two answers' nodes under a single budget, best-first on both.

    The two seeders reach substantially different nodes - measured over the
    bench rubric, graphify's reaches 51 of 119 required nodes and this module's
    70, but together they reach 85 - so the useful thing is not to choose
    between them but to spend one budget across both. Strict alternation keeps
    each side's own ranking and needs no cross-engine score, which there is no
    principled way to compute.
    """
    def nodes(text: str) -> list[str]:
        return [line for line in text.splitlines() if line.startswith("NODE ")]

    # Reciprocal-rank fusion. Strict alternation spends half the budget on each
    # side, which drops nodes either side ranked mid-list - it cost `LegData` on
    # "how is a swap priced". Summing 1/(k+rank) keeps each side's top picks and
    # additionally lifts anything both sides found, without needing a score that
    # means the same thing in both engines.
    k = 10
    fused: dict[str, list] = {}
    for side in (nodes(primary), nodes(secondary)):
        for rank, line in enumerate(side):
            # Label *and* file: one label can name several nodes (`LegData` is
            # both a stub with no source and the real class), and collapsing
            # them keeps whichever ranked higher, which is not the one asked for.
            key = line.split(" loc=", 1)[0]
            entry = fused.setdefault(key, [0.0, len(fused), line])
            entry[0] += 1.0 / (k + rank)

    lines, used = [], 0
    for _key, (score, order, line) in sorted(
            fused.items(), key=lambda kv: (-kv[1][0], kv[1][1])):
        cost = len(_TOKEN_RE.findall(line))
        if used + cost > token_budget and lines:
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


def query_graph_text(graph, question: str, *, mode: str = "bfs", depth: int = 3,
                     token_budget: int = 2000,
                     graphify_answer: str | None = None) -> str:
    """The answer this project serves: graphify's retrieval merged with ours.

    `graphify_answer` lets a caller that has already run graphify's retrieval
    (the MCP server, which gets it from the handler it wraps) pass it in rather
    than pay for the traversal twice.
    """
    base = graphify_answer
    if base is None:
        from graphify import serve as _graphify
        base = _graphify._query_graph_text(graph, question, mode=mode,
                                           depth=depth,
                                           token_budget=token_budget)
    ours = query_question(graph, question, mode=mode, depth=depth,
                          token_budget=token_budget)
    head = (f"Question: {question}\n"
            f"Traversal: {mode.upper()} depth={depth} | merged graphify + oregraph seeds")
    return head + "\n\n" + merge_answers(base, ours, token_budget)
