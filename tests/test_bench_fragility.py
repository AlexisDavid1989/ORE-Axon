"""The perturbations must change nothing a question could depend on, and the
summary must turn crossings into the margin the report recommends."""
import unittest

import networkx as nx

from oregraph.bench_fragility import (format_fragility, shuffled_copy, summarise,
                                      with_inert_nodes)


def graph(cls=nx.DiGraph):
    g = cls()
    g.graph.update({"hyperedges": [1], "_norm_index": {"stale": ["x"]}, "keep": True})
    for i in range(30):
        g.add_node(f"n{i}", label=f"Label{i}", source_file=f"f{i % 3}.hpp", community=i % 4)
    for i in range(29):
        g.add_edge(f"n{i}", f"n{i + 1}", relation="uses", weight=1.0 + i)
        if i % 5 == 0:
            g.add_edge(f"n{i}", f"n{(i * 7) % 30}", relation="calls")
    return g


def facts(g):
    return ({n: dict(d) for n, d in g.nodes(data=True)},
            {(u, v): dict(d) for u, v, d in g.edges(data=True)})


class PerturbationTest(unittest.TestCase):
    def test_shuffle_keeps_every_node_edge_and_attribute(self):
        g = graph()
        self.assertEqual(facts(shuffled_copy(g, 1)), facts(g))

    def test_shuffle_changes_the_order_but_not_with_the_same_seed(self):
        g = graph()
        a, b, c = shuffled_copy(g, 1), shuffled_copy(g, 2), shuffled_copy(g, 1)
        self.assertNotEqual(list(a.nodes), list(g.nodes))
        self.assertNotEqual(list(a.nodes), list(b.nodes))
        self.assertEqual(list(a.nodes), list(c.nodes))
        self.assertEqual(list(a.edges), list(c.edges))
        adjacency = lambda h: [list(h.successors(n)) for n in g.nodes]
        self.assertNotEqual(adjacency(a), adjacency(g))

    def test_shuffle_drops_only_our_own_memoised_indexes(self):
        h = shuffled_copy(graph(), 1)
        self.assertNotIn("_norm_index", h.graph)
        self.assertEqual((h.graph["keep"], h.graph["hyperedges"]), (True, [1]))

    def test_shuffle_leaves_the_original_untouched(self):
        g = graph()
        before, order = facts(g), list(g.nodes)
        shuffled_copy(g, 3)
        self.assertEqual((facts(g), list(g.nodes)), (before, order))

    def test_multigraph_keeps_parallel_edges(self):
        g = graph(nx.MultiDiGraph)
        g.add_edge("n0", "n1", relation="second")
        h = shuffled_copy(g, 1)
        self.assertEqual(h.number_of_edges(), g.number_of_edges())

    def test_inert_adds_edgeless_nodes_and_keeps_the_original_order(self):
        g = graph()
        h = with_inert_nodes(g, 1, fraction=0.2)
        self.assertEqual(h.number_of_nodes(), g.number_of_nodes() + 6)
        self.assertEqual(list(h.nodes)[:30], list(g.nodes))
        self.assertEqual(h.number_of_edges(), g.number_of_edges())
        added = [n for n in h.nodes if n not in g]
        self.assertTrue(all(h.degree(n) == 0 for n in added))
        self.assertTrue(all(not h.nodes[n]["source_file"] for n in added))


def entry(qid, name, kind="required", reached=True, margin=50, flips=0, drop=0, runs=()):
    return {"id": qid, "entry": name, "kind": kind, "reached": reached, "rank": 5,
            "margin": margin, "flips": flips, "flip_runs": list(runs),
            "max_drop": drop, "max_shift": 0}


class SummariseTest(unittest.TestCase):
    def test_margin_comes_from_the_farthest_crossing_in_either_direction(self):
        entries = [
            entry("s1", "gap-out", "gap", reached=False, margin=-23, flips=1, runs=["inert#1"]),
            entry("s2", "gap-near", "gap", reached=False, margin=-8, flips=2, runs=["shuffle#1"]),
            entry("s3", "steady", margin=60),
        ]
        s = summarise(entries)
        self.assertEqual(s["farthest_crossing"], 23)
        self.assertEqual(s["suggested_margin"], 25)    # 23 + 1, up to a multiple of 5
        self.assertEqual((s["crossed"], s["required_lost"]), (2, 0))

    def test_a_delivered_entry_that_dropped_out_counts_by_its_margin(self):
        entries = [entry("s1", "lost", margin=12, flips=1, runs=["shuffle#2"])]
        s = summarise(entries)
        self.assertEqual((s["required_lost"], s["farthest_crossing"], s["suggested_margin"]),
                         (1, 12, 15))
        self.assertEqual(s["required_lost_entries"], ["s1:lost"])

    def test_an_entry_from_outside_both_halves_has_no_distance(self):
        entries = [entry("s1", "far", "gap", reached=False, margin=None, flips=1)]
        s = summarise(entries)
        self.assertEqual((s["from_outside"], s["farthest_crossing"], s["suggested_margin"]),
                         (1, None, 0))

    def test_no_crossings_suggests_nothing(self):
        s = summarise([entry("s1", "steady", drop=14)])
        self.assertEqual((s["crossed"], s["suggested_margin"], s["max_drop"]), (0, 0, 14))

    def test_a_boundary_distance_rounds_up_by_one_step(self):
        for distance, want in ((4, 5), (5, 10), (24, 25), (25, 30)):
            with self.subTest(distance=distance):
                e = entry("s", "x", "gap", reached=False, margin=-distance, flips=1)
                self.assertEqual(summarise([e])["suggested_margin"], want)

    def test_the_report_flags_a_stale_constant(self):
        e = entry("s1", "gap-out", "gap", reached=False, margin=-23, flips=1, runs=["inert#1"])
        res = {"questions": 1, "kinds": ["inert"], "seeds": 1, "entries": [e],
               "runs": [{"kind": "inert", "seed": 1, "flips": [
                   {"id": "s1", "entry": "gap-out", "from": False, "to": True}],
                   "answers_changed": 1, "nodes_changed": 4}],
               "summary": summarise([e])}
        self.assertIn("STALE", format_fragility(res, 20))
        self.assertNotIn("STALE", format_fragility(res, 25))


if __name__ == "__main__":
    unittest.main()
