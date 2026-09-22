"""Task-oriented retrieval over a merged ORE graph."""
from __future__ import annotations

import json
import heapq
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