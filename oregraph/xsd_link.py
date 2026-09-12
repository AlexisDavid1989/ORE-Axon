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

This module recovers that relationship the same way a person would: by
matching names. It's a heuristic, not an extraction - unlike link.py's
#include scan (byte-for-byte ground truth) or symbol_links.py's regex-over-
source-text (a literal reference in the code), there's nothing in either
XSD or C++ that explicitly declares "this class implements this schema
element". Confidence is scored lower accordingly (see LINK_CONFIDENCE).

Scope, deliberately narrow for this first pass
-----------------------------------------------
- Only `xsd/instruments.xsd` nodes are considered (trade-field definitions -
  the schemas most directly tied to a parsing C++ class; conventions.xsd,
  curveconfig.xsd etc. have far more paraphrased, non-literal LLM labels
  and would need their own matching strategy).
- Only OREData classes are considered as match targets. Matching against
  the whole graph picks up unrelated same-named classes elsewhere (e.g.
  instruments.xsd's `varianceSwapData` -> stripped to `varianceSwap` ->
  matches QuantLib's VarianceSwap *pricing instrument*, not OREData's
  `VarSwap` *trade wrapper* - the two are different things with different
  names, and only the OREData-scoped search avoids that false match).
- A name that matches more than one OREData class (after the tie-break
  below) is left unmatched rather than guessed at; measured on the corpus
  this pass currently runs against, that tie-break resolves every
  ambiguous case, so in practice nothing is silently dropped here today,
  but nothing here assumes that stays true as the schema grows.
"""
from __future__ import annotations

import re
from collections import defaultdict

#: "name (complexType)", "name (top-level complexType)", "name (element, ...)"
#: or the parenthesis-free "name complexType" - the two label shapes actually
#: observed in semantic-chunks/xsd/*.json for instruments.xsd nodes.
_TYPE_LABEL_RE = re.compile(
    r"^([A-Za-z][\w]*)\s*(?:\((?:top-level )?(?:complexType|simpleType|element)|"
    r"(?:complexType|simpleType|element)\b)")

LINK_CONFIDENCE = "MATCHED"
LINK_CONFIDENCE_SCORE = 0.85


def _extract_type_names(nodes: list[dict]) -> dict[str, str]:
    """xsd node id -> literal type/element name, for instruments.xsd nodes only."""
    names: dict[str, str] = {}
    for n in nodes:
        if n.get("repo") != "OREXsd":
            continue
        if n.get("source_file") != "xsd/instruments.xsd":
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


def link_xsd(nodes: list[dict]) -> tuple[list[dict], dict]:
    """Return (edges, stats). *nodes* is the fully namespaced merged node list
    (post-merge.py-namespacing, same convention as symbol_links.link_symbols) -
    ids on returned edges are ready to use as-is, no remapping needed."""
    xsd_names = _extract_type_names(nodes)
    by_name = _index_ore_classes(nodes)

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

    edges.sort(key=lambda e: (e["source"], e["target"]))
    return edges, {
        "instruments_xsd_type_names": len(xsd_names),
        "xsd_edges": len(edges),
        "matched_exact": len(edges) - matched_via_stem,
        "matched_via_stripped_data_suffix": matched_via_stem,
        "unmatched": len(unmatched),
        "unmatched_names": sorted(unmatched),
    }
