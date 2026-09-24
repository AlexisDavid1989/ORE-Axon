"""Recover explicit symbol relationships that chunked AST extraction loses."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

from .link import INCLUDE_RE, SOURCE_EXTS


FUNCTION_RE = re.compile(
    r"(?P<class>[A-Za-z_]\w*)::(?P<method>~?[A-Za-z_]\w*)\s*"
    r"\([^;{}]*\)\s*(?:const\s*)?(?:override\s*)?\{")
CONSTRUCT_RE = re.compile(
    r"(?:make_shared\s*<\s*|\bnew\s+)(?:[A-Za-z_]\w*::)*"
    r"(?P<target>[A-Za-z_]\w*)")
TYPED_CAST_RE = re.compile(
    r"(?:dynamic_pointer_cast|static_pointer_cast)\s*<\s*"
    r"(?:[A-Za-z_]\w*::)*(?P<target>[A-Za-z_]\w*)")
QUALIFIED_CALL_RE = re.compile(
    r"(?P<class>[A-Za-z_]\w*)::(?P<method>[A-Za-z_]\w*)\s*\(")
REGISTER_RE = re.compile(
    r"ORE_REGISTER_(?P<kind>TRADE|ENGINE)_BUILDER\s*\(\s*"
    r"(?P<target>[A-Za-z_]\w*)")
LINE_RE = re.compile(r"(?:^|[^0-9])L?(\d+)(?:[^0-9]|$)")
# `class Foo {`, `struct QL_EXPORT Foo : public Bar {` - a class *body*, not a
# forward declaration (no `{`) or a template parameter (`class T>`).
CLASS_RE = re.compile(
    r"\b(?:class|struct)\s+(?:[A-Z_][A-Z0-9_]*\s+)?(?P<name>[A-Za-z_]\w*)"
    r"\s*(?:final\s+)?(?::[^;{]*)?\{")


def _label(node: dict) -> str:
    for key in ("label", "name", "title"):
        if node.get(key):
            return str(node[key])
    return str(node.get("local_id") or node.get("id", "")).rsplit("::", 1)[-1]


def _line(node: dict) -> int | None:
    for key in ("line", "start_line", "line_start", "location", "loc"):
        value = node.get(key)
        if isinstance(value, int):
            return value
        if value:
            match = LINE_RE.search(str(value))
            if match:
                return int(match.group(1))
    return None


def _matching_brace(text: str, opening: int) -> int:
    depth = 0
    state = "code"
    index = opening
    while index < len(text):
        char = text[index]
        nxt = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if char == "/" and nxt == "/":
                state = "line_comment"
                index += 1
            elif char == "/" and nxt == "*":
                state = "block_comment"
                index += 1
            elif char == '"':
                state = "string"
            elif char == "'":
                state = "char"
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return index
        elif state == "line_comment" and char == "\n":
            state = "code"
        elif state == "block_comment" and char == "*" and nxt == "/":
            state = "code"
            index += 1
        elif state in ("string", "char"):
            delimiter = '"' if state == "string" else "'"
            if char == "\\":
                index += 1
            elif char == delimiter:
                state = "code"
        index += 1
    return len(text)


def _function_spans(text: str) -> list[tuple[int, int, str, str]]:
    spans = []
    for match in FUNCTION_RE.finditer(text):
        opening = text.find("{", match.start(), match.end())
        spans.append((opening, _matching_brace(text, opening),
                      match.group("class"), match.group("method")))
    return spans


def _class_spans(text: str) -> list[tuple[int, int, str]]:
    """(opening brace, closing brace, name) for every class or struct body."""
    spans = []
    for match in CLASS_RE.finditer(text):
        if text[:match.start()].rstrip().endswith("enum"):   # `enum class E {`
            continue
        opening = match.end() - 1
        spans.append((opening, _matching_brace(text, opening), match.group("name")))
    return spans


def _source_files(engine: Path, nodes: list[dict]):
    paths = sorted({str(node.get("repo_path")) for node in nodes
                    if node.get("repo_path")})
    for relative in paths:
        path = engine / relative
        if path.is_file() and path.suffix.lower() in SOURCE_EXTS:
            yield relative, path


def _path_stem(path: str) -> str:
    return str(PurePosixPath(path).with_suffix(""))


def link_symbols(engine: Path, nodes: list[dict]) -> tuple[list[dict], dict]:
    """Return high-confidence source-level relationships between symbols."""
    by_label: dict[str, list[dict]] = defaultdict(list)
    by_path: dict[str, list[dict]] = defaultdict(list)
    by_stem_label: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for node in nodes:
        label = _label(node).casefold()
        by_label[label].append(node)
        if node.get("repo_path"):
            node_path = str(node["repo_path"])
            by_path[node_path].append(node)
            by_stem_label[(_path_stem(node_path), label)].append(node)
    include_index: dict[str, set[str]] = defaultdict(set)
    for candidate_path in by_path:
        include_index[candidate_path].add(candidate_path)
        if "/" in candidate_path:
            include_index[candidate_path.split("/", 1)[1]].add(candidate_path)

    def owner(path: str, method: str, line: int) -> dict | None:
        candidates = [node for node in by_path.get(path, [])
                      if _label(node).casefold() == method.casefold()]
        if not candidates and method:
            candidates = by_stem_label.get(
                (_path_stem(path), method.casefold()), [])
        if not candidates:
            return min(by_path.get(path, []),
                       key=lambda node: (len(str(node["id"])), str(node["id"])),
                       default=None)
        return min(candidates, key=lambda node: (
            abs((_line(node) or line) - line), str(node["id"])))

    def class_owner(path: str, name: str, line: int) -> dict | None:
        """The node for class `name` in `path`, for code written inside its body.

        Header-inline code has no `Class::method` span, so it used to fall back
        to the node with the shortest id in the file - which was the main class
        only by luck. A nested `struct Curves` inside `FwdBondEngineBuilder`
        has the shorter id, so once the extractor began emitting nested types
        every construct in that header was attributed to `Curves`.
        """
        named = [node for node in by_path.get(path, [])
                 if _label(node).casefold() == name.casefold()]
        candidates = [node for node in named if node.get("_callable_class")] or named
        return min(candidates, key=lambda node: (
            abs((_line(node) or line) - line), str(node["id"])), default=None)

    def targets(label: str, included: set[str], source_path: str) -> list[dict]:
        candidates = [node for node in by_label.get(label.casefold(), [])
                      if node.get("repo_path") != source_path]
        narrowed = [node for node in candidates
                    if str(node.get("repo_path", "")) in included]
        return sorted(narrowed, key=lambda node: (
            not bool(node.get("repo_path")), len(str(node["id"])), str(node["id"])
        ))[:1]

    edges = []
    seen = set()
    counts: Counter[str] = Counter()
    for relative, path in _source_files(engine, nodes):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        included = set()
        for _delimiter, include in INCLUDE_RE.findall(text):
            suffix = include.replace("\\", "/").lstrip("./")
            included.update(include_index.get(suffix, ()))

        spans = _function_spans(text)
        class_spans = _class_spans(text)
        definitions = [(match.start(), match.end())
                   for match in FUNCTION_RE.finditer(text)]

        def add(match, relation: str, target_label: str, context: str):
            line = text.count("\n", 0, match.start()) + 1
            enclosing = [item for item in spans
                         if item[0] <= match.start() <= item[1]]
            span = max(enclosing, key=lambda item: item[0], default=None)
            if span:
                source = owner(relative, span[3], line)
            else:
                # Innermost class whose braces contain the call.
                scope = max((item for item in class_spans
                             if item[0] <= match.start() <= item[1]),
                            key=lambda item: item[0], default=None)
                source = (class_owner(relative, scope[2], line) if scope else None
                          ) or owner(relative, "", line)
            if source is None:
                return
            for target in targets(target_label, included, relative):
                key = (source["id"], target["id"], relation)
                if key in seen:
                    continue
                seen.add(key)
                edges.append({
                    "source": source["id"],
                    "target": target["id"],
                    "relation": relation,
                    "context": context,
                    "confidence": "RESOLVED",
                    "confidence_score": 0.95,
                    "weight": 1.0,
                    "source_file": relative,
                    "line": line,
                    "_origin": "symbol_link",
                })
                counts[relation] += 1

        for match in CONSTRUCT_RE.finditer(text):
            add(match, "constructs", match.group("target"), "cpp_construction")
        for match in TYPED_CAST_RE.finditer(text):
            add(match, "uses", match.group("target"), "cpp_typed_cast")
        for match in QUALIFIED_CALL_RE.finditer(text):
            if match.group("method") == match.group("class"):
                continue
            if any(start <= match.start() < end for start, end in definitions):
                continue
            add(match, "calls", match.group("method"), "cpp_qualified_call")
        for match in REGISTER_RE.finditer(text):
            add(match, "registers", match.group("target"),
                f"ore_{match.group('kind').lower()}_registration")

    edges.sort(key=lambda edge: (edge["source"], edge["target"], edge["relation"]))
    return edges, {"symbol_edges": len(edges), "by_relation": dict(counts)}