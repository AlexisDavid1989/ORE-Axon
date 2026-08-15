"""Repair graphify AST node ids that leaked an absolute filesystem path.

Root cause: graphify_build.py passes ``cache_root`` (an out-of-tree cache
directory) into ``graphify.extract.extract()``, which reuses that same value
internally as the root for id-relativization (``path.relative_to(root)``).
Since the real source files aren't under the cache directory, that
relativization silently fails for every file and the AST extractor falls back
to an absolute-path-derived id. ``source_file`` is unaffected (it's
relativized separately, correctly, in ``build_from_json``), so it's used here
as the ground truth to recompute the correct id.

Two-tier fix, applied directly to a built ``graph.json``:
  1. For nodes with a source_file: recompute the canonical extension-less id
     (graphify's own scheme - see graphify/extractors/base.py:_file_stem).
     Collisions between a header and its sibling impl file (e.g. foo.hpp /
     foo.cpp collapsing to the same stem) are merged into one node, keeping
     the header's attributes and redirecting the impl's edges onto it -
     mirroring graphify's own _merge_decl_def_classes intent. Collisions that
     aren't a clean single-header set (e.g. a .sln/.vcxproj pair) are left
     distinct by keeping the extension in the id instead of merging.
  2. For everything else whose id still starts with the detected absolute
     prefix (symbol/reference nodes with no source_file of their own): strip
     the prefix directly.

Safe to run multiple times (a no-op on an already-fixed graph.json).
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

from graphify.ids import normalize_id

HEADER_EXTS = {".h", ".hpp", ".hxx", ".hh", ".inl", ".ipp"}
IMPL_EXTS = {".cpp", ".cc", ".cxx", ".c", ".mm", ".m"}


def _stem_with_ext(source_file: str) -> str:
    return normalize_id(source_file)


def _stem_no_ext(source_file: str) -> str:
    return normalize_id(Path(source_file).with_suffix("").as_posix())


def _ext_of(source_file: str) -> str:
    return Path(source_file).suffix.lower()


def fix_graph_json(path: str) -> dict:
    """Repair absolute-path-derived ids in a graph.json file in place.

    Returns a stats dict. If no absolute-path ids are detected, does nothing
    and returns {"skipped": "..."}.
    """
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    nodes = d["nodes"]
    links = d["links"]

    by_sf: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        sf = n.get("source_file")
        if sf:
            by_sf[sf].append(n)

    root_const = None
    for sf, group in by_sf.items():
        want = "_" + _stem_with_ext(sf)
        for n in group:
            if n["id"].endswith(want):
                root_const = n["id"][: -len(want)]
                break
        if root_const:
            break
    if root_const is None:
        return {"skipped": "no absolute-path ids detected"}

    tentative: dict[str, tuple[str, str]] = {}
    unmapped: list[str] = []
    for sf, group in by_sf.items():
        new_no_ext = _stem_no_ext(sf)
        old_sym_pref = root_const + "_" + new_no_ext
        old_file_id = root_const + "_" + _stem_with_ext(sf)
        for n in group:
            oid = n["id"]
            if oid == old_file_id:
                tentative[oid] = (new_no_ext, sf)
            elif oid.startswith(old_sym_pref + "_"):
                tentative[oid] = (new_no_ext + oid[len(old_sym_pref):], sf)
            elif oid == old_sym_pref:
                tentative[oid] = (new_no_ext, sf)
            else:
                unmapped.append(oid)

    groups_by_new: dict[str, list[str]] = defaultdict(list)
    for oid, (nid, _sf) in tentative.items():
        groups_by_new[nid].append(oid)

    id_remap: dict[str, str] = {}
    messy_files: set[str] = set()
    for nid, oids in groups_by_new.items():
        if len(oids) == 1:
            id_remap[oids[0]] = nid
            continue
        sfs = {tentative[o][1] for o in oids}
        headers = [s for s in sfs if _ext_of(s) in HEADER_EXTS]
        impls = [s for s in sfs if _ext_of(s) in IMPL_EXTS]
        clean = len(headers) == 1 and len(headers) + len(impls) == len(sfs)
        if clean:
            for o in oids:
                id_remap[o] = nid
        else:
            messy_files |= sfs
            for o in oids:
                sf = tentative[o][1]
                id_remap[o] = _stem_with_ext(sf)

    prefix = root_const + "_"
    generic_fixed = 0
    for n in nodes:
        oid = n["id"]
        if oid in id_remap:
            continue
        if oid.startswith(prefix):
            id_remap[oid] = oid[len(prefix):]
            generic_fixed += 1

    final_groups: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        final_groups[id_remap.get(n["id"], n["id"])].append(n)

    def rank(n: dict) -> int:
        ext = _ext_of(n.get("source_file", ""))
        if ext in HEADER_EXTS:
            return 0
        if ext in IMPL_EXTS:
            return 1
        return 2

    final_nodes = []
    collision_merges = 0
    for nid, grp in final_groups.items():
        if len(grp) == 1:
            grp[0]["id"] = nid
            final_nodes.append(grp[0])
        else:
            collision_merges += 1
            survivor = sorted(grp, key=rank)[0]
            survivor["id"] = nid
            final_nodes.append(survivor)

    final_links = []
    selfloop_dropped = 0
    for e in links:
        s_old, t_old = e.get("source"), e.get("target")
        was_self = s_old == t_old
        s_new = id_remap.get(s_old, s_old)
        t_new = id_remap.get(t_old, t_old)
        if s_new == t_new and not was_self:
            selfloop_dropped += 1
            continue
        e["source"] = s_new
        e["target"] = t_new
        final_links.append(e)

    d["nodes"] = final_nodes
    d["links"] = final_links
    Path(path).write_text(json.dumps(d, indent=2), encoding="utf-8")

    still_abs = sum(1 for n in final_nodes if n["id"].startswith(root_const))
    return {
        "nodes_before": len(nodes),
        "nodes_after": len(final_nodes),
        "links_before": len(links),
        "links_after": len(final_links),
        "unmapped": len(unmapped),
        "generic_fixed": generic_fixed,
        "collision_merges": collision_merges,
        "messy_files_kept_distinct": len(messy_files),
        "selfloops_dropped": selfloop_dropped,
        "still_absolute_after_fix": still_abs,
    }


if __name__ == "__main__":
    result = fix_graph_json(sys.argv[1])
    print(json.dumps(result, indent=2))
