"""The fusion behind `query_graph`, split so the benchmark can see the ranking.

`fuse_ranked` + `take_budget` replaced one function. What they must not change is
the answer, so the old algorithm is kept here as the reference."""
import re
import unittest
from types import SimpleNamespace
from unittest import mock

from oregraph import query
from oregraph.query import (fuse_ranked, merge_answers, query_graph_answer,
                            query_graph_text, take_budget)

_TOKEN_RE = re.compile(r"\w+|[^\w\s]")


def reference_merge(primary, secondary, token_budget=2000):
    """merge_answers as it was before it was split (reciprocal-rank fusion, k=10)."""
    def nodes(text):
        return [line for line in text.splitlines() if line.startswith("NODE ")]

    k = 10
    fused = {}
    for side in (nodes(primary), nodes(secondary)):
        for rank, line in enumerate(side):
            key = line.split(" loc=", 1)[0]
            entry = fused.setdefault(key, [0.0, len(fused), line])
            entry[0] += 1.0 / (k + rank)
    lines, used = [], 0
    for _key, (_score, _order, line) in sorted(
            fused.items(), key=lambda kv: (-kv[1][0], kv[1][1])):
        cost = len(_TOKEN_RE.findall(line))
        if used + cost > token_budget and lines:
            break
        lines.append(line)
        used += cost
    return "\n".join(lines)


def node(label, src="", loc="L1"):
    return f"NODE {label} [src={src} loc={loc} community=c]"


def answer(*nodes, header=True):
    body = "\n".join(nodes)
    return ("Traversal: BFS depth=3 | Start: ['x'] | 5 nodes found\n\n" + body
            if header else body)


A = answer(node("Swap", "swap.hpp"), node("Leg", "leg.hpp"), node("Bond", "bond.hpp"),
           node("Trade", "trade.hpp"), "EDGE Swap --uses [EXTRACTED]--> Leg")
B = answer(node("Leg", "leg.hpp"), node("Curve", "curve.hpp"), node("Swap", "swap.hpp"),
           node("LegData", ""), node("LegData", "legdata.hpp"))


class FusionTest(unittest.TestCase):
    def test_merge_answers_is_unchanged_by_the_split(self):
        for budget in (5, 40, 90, 2000):
            with self.subTest(budget=budget):
                self.assertEqual(merge_answers(A, B, budget), reference_merge(A, B, budget))
                self.assertEqual(merge_answers(B, A, budget), reference_merge(B, A, budget))

    def test_random_answers_fuse_exactly_like_the_reference(self):
        # Two tiny answers can agree under a slightly different score; many
        # overlapping 60-node ones cannot, so this pins the arithmetic itself.
        import random
        for seed in range(60):
            rng = random.Random(seed)
            pool = [(f"N{i}", f"n{i}.hpp") for i in range(90)]

            def side():
                return answer(*[node(*n) for n in rng.sample(pool, 60)])

            a, b = side(), side()
            for budget in (200, 900, 2000):
                self.assertEqual(merge_answers(a, b, budget), reference_merge(a, b, budget),
                                 (seed, budget))

    def test_a_node_both_sides_found_ranks_first(self):
        ranked = fuse_ranked(A, B)
        # Leg is 2nd and 1st (1/11 + 1/10), Swap 1st and 3rd (1/10 + 1/12);
        # both beat everything only one side found, Curve (1/11) included.
        self.assertTrue(ranked[0].startswith("NODE Leg "))
        self.assertTrue(ranked[1].startswith("NODE Swap "))
        self.assertLess(ranked.index(node("Swap", "swap.hpp")),
                        [i for i, l in enumerate(ranked) if l.startswith("NODE Curve ")][0])

    def test_label_and_file_are_the_key(self):
        ranked = fuse_ranked(A, B)
        legdata = [l for l in ranked if l.startswith("NODE LegData ")]
        self.assertEqual(len(legdata), 2)      # the stub and the real class stay apart

    def test_only_nodes_are_ranked(self):
        self.assertTrue(all(l.startswith("NODE ") for l in fuse_ranked(A, B)))

    def test_take_budget_returns_a_prefix_and_at_least_one_line(self):
        ranked = fuse_ranked(A, B)
        for budget in (0, 15, 60, 10 ** 6):
            kept = take_budget(ranked, budget)
            self.assertEqual(kept, ranked[:len(kept)])
            self.assertGreaterEqual(len(kept), 1)
        self.assertEqual(take_budget(ranked, 10 ** 6), ranked)

    def test_take_budget_stops_before_the_line_that_would_overflow(self):
        ranked = fuse_ranked(A, B)
        cost = lambda l: len(_TOKEN_RE.findall(l))
        budget = cost(ranked[0]) + cost(ranked[1])
        self.assertEqual(take_budget(ranked, budget), ranked[:2])
        self.assertEqual(take_budget(ranked, budget - 1), ranked[:1])


class AnswerTest(unittest.TestCase):
    def test_answer_carries_both_halves_the_ranking_and_the_cut(self):
        ours = answer(node("Curve", "curve.hpp"), node("Swap", "swap.hpp"))
        with mock.patch.object(query, "query_question", return_value=ours):
            got = query_graph_answer(None, "how is a swap priced", token_budget=40,
                                     graphify_answer=A)
        self.assertEqual((got.graphify, got.ours), (A, ours))
        self.assertEqual(got.ranked, fuse_ranked(A, ours))
        self.assertLess(got.shown, len(got.ranked))
        served = [l for l in got.text.splitlines() if l.startswith("NODE ")]
        self.assertEqual(served, got.ranked[:got.shown])
        self.assertTrue(got.text.startswith("Question: how is a swap priced\n"))

    def test_query_graph_text_is_exactly_the_answers_text(self):
        with mock.patch.object(query, "query_question", return_value=B):
            text = query_graph_text(None, "q", graphify_answer=A)
            self.assertEqual(text, query_graph_answer(None, "q", graphify_answer=A).text)
            self.assertEqual(
                text,
                "Question: q\nTraversal: BFS depth=3 | merged graphify + oregraph seeds"
                "\n\n" + reference_merge(A, B))


if __name__ == "__main__":
    unittest.main()
