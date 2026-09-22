"""Loader for ORE's field-mapping data: trades, curve configs, conventions and
pricing engines.

ORE_Forge is a separate repo (see docs/FIELDMAP-SOURCE.md) that already
resolves those four domains' XML fields into concrete XPaths - shared
components expanded inline, multi-instance legs indexed (LegData[1],
LegData[2], ...), choice fields (LegDataType -> Fixed/Floating/...) resolved
into their concrete subtree. That resolution logic (ORE_Forge's
UnifiedXPathProvider) is not reimplemented here - this module only reads it,
in place, via ORE_FIELDMAP (see oregraph.config). ORE_Forge's own JSON files
are never vendored, copied, or flattened into this repo: ORE_Forge stays the
source of truth, and a stale snapshot is refreshed by re-running
`oregraph fieldmap`, not by editing anything here.

`snapshot()` + `save()` produce a cached build intermediate; `load()` reads it
back without importing anything from ORE_Forge, which is how `oregraph merge`
consumes it (fieldmap_link.py turns it into graph nodes and edges). Merge never
calls ORE_Forge itself - the snapshot's recorded commit is what the merged
graph is stamped with, and `verify` flags the graph when ORE_Forge has moved on.

Authority: the mapping is ORE_Forge's claim about what ORE accepts, audited
there against fromXML(). fieldmap_link.py does not take it on trust - wherever
ORE's own source can corroborate a link (the TradeType registry, the
conventions dispatch chain, the XSD dispatch blocks) it re-derives it and marks
the edge EXTRACTED, and marks a link INFERRED when ORE_Forge's word is all
there is. Disagreements are reported, not resolved silently.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config as configmod

DOMAINS = ("trade", "curve_config", "convention", "pricing_engine")

#: Bumped whenever the snapshot layout changes, so `load()` refuses an old file
#: with an instruction instead of half-reading it. Format 1 was trade-only
#: (`trade_types` + `nodes_by_trade`).
SNAPSHOT_FORMAT = 2


class FieldmapError(RuntimeError):
    pass


@dataclass(frozen=True)
class FieldmapSnapshot:
    """One build-time read of ORE_Forge's resolved field mapping.

    `domains` maps domain -> entry name -> record. A record is
    {"meta": {...}, "nodes": [...]} for trade / curve_config / convention, and
    {"meta": {...}, "combinations": [{"Model", "Engine", "nodes", ...}]} for
    pricing_engine, whose XML shape (and parameter set) depends on which
    (Model, Engine) pair is chosen - so every valid pair is resolved, not just
    the default. `meta` is the entry's scalar keys (XML_Node_Name, Trade_Type,
    Cpp_Class_Name, ...): the join keys fieldmap_link.py works from.
    """
    source: str
    version: dict
    domains: dict[str, dict[str, dict[str, Any]]]

    def entry_count(self, domain: str) -> int:
        return len(self.domains.get(domain, {}))

    def node_count(self, domain: str) -> int:
        return sum(len(nodes) for record in self.domains.get(domain, {}).values()
                   for nodes in record_node_lists(record))

    @property
    def total_nodes(self) -> int:
        return sum(self.node_count(d) for d in self.domains)


def record_node_lists(record: dict[str, Any]) -> list[list[dict[str, Any]]]:
    """Every resolved node list a record carries: one for most domains, one per
    (Model, Engine) combination for pricing_engine."""
    if "combinations" in record:
        return [combo["nodes"] for combo in record["combinations"]]
    return [record.get("nodes", [])]


# Keyed by fieldmap root so a process that (unusually) points at more than
# one ORE_Forge checkout doesn't cross-contaminate; UnifiedXPathProvider
# itself caches per-instance already, this just avoids re-importing.
_provider_cache: dict[Path, Any] = {}


def _load_provider(fieldmap_root: Path):
    """Import ORE_Forge's UnifiedXPathProvider by path.

    ORE_Forge is not pip-installable today, and even a proper install
    wouldn't include scripts/xpath/ (it's outside the packaged src/ tree) -
    see docs/FIELDMAP-SOURCE.md Step 1b. ORE_Forge's own tooling
    (scripts/mapping/convert_trades.py, scripts/generate_baselines.py, ...)
    reaches this the same way: insert the repo root on sys.path and import
    as if the checkout were the package root. This is the only route that
    works without modifying ORE_Forge.
    """
    cached = _provider_cache.get(fieldmap_root)
    if cached is not None:
        return cached

    root_str = str(fieldmap_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    try:
        from scripts.xpath.unified_xpath_provider import UnifiedXPathProvider
    except ImportError as exc:
        raise FieldmapError(
            f"Could not import UnifiedXPathProvider from {fieldmap_root}.\n"
            "Confirm ORE_FIELDMAP points at an ORE_Forge checkout with "
            "scripts/xpath/unified_xpath_provider.py present."
        ) from exc

    provider = UnifiedXPathProvider(data_dir=fieldmap_root / "data" / "unified")
    _provider_cache[fieldmap_root] = provider
    return provider


def _entry_meta(entry: dict[str, Any]) -> dict[str, Any]:
    """The scalar (and list-of-scalar) keys of a raw entry: the join keys
    (XML_Node_Name, Trade_Type, XSD_Type, Cpp_Class_Name, Cpp_Builders, ...)
    without the Fields/Field_Specs bulk. `description` is dropped - it is long
    LaTeX prose lifted from the User Guide, not a join key."""
    def scalar(v):
        return v is None or isinstance(v, (str, int, float, bool))

    return {k: v for k, v in entry.items()
            if k != "description"
            and (scalar(v) or (isinstance(v, list) and all(scalar(x) for x in v)))}


def _entry_names(provider) -> dict[str, list[str]]:
    """Which entries to enumerate per domain.

    trade / convention / pricing_engine use ORE_Forge's own enumerators.
    curve_config deliberately does not: `get_config_types()` keeps only
    Is_Top_Level entries because that is what its GUI selector shows, but the
    other entries (yield-curve segments, nested types such as PriceInfo) carry
    their own Cpp_Class_Name and resolve on their own through `get_xpath` -
    dropping them would leave those classes with no mapping at all. Every
    entry is enumerated and its Is_Top_Level flag travels in `meta`, so a
    consumer that wants the selector's view can still filter to it.
    """
    return {
        "trade": provider.get_trade_types(),
        "curve_config": sorted(provider.configs["entries"]),
        "convention": provider.get_convention_types(),
        "pricing_engine": provider.get_pricing_engine_types(),
    }


def _resolved_choice(nodes: list[dict[str, Any]], field: str):
    for node in nodes:
        if node.get("is_field") and node.get("xpath") == f"Product/{field}":
            return node.get("value")
    return None


def _pricing_combinations(provider, name: str, entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Resolve every valid (Model, Engine) pair of a pricing-engine product.

    `_build_pricing_engine` silently falls back to the product's default when
    asked for a Model/Engine it does not recognise, so the pair actually
    resolved is read back out of the nodes and recorded as `substituted`
    whenever it differs from the pair requested - a combination that resolved
    to something else would otherwise be indistinguishable from a good one.
    """
    combinations = []
    for combo in entry.get("Valid_Combinations", []):
        model, engine = combo.get("Model"), combo.get("Engine")
        nodes = provider.get_pricing_engine_xpath(name, model, engine)
        record: dict[str, Any] = {"Model": model, "Engine": engine, "nodes": nodes}
        resolved = [_resolved_choice(nodes, "Model"), _resolved_choice(nodes, "Engine")]
        if resolved != [model, engine]:
            record["substituted"] = resolved
        combinations.append(record)
    return combinations


def snapshot(cfg: configmod.Config) -> FieldmapSnapshot:
    """Read every entry of all four domains from ORE_Forge, in one pass.

    Raises FieldmapError if cfg.fieldmap is not set - this is an opt-in
    capability, not a requirement of the core build/merge path.
    """
    if cfg.fieldmap is None:
        raise FieldmapError(
            "No ORE_Forge checkout configured. Set ORE_FIELDMAP to the "
            "ORE_Forge repo root (same pattern as ORE_ENGINE)."
        )
    provider = _load_provider(cfg.fieldmap)
    raw = {"trade": provider.trades, "curve_config": provider.configs,
           "convention": provider.conventions,
           "pricing_engine": provider.pricing_engines}
    names = _entry_names(provider)

    domains: dict[str, dict[str, dict[str, Any]]] = {}
    for domain in DOMAINS:
        entries = raw[domain]["entries"]
        records: dict[str, dict[str, Any]] = {}
        for name in names[domain]:
            record: dict[str, Any] = {"meta": _entry_meta(entries[name])}
            if domain == "pricing_engine":
                record["combinations"] = _pricing_combinations(provider, name, entries[name])
            else:
                record["nodes"] = provider.get_xpath(domain, name)
            records[name] = record
        domains[domain] = records

    return FieldmapSnapshot(
        source=str(cfg.fieldmap),
        version=configmod.fieldmap_version(cfg.fieldmap),
        domains=domains,
    )


def save(snap: FieldmapSnapshot, path: Path) -> None:
    """Cache a snapshot as a build intermediate (cfg.fieldmap_out).

    This is a cache of ORE_Forge's *output*, not a vendored copy of its
    source files - it's derived, disposable, and regenerated by re-running
    snapshot(), the same relationship module_out() has to a chunk's source.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": SNAPSHOT_FORMAT,
        "source": snap.source,
        "version": snap.version,
        "domains": snap.domains,
    }
    path.write_text(json.dumps(payload, indent=1), encoding="utf-8")


def load(path: Path) -> FieldmapSnapshot:
    """Read a snapshot written by save(). Imports nothing from ORE_Forge."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FieldmapError(f"cannot read fieldmap snapshot {path}: {exc}") from exc
    found = payload.get("format", 1)
    if found != SNAPSHOT_FORMAT:
        raise FieldmapError(
            f"{path} is snapshot format {found}; this version reads format "
            f"{SNAPSHOT_FORMAT}. Re-run `python -m oregraph fieldmap`.")
    return FieldmapSnapshot(source=payload["source"], version=payload["version"],
                            domains=payload["domains"])
