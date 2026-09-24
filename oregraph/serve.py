"""MCP server for the ORE graph.

Serves graphify's tools unchanged except `query_graph`, which is answered by
`query.query_graph_text` - graphify's retrieval merged with this project's. The
reason is measured: over the bench rubric graphify's seeding reaches 51 of 119
required nodes and ours 70, but the two reach different nodes and together
reach 85. Seeding is the weak point for prose questions, because query words
are matched against labels one at a time and an exact hit on a common member
name (`engine`, `validate`) outranks the class that answers the question.

Nothing in graphify is modified. Its server is built as usual and the one tool
is intercepted; every other tool, and every code path this does not understand
(a `project_path`, a `context_filters` argument), is delegated untouched.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .query import query_graph_text

_TOOL = "query_graph"
_graphs: dict[tuple, object] = {}


def _share_graph_loads() -> None:
    """Make graphify's loader memoize, so its server and our retrieval share one
    graph instead of holding a copy each (~120MB of JSON, several hundred MB in
    memory). Keyed on the file's mtime and size, which is what graphify's own
    context cache keys on, so a rebuilt graph still reloads."""
    from graphify import serve as _graphify

    if getattr(_graphify._load_graph, "_oregraph_shared", False):
        return
    original = _graphify._load_graph

    def shared(graph_path: str):
        resolved = Path(graph_path).resolve()
        try:
            stat = resolved.stat()
            key = (str(resolved), stat.st_mtime_ns, stat.st_size)
        except OSError:
            return original(graph_path)
        if key not in _graphs:
            _graphs.clear()
            _graphs[key] = original(graph_path)
        return _graphs[key]

    shared._oregraph_shared = True
    _graphify._load_graph = shared


def _answer_text(result):
    """The text payload of a CallToolResult, or None if it is shaped otherwise."""
    content = getattr(getattr(result, "root", result), "content", None)
    if content and getattr(content[0], "type", None) == "text":
        return content[0].text
    return None


def build_server(graph_path: str):
    """graphify's MCP server with `query_graph` answered by the merged retriever."""
    from graphify import serve as _graphify
    from mcp import types

    _share_graph_loads()
    server = _graphify._build_server(graph_path)
    original = server.request_handlers.get(types.CallToolRequest)
    if original is None:  # pragma: no cover - graphify changed shape
        raise RuntimeError(
            "graphify's MCP server registered no CallToolRequest handler; "
            "oregraph.serve cannot wrap query_graph. Serve graphify directly "
            "or update this module.")

    async def call_tool(request):
        result = await original(request)
        params = request.params
        arguments = dict(params.arguments or {})
        question = arguments.get("question")
        # Only the plain case is ours. A different graph or a context filter is
        # graphify's alone, and silently dropping either would be worse than
        # keeping its answer.
        if (params.name != _TOOL or not question
                or arguments.get("project_path")
                or arguments.get("context_filters")):
            return result
        base = _answer_text(result)
        if base is None:
            return result
        graph = _graphify._load_graph(graph_path)
        merged = query_graph_text(
            graph, question,
            mode=str(arguments.get("mode") or "bfs"),
            depth=int(arguments.get("depth") or 3),
            token_budget=int(arguments.get("token_budget") or 2000),
            graphify_answer=base)
        result.root.content[0].text = merged
        return result

    server.request_handlers[types.CallToolRequest] = call_tool
    return server


def serve(graph_path: str | None = None) -> None:
    from graphify import serve as _graphify

    graph_path = graph_path or _graphify._default_graph_json()
    import asyncio

    from mcp.server.stdio import stdio_server

    server = build_server(graph_path)

    async def main() -> None:
        async with stdio_server() as streams:
            await server.run(streams[0], streams[1],
                             server.create_initialization_options())

    _graphify._filter_blank_stdin()
    asyncio.run(main())


if __name__ == "__main__":
    serve(sys.argv[1] if len(sys.argv) > 1 else None)
