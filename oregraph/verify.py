"""Post-build sanity checks.

Every check here corresponds to a failure that actually occurred in the original
build and produced no error at the time - a graph that looked fine and answered
questions wrongly. They are cheap; run them after every rebuild.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


def _node_label(node: dict) -> str:
    for key in ("label", "name", "title"):
        if node.get(key):
            return str(node[key])
    return str(node.get("local_id") or node.get("id", "")).rsplit("::", 1)[-1]


def _has_relation_path(nodes: list[dict], links: list[dict], start: str,
                   end: str, relations: set[str], max_hops: int,
                   start_source: str | None = None) -> bool:
    starts = {node["id"] for node in nodes
            if _node_label(node).casefold() == start.casefold()
            and (start_source is None or start_source.casefold() in
                str(node.get("repo_path") or node.get("source_file") or "").casefold())}
    ends = {node["id"] for node in nodes
            if _node_label(node).casefold() == end.casefold()}
    adjacency = defaultdict(list)
    for link in links:
        edge_relation = str(link.get("relation", "")).casefold()
        adjacency[link["source"]].append((link["target"], edge_relation))
        adjacency[link["target"]].append((link["source"], edge_relation))
    wanted = {relation.casefold() for relation in relations}
    frontier = [(node_id, 0, frozenset()) for node_id in starts]
    seen = {(node_id, frozenset()) for node_id in starts}
    for node_id, hops, matched in frontier:
        if node_id in ends and wanted <= matched:
            return True
        if hops >= max_hops:
            continue
        for neighbor, edge_relation in adjacency.get(node_id, []):
            next_matched = matched | ({edge_relation} if edge_relation in wanted else set())
            state = (neighbor, frozenset(next_matched))
            if state in seen:
                continue
            seen.add(state)
            frontier.append((neighbor, hops + 1, state[1]))
    return False


def _sample(items: list[str], n: int = 4) -> str:
    more = f" (+{len(items) - n} more)" if len(items) > n else ""
    return "; ".join(items[:n]) + more


def _fieldmap_checks(cfg, graph_meta: dict, nodes: list[dict], links: list[dict],
                     check) -> None:
    """ORE_Forge's field mapping (fieldmap_link.py). It is optional, so its
    absence is only a finding when ORE_FIELDMAP says it should be there - a
    graph quietly built without the mapping it was configured to carry is the
    gap this pass exists to end. Once present, the structure is an error if it
    is inconsistent; everything that reflects ORE_Forge's data (stale, an
    unresolved name, a disagreement with ORE's source) is a warning, because
    those are findings about the mapping, not about the build."""
    from . import config as configmod
    from .fieldmap_link import FIELDMAP_REPO, FIELDMAP_RELATIONS

    fm = graph_meta.get("fieldmap")
    fm_nodes = [n for n in nodes if n.get("repo") == FIELDMAP_REPO]
    if not fm or not fm_nodes:
        if cfg.fieldmap:
            check("fieldmap merged", False,
                  "ORE_FIELDMAP is set but the graph carries no field mapping - run "
                  "`python -m oregraph fieldmap`, then `python -m oregraph merge`",
                  severity="warn")
        return
    per = fm["domains"]
    check("fieldmap merged", True, "; ".join(
        f"{d} {v['entries']} entries/{v['fields']:,} fields" for d, v in per.items()))

    # Structure: what the pass recorded must be what is in the graph. The fields
    # travel as attributes on the entry nodes (they are not nodes of their own -
    # see fieldmap_link.py for why), so a truncated or dropped attribute would
    # leave an entry that answers queries with a fraction of its fields and no
    # error anywhere; the field totals are the check that catches it.
    entries = [n for n in fm_nodes if n.get("kind") == "entry"]
    carried = sum(len(n.get("fields") or []) + sum(len(c.get("fields") or [])
                                                    for c in n.get("combinations") or [])
                  for n in entries)
    combos = sum(len(n.get("combinations") or []) for n in entries)
    edges = [l for l in links if l.get("_origin") == "fieldmap_link"]
    entry_ids = {n["id"] for n in entries}
    problems = []
    for what, have, want in (
            ("entry nodes", len(entries), sum(v["entries"] for v in per.values())),
            ("fields carried on entries", carried, sum(v["fields"] for v in per.values())),
            ("combinations carried", combos, sum(v["combinations"] for v in per.values())),
            ("fieldmap edges", len(edges), fm.get("edges"))):
        if have != want:
            problems.append(f"{what}: {have:,} in graph vs {want:,} recorded")
    # Only entries may be nodes. Field (and combination) nodes were tried and
    # measurably broke retrieval - `oregraph bench` went from identical to 4 of 8
    # answers changed, one of them 2x the tokens - so a later change that turns
    # the fields back into nodes must fail here, not surface as a slow bench
    # regression nobody connects to the fieldmap (see fieldmap_link.py).
    not_entries = [n for n in fm_nodes if n.get("kind") != "entry"]
    if not_entries:
        problems.append(f"{len(not_entries):,} fieldmap node(s) that are not entries - "
                        "fields must be attributes, not nodes: they distort query "
                        "retrieval (fieldmap_link.py explains, `oregraph bench` shows it)")
    stray = [l for l in edges if l["source"] not in entry_ids
             or l.get("relation") not in FIELDMAP_RELATIONS]
    if stray:
        problems.append(f"{len(stray)} fieldmap edge(s) not maps_to_* out of an entry node")
    short_counted = [n["entry"] for n in entries
                     if "fields" in n and n.get("field_count") != len(n["fields"])]
    if short_counted:
        problems.append(f"field_count disagrees with the fields carried on "
                        f"{len(short_counted)} entr(ies): {_sample(short_counted, 3)}")
    check("fieldmap structure", not problems,
          f"{len(entries)} entries carry {carried:,} fields and {combos} combinations; "
          "counts match the pass's own" if not problems else "; ".join(problems))

    stamp = fm.get("snapshot") or {}
    if cfg.fieldmap:
        current = configmod.fieldmap_version(cfg.fieldmap)
        stale = bool(current["commit"]) and current["commit"] != stamp.get("commit")
        short = lambda c: str(c or "?")[:9]
        check("fieldmap snapshot current", not stale and not stamp.get("dirty"),
              f"graph carries ORE_Forge {short(stamp.get('commit'))}"
              + (f", checkout is at {short(current['commit'])} - re-run `python -m "
                 "oregraph fieldmap` then `merge`" if stale else "")
              + (" (snapshot taken from a dirty tree)" if stamp.get("dirty") else ""),
              severity="warn")

    unresolved = [f"{d} {x}" for kind in ("unresolved_class", "unresolved_schema")
                  for d, xs in (fm.get(kind) or {}).items() for x in xs]
    linked = ", ".join(f"{d} {v['class_linked']}/{v['entries']} class + "
                       f"{v['schema_linked']}/{v['entries']} schema" for d, v in per.items())
    anchors = fm.get("schema_anchor") or {}
    detail = linked + (f"; schema anchored at the type's own node for "
                       f"{anchors.get('type', 0)}, at the file's summary node for "
                       f"{anchors.get('file', 0)}" if anchors else "")
    if unresolved:
        detail += f"; {len(unresolved)} unresolved: {_sample(unresolved)}"
    check("fieldmap entries linked to code and schema", not unresolved, detail,
          severity="warn")

    # Where ORE's own source disagrees with ORE_Forge, or ORE_Forge's own data
    # is internally odd. Each is a finding to hand to whoever owns the mapping.
    found = {"class": fm.get("class_disagreements") or [],
             "schema": fm.get("schema_disagreements") or [],
             "unsupported class claim": fm.get("unsupported_claims") or [],
             "substituted combination": fm.get("substituted_combinations") or [],
             "duplicate xpath": fm.get("duplicate_xpaths") or []}
    flat = [f"[{k}] {x}" for k, xs in found.items() for x in xs]
    check("fieldmap agrees with ORE's source", not flat,
          "no disagreements between ORE_Forge's claims and the registry, dispatch "
          "chain and schema" if not flat else f"{len(flat)}: {_sample(flat)}",
          severity="warn")


def verify(cfg) -> dict:
    checks: list[dict] = []

    def check(name, ok, detail, severity="error"):
        checks.append({"check": name, "ok": bool(ok), "detail": detail,
                       "severity": severity})

    path = cfg.merged_graph
    if not path.exists():
        return {"checks": [{"check": "merged graph exists", "ok": False,
                            "detail": f"{path} not found - run `build`"}]}

    g = json.loads(path.read_text(encoding="utf-8"))
    nodes, links = g["nodes"], g["links"]
    ids = {n["id"] for n in nodes}
    check("merged graph exists", True, str(path))
    ore = (g.get("graph") or {}).get("ore")

    # The field-mapping nodes (fieldmap_link.py) get a generated community name
    # each - "FX Forward (trade mapping)" - and none of them is a curated name.
    # Counting them in checks 4/4b/5 would push the retention rate past 100% and
    # let a real collapse of the curated names hide behind ~400 generated ones.
    from .fieldmap_link import FIELDMAP_REPO
    curated_nodes = [n for n in nodes if n.get("repo") != FIELDMAP_REPO]

    # 1. every edge endpoint resolves
    dangling = sum(1 for l in links if l["source"] not in ids or l["target"] not in ids)
    check("no dangling edges", dangling == 0, f"{dangling:,} dangling")

    # 2. cross-module edges exist (the failure that made the old graph 12 islands)
    repo = {n["id"]: n.get("repo") for n in nodes}
    cross = sum(1 for l in links if repo.get(l["source"]) != repo.get(l["target"]))
    check("cross-module edges present", cross > 0, f"{cross:,} cross-module edges")

    # 3. communities are namespaced per chunk (old merge concatenated raw ids,
    #    so one community id spanned a dozen unrelated modules). Ids are ints
    #    offset by chunk position, so this also catches a chunk overrunning
    #    COMMUNITY_STRIDE and colliding with the next chunk's range. A bare int
    #    is unreadable, so report the readable `community_key` on failure.
    spans = defaultdict(set)
    keys = {}
    for n in nodes:
        cid = n.get("community")
        if cid is not None:
            spans[cid].add(n.get("repo"))
            keys.setdefault(cid, n.get("community_key", cid))
    bad = [c for c, r in spans.items() if len(r) > 1]
    check("communities do not span chunks", not bad,
          f"{len(bad)} communities span >1 chunk"
          + ("" if not bad else ": " + ", ".join(str(keys[c]) for c in bad[:5])))

    # 4. curated labels actually landed
    named = sum(1 for n in curated_nodes
                if n.get("community_name") and "Community " not in str(n["community_name"]))
    distinct = len({n.get("community_name") for n in curated_nodes
                    if n.get("community_name") and "Community " not in str(n["community_name"])})
    check("curated labels attached", distinct > 0,
          f"{distinct} named communities covering {named:,} nodes")

    # 4b. retention against every name ever anchored, not just this chunk's
    #     already-synced id file - check 5 below can't see a chunk-wide
    #     collapse, because `--sync` silently drops whatever failed to
    #     attach before this check ever reads the id file, so it only tests
    #     self-consistency, not coverage. This is what would have caught the
    #     graphify 0.9.44 upgrade silently dropping 88% of names (530 -> 63)
    #     to a build_ast.py id-relativization bug, not ordinary re-clustering
    #     drift - RELABELLING.md measures >90% survival even at 25% source
    #     churn, so anything under half is a broken pipeline, not drift.
    total_curated = 0
    for af in cfg.labels_dir.glob("*.anchors.json"):
        entries = json.loads(af.read_text(encoding="utf-8")).get("communities", [])
        total_curated += len({e["label"] for e in entries})
    retention = (distinct / total_curated) if total_curated else 1.0
    check("curated-name retention rate", retention >= 0.5,
          f"{distinct}/{total_curated} ever-anchored names attached ({retention:.0%})")

    # 5. every curated name in a label file actually reached the merged graph.
    #    `relabel --audit` tests name-against-content on the *per-chunk* graph;
    #    attachment happens later, through anchor overlap in labels.py at merge
    #    time. Nothing spanned the two, so a name could pass every gate and
    #    still vanish - four OREDocs names did exactly that, dropped by an
    #    overlap guard they could not satisfy, with no error anywhere.
    attached: dict[str, set[str]] = defaultdict(set)
    for n in curated_nodes:
        nm, chunk = n.get("community_name"), n.get("repo")
        if not nm or "Community " in str(nm):
            continue
        # labels.py joins names with " / " when two of them claim one community.
        for part in str(nm).split(" / "):
            attached[chunk].add(part)

    built = {n.get("repo") for n in nodes}
    missing: dict[str, list[str]] = {}
    for lf in sorted(cfg.labels_dir.glob("*.json")):
        if lf.name.endswith(".anchors.json"):
            continue
        chunk = lf.stem
        if chunk not in built:
            continue
        # `relabel --sync` writes the id file straight from `community_name`,
        # so a combined "A / B" entry can now appear on this side too, not
        # just in the merged graph - split both the same way or a synced,
        # merged community fails this check on its own attached name.
        want: set[str] = set()
        for v in json.loads(lf.read_text(encoding="utf-8")).values():
            want.update(str(v).split(" / "))
        gap = sorted(want - attached.get(chunk, set()))
        if gap:
            missing[chunk] = gap

    # A warning, not a failure: a handful of names failing to attach is the
    # expected result of building against a different ORE commit than the
    # anchors were pinned on - the corpus re-clusters and some anchors no
    # longer win a community. That is harmless and must not fail the build
    # (INSTALL.md's Caveats say as much). A wholesale collapse from a pipeline
    # bug is the hard gate above - "curated-name retention rate" - which still
    # fails. This check stays to name *which* names dropped, not to block.
    n_missing = sum(len(v) for v in missing.values())
    check("all curated names attached", not missing,
          "every curated name reached the merged graph" if not missing
          else f"{n_missing} name(s) did not attach (expected off-baseline; a "
               "mass drop is caught by curated-name retention above): "
               + "; ".join(f"{c}: {', '.join(repr(x) for x in v)}"
                           for c, v in missing.items()),
          severity="warn")

    # 6. every expected chunk contributed
    present = Counter(n.get("repo") for n in nodes)
    check("all built chunks merged", len(present) > 0,
          ", ".join(f"{k}={v:,}" for k, v in present.most_common()))

    # 7. docs and xsd survived the merge (they were dropped by the old
    #    rebuild_all.py, which merged only the code chunks)
    check("docs present", present.get("OREDocs", 0) > 0,
          f"{present.get('OREDocs', 0)} doc nodes")
    xsd_node_count = present.get("OREXsd", 0) + present.get("OREXsdSupplement", 0)
    check("xsd present", xsd_node_count > 0, f"{xsd_node_count} xsd nodes")
    check("xsd supplement chunk present", present.get("OREXsdSupplement", 0) > 0,
          f"{present.get('OREXsdSupplement', 0)} nodes deterministically filling "
          "OREXsd's complexType/simpleType coverage gap (xsd_coverage_extract.py) "
          "- a regression here means those instruments.xsd/referencedata.xsd "
          "types silently lost their graph nodes again")

    # 8. include recall - informational, not a pass/fail gate (no baseline to
    #    gate against yet, see docs/METRICS.md). Surfaces the number so a
    #    regression is visible instead of silent, the same failure mode that
    #    motivated link.py in the first place.
    link_stats = g.get("graph", {}).get("link_stats") or {}
    total_inc = link_stats.get("total_includes", 0)
    resolved = link_stats.get("resolved_includes", 0)
    if total_inc:
        detail = (f"{resolved:,}/{total_inc:,} #include directives resolved "
                  f"({resolved / total_inc:.0%}); "
                  f"{link_stats.get('unresolved_includes', 0)} unresolved, "
                  f"{link_stats.get('ignored_non_ore_prefix', 0)} outside "
                  "INCLUDE_ROOTS")
    else:
        detail = "no link_stats in merged graph - re-run `merge` to populate"
    check("include recall computed", bool(total_inc), detail)

    # 9. implementation-flow queries need symbol links beyond file includes.
    symbol_stats = g.get("graph", {}).get("symbol_link_stats") or {}
    symbol_links = [link for link in links
                    if link.get("_origin") == "symbol_link"]
    relations = Counter(link.get("relation") for link in symbol_links)
    relation_detail = ", ".join(
        f"{key}={value:,}" for key, value in relations.most_common())
    detail = f"{len(symbol_links):,} symbol links; {relation_detail}"
    if not symbol_links:
        detail = f"none (recorded stats: {symbol_stats or 'missing'}; re-run merge)"
    check("symbol-level links present", bool(symbol_links), detail)

    # 9b. XSD schema definitions should connect to the C++ that implements
    # them (see xsd_link.py) - otherwise OREXsd sits in the graph as a
    # disconnected island despite visibly describing the same trade
    # structures OREData's fromXML() classes parse.
    xsd_stats = g.get("graph", {}).get("xsd_link_stats") or {}
    xsd_links = [link for link in links if link.get("_origin") == "xsd_link"]
    detail = (f"{len(xsd_links):,} xsd links "
              f"({xsd_stats.get('matched_exact', 0)} exact, "
              f"{xsd_stats.get('matched_via_stripped_data_suffix', 0)} via "
              "stripped 'Data' suffix)")
    if not xsd_links:
        detail = f"none (recorded stats: {xsd_stats or 'missing'}; re-run merge)"
    check("xsd-to-code links present", bool(xsd_links), detail)

    # 9c. forward coverage: "some links exist" (9b) says nothing about how
    # much of instruments.xsd actually resolved - xsd_link.py already
    # computes the unmatched set, it just wasn't surfaced past merge.py's
    # log line. A name can go unmatched for a legitimate reason (a wrapper/
    # collection type with no 1:1 C++ class) or because the heuristic missed
    # a real one (renamed class, paraphrased label) - list them so that
    # distinction is a human judgment call, not a silent gap.
    total_names = xsd_stats.get("instruments_xsd_type_names", 0)
    unmatched_names = xsd_stats.get("unmatched_names") or []
    if total_names:
        rate = (total_names - len(unmatched_names)) / total_names
        detail = (f"{total_names - len(unmatched_names)}/{total_names} "
                  f"instruments.xsd type names matched ({rate:.0%})")
        if unmatched_names:
            sample = ", ".join(unmatched_names[:15])
            more = f" (+{len(unmatched_names) - 15} more)" if len(unmatched_names) > 15 else ""
            detail += f"; unmatched: {sample}{more}"
        check("instruments.xsd match coverage", not unmatched_names, detail,
              severity="warn")

    # 9c2. the dispatch-table passes (trade type <-> databuilders.cpp,
    # convention type <-> conventions.cpp, reference-datum type <->
    # databuilders.cpp - see xsd_link.py) read their source files directly
    # rather than through the (incomplete) OREXsd graph nodes, so their own
    # coverage numbers matter independently of 9c's complexType-name numbers
    # above.
    for pass_name, stats_key, noun in (
            ("trade dispatch (instruments.xsd <-> databuilders.cpp)",
             "trade_dispatch", "trade elements"),
            ("convention dispatch (conventions.xsd <-> conventions.cpp)",
             "convention_dispatch", "convention elements"),
            ("reference-datum dispatch (referencedata.xsd <-> databuilders.cpp)",
             "reference_data_dispatch", "reference-datum elements")):
        pass_stats = xsd_stats.get(stats_key) or {}
        if pass_stats.get("skipped"):
            check(pass_name, False,
                  f"skipped: {pass_stats['skipped']} (merge must run with an "
                  "Engine checkout to read source files directly)",
                  severity="warn")
            continue
        attempted = pass_stats.get("attempted", 0)
        pass_unmatched = pass_stats.get("unmatched_names") or []
        if not attempted:
            continue
        matched = attempted - len(pass_unmatched)
        rate = matched / attempted
        detail = f"{matched}/{attempted} {noun} matched ({rate:.0%})"
        if pass_unmatched:
            sample = ", ".join(pass_unmatched[:15])
            more = (f" (+{len(pass_unmatched) - 15} more)"
                    if len(pass_unmatched) > 15 else "")
            detail += (f"; unmatched (mostly missing OREXsd graph nodes for "
                       f"that complexType, not a matching failure - see "
                       f"xsd_link.py): {sample}{more}")
        check(pass_name, not pass_unmatched, detail, severity="warn")

    # 9d. reciprocal direction: does every OREData trade class (one that
    # defines both fromXML and build - the Trade-subclass signature, as
    # opposed to LegData/Convention/ScheduleData-style classes that parse
    # XML but were never in instruments.xsd's scope) have an outbound xsd
    # link at all? 9c only tells you which xsd *names* failed to match; this
    # catches the opposite failure - a real trade class present in the
    # merged graph that xsd_link.py's candidate index or name heuristic
    # missed entirely (e.g. no source_file recorded, or a name that isn't
    # even a candidate), which 9b/9c can't see because they start from the
    # xsd side.
    defines_targets = defaultdict(set)
    for link in links:
        if link.get("relation") == "defines":
            defines_targets[link["source"]].add(link["target"])
    label_of = {n["id"]: _node_label(n) for n in nodes}
    xsd_matched_sources = {link["source"] for link in links
                            if link.get("_origin") == "xsd_link"}
    trade_classes = []
    for n in nodes:
        if n.get("repo") != "OREData" or not n.get("_callable_class"):
            continue
        # configuration/*.hpp (Convention, ...) also defines fromXML+build
        # but parses conventions.xsd, never instruments.xsd - restricting to
        # portfolio/ matches xsd_link.py's actual (deliberately narrow)
        # scope and keeps the gap list free of by-design non-matches.
        if not str(n.get("source_file", "")).startswith("portfolio/"):
            continue
        method_labels = {label_of.get(t, "").lower()
                          for t in defines_targets.get(n["id"], set())}
        if {"fromxml", "build"} <= method_labels:
            trade_classes.append(n)
    unmatched_classes = sorted(_node_label(n) for n in trade_classes
                                if n["id"] not in xsd_matched_sources)
    if trade_classes:
        matched_count = len(trade_classes) - len(unmatched_classes)
        detail = (f"{matched_count}/{len(trade_classes)} OREData classes with "
                  "fromXML()+build() have an xsd link")
        if unmatched_classes:
            sample = ", ".join(unmatched_classes[:15])
            more = (f" (+{len(unmatched_classes) - 15} more)"
                    if len(unmatched_classes) > 15 else "")
            detail += f"; missing: {sample}{more}"
        check("fromXML/build classes reciprocally linked to xsd",
              not unmatched_classes, detail, severity="warn")

    # 9e. same reciprocal check, for conventions.xsd's target population:
    # configuration/*.hpp classes that define fromXML but never build() (a
    # Convention parses config, it doesn't price anything) - the population
    # check 9d deliberately excludes.
    convention_classes = []
    for n in nodes:
        if n.get("repo") != "OREData" or not n.get("_callable_class"):
            continue
        if not str(n.get("source_file", "")).startswith("configuration/"):
            continue
        method_labels = {label_of.get(t, "").lower()
                          for t in defines_targets.get(n["id"], set())}
        if "fromxml" in method_labels:
            convention_classes.append(n)
    unmatched_conventions = sorted(_node_label(n) for n in convention_classes
                                    if n["id"] not in xsd_matched_sources)
    if convention_classes:
        matched_count = len(convention_classes) - len(unmatched_conventions)
        detail = (f"{matched_count}/{len(convention_classes)} OREData "
                  "configuration/ classes with fromXML() have an xsd link")
        if unmatched_conventions:
            sample = ", ".join(unmatched_conventions[:15])
            more = (f" (+{len(unmatched_conventions) - 15} more)"
                    if len(unmatched_conventions) > 15 else "")
            detail += f"; missing: {sample}{more}"
        check("fromXML configuration classes reciprocally linked to xsd",
              not unmatched_conventions, detail, severity="warn")

    # 10. schema_for links (link_schema.py) present, and not badly regressed
    # against a recorded baseline - same shape as check 2 (cross-module
    # edges: fail at zero), plus a soft regression guard the way "curated-
    # name retention rate" guards labels: the tiered join depends on both
    # the portfolio-scan trade registry and the full xsd census staying
    # intact, so a silent collapse (a source-scan regex breaking, an xsd
    # file failing to parse) should warn loudly rather than just quietly
    # shrinking the edge count.
    from .link_schema import SCHEMA_LINKS_BASELINE
    schema_links = [l for l in links if l.get("_origin") == "schema_link"]
    schema_stats = g.get("graph", {}).get("schema_link_stats") or {}
    check("schema links present", bool(schema_links),
          f"{len(schema_links):,} schema_for edges" if schema_links
          else f"none (recorded stats: {schema_stats or 'missing'}; re-run merge)")
    if schema_links and SCHEMA_LINKS_BASELINE:
        drop = 1 - (len(schema_links) / SCHEMA_LINKS_BASELINE)
        check("schema links not regressed vs baseline", drop <= 0.10,
              f"{len(schema_links):,} schema_for edges vs baseline "
              f"{SCHEMA_LINKS_BASELINE:,}" + (f" ({drop:+.0%})" if drop > 0.10 else ""),
              severity="warn")

    # 11. ORE_Forge's field mapping - see _fieldmap_checks.
    _fieldmap_checks(cfg, g.get("graph") or {}, nodes, links, check)

    convertible_path = _has_relation_path(
                nodes, links, "build",
        "FdDefaultableEquityJumpDiffusionConvertibleBondEngine",
                {"uses", "constructs"}, 4, "portfolio/convertiblebond")
    check("convertible pricing path connected", convertible_path,
                    "ConvertibleBond::build reaches its FD engine within 4 hops through a "
                    "uses and constructs edge")

    from .query import load_path_graph, query_flow
    flow_output = query_flow(load_path_graph(path), "ConvertibleBond")
    discovered_engine = (
        "FdDefaultableEquityJumpDiffusionConvertibleBondEngine" in flow_output)
    check("convertible pricing endpoint discovered", discovered_engine,
          "query-flow discovers the FD engine from ConvertibleBond alone")

    return {"checks": checks, "ore": ore,
            "nodes": len(nodes), "edges": len(links),
            "cross_module_edges": cross}


def _format_ore(ore: dict) -> str:
    bits = [ore["release"]] if ore.get("release") else []
    ref = ore.get("describe") or ore.get("commit")
    if ref:
        bits.append(ref)
    if ore.get("quantlib"):
        bits.append(f"QuantLib {ore['quantlib']}")
    if ore.get("graphify_version"):
        bits.append(f"graphifyy {ore['graphify_version']}")
    line = "ORE: " + (" | ".join(bits) if bits else "unknown")
    if ore.get("built_at"):
        line += f"  (built {ore['built_at']})"
    return line


def format_report(result: dict) -> str:
    lines = []
    ore = result.get("ore")
    lines.append(_format_ore(ore) if ore else
                 "ORE: not recorded in this graph - rebuild to capture it")
    lines.append("")
    for c in result["checks"]:
        if c["ok"]:
            tag = "PASS"
        elif c.get("severity") == "warn":
            tag = "WARN"
        else:
            tag = "FAIL"
        lines.append(f"[{tag}] {c['check']:34s} {c['detail']}")
    if "nodes" in result:
        lines.append(f"\n{result['nodes']:,} nodes  {result['edges']:,} edges  "
                     f"{result['cross_module_edges']:,} cross-module")
    failed = [c for c in result["checks"]
              if not c["ok"] and c.get("severity", "error") != "warn"]
    warned = [c for c in result["checks"]
              if not c["ok"] and c.get("severity", "error") == "warn"]
    if failed:
        lines.append(f"\n{len(failed)} check(s) FAILED.")
    elif warned:
        lines.append(f"\nAll checks passed ({len(warned)} warning(s)).")
    else:
        lines.append("\nAll checks passed.")
    return "\n".join(lines)
