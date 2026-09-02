"""Task-oriented retrieval over a merged ORE graph."""
from __future__ import annotations

import json
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
    "references": 1.8,
    "defines": 2.2,
    "includes": 3.0,
    "contains": 3.5,
}
CONFIDENCE_COST = {"RESOLVED": 0.0, "EXTRACTED": 0.2, "INFERRED": 2.5}

IMPACT_RELATIONS = {"calls", "constructs", "registers", "returns", "uses",
                    "inherits", "references"}
BUNDLE_RELATIONS = IMPACT_RELATIONS | {"defines", "imports"}


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
            if neighbor not in seen:
                seen.add(neighbor)
                frontier.append((neighbor, hops + 1))

    grouped: dict[str, list[tuple[str, set[str]]]] = {
        category: [] for category in
        ("trade/data", "builder", "pricing/model", "schema", "tests", "support")
    }
    for source, labels in sorted(files.items()):
        grouped[_bundle_category(source)].append((source, labels))

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