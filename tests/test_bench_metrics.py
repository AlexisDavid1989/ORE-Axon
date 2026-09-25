"""Rank, margin, controls, variants, noise and the metrics built from them."""
import json
import unittest
from pathlib import Path
from types import SimpleNamespace

import networkx as nx

from oregraph.bench import (FRAGILE_MARGIN, check_suite, controls_for, entry_rank,
                            evaluate, explain_question, format_explain,
                            is_fragile, noise_counts, noise_kind, parse_nodes,
                            run_controls, run_vs_source, standing)

SUITE = Path(__file__).resolve().parent.parent / "bench" / "source_questions.json"


def node_line(label, src):
    return f"NODE {label} [src={src} loc=L1 community=c]"


def answer_text(*nodes):
    return "\n".join(node_line(*n) for n in nodes)


class FakeAdapter:
    """Answers each question from a table: question -> (ranked nodes, shown).

    `graphify_only` and `oregraph_only` answer from `halves` so `explain` can be
    tested without a graph."""

    def __init__(self, table, halves=None):
        self.table = table
        self.halves = halves or {}
        self.asked = []
        self.G = nx.DiGraph()

    def answer(self, question, **_shape):
        self.asked.append(question)
        ranked, shown = self.table[question]
        return SimpleNamespace(
            text=f"Question: {question}\n\n" + answer_text(*ranked[:shown]),
            ranked=[node_line(*n) for n in ranked], shown=shown,
            graphify=answer_text(*self.halves.get(("g", question), ranked[:shown])),
            ours=answer_text(*self.halves.get(("o", question), ranked[:shown])))

    def graphify_only(self, question, **shape):
        return answer_text(*self.halves.get(("gd", question), self.table[question][0]))

    def oregraph_only(self, question, **shape):
        return answer_text(*self.halves.get(("od", question), self.table[question][0]))


def ranked_nodes(n, **placed):
    """n filler nodes `f0..`, with `placed` label -> 0-based index inserted."""
    nodes = [(f"f{i}", f"f{i}.hpp") for i in range(n)]
    for label, idx in placed.items():
        nodes[idx] = (label, f"{label.lower()}.hpp")
    return nodes


class EntryRankTest(unittest.TestCase):
    def test_rank_is_one_based_position_of_first_match(self):
        nodes = parse_nodes(answer_text(("A", "a.hpp"), ("B", "b.hpp"), ("B", "c.hpp")))
        self.assertEqual(entry_rank(nodes, "A"), 1)
        self.assertEqual(entry_rank(nodes, "B"), 2)
        self.assertEqual(entry_rank(nodes, "B@c.hpp"), 3)
        self.assertIsNone(entry_rank(nodes, "C"))

    def test_a_source_with_spaces_is_read_whole(self):
        # A fieldmap entry's source is `fieldmap/trade/Interest Rate Swaption`. Read up to
        # the next space it was `fieldmap/trade/Interest`, so an entry that named the node
        # in full (s51's) could never be met by an answer that contained it.
        nodes = parse_nodes(answer_text(
            ("Interest Rate Swaption [trade mapping]", "fieldmap/trade/Interest Rate Swaption")))
        self.assertEqual(nodes, [("Interest Rate Swaption [trade mapping]",
                                  "fieldmap/trade/Interest Rate Swaption")])
        self.assertEqual(entry_rank(
            nodes, "Interest Rate Swaption [trade mapping]@fieldmap/trade/Interest Rate Swaption"), 1)
        # ...and an entry that names only the first word (s34's) still matches.
        self.assertEqual(entry_rank(
            nodes, "Interest Rate Swaption [trade mapping]@fieldmap/trade/Interest"), 1)

    def test_src_entry_ranks_at_its_best_match(self):
        nodes = parse_nodes(answer_text(("A", "a.hpp"), ("B", "test/b.cpp"),
                                        ("C", "test/c.cpp")))
        self.assertEqual(entry_rank(nodes, "src:test/"), 2)


class StandingTest(unittest.TestCase):
    def setUp(self):
        self.ranked = [(f"n{i}", f"n{i}.hpp") for i in range(10)]

    def test_margin_counts_nodes_between_entry_and_cut(self):
        st = standing(self.ranked, 8, "n2")
        self.assertEqual((st["rank"], st["margin"]), (3, 5))
        # rank == cutoff is the last node kept, margin 0
        self.assertEqual(standing(self.ranked, 8, "n7")["margin"], 0)

    def test_a_cut_entry_has_negative_margin(self):
        st = standing(self.ranked, 8, "n8")
        self.assertEqual((st["rank"], st["margin"], st["support"]), (9, -1, 0))

    def test_entry_in_no_candidate_has_no_rank(self):
        st = standing(self.ranked, 8, "zzz")
        self.assertEqual((st["rank"], st["margin"]), (None, None))

    def test_support_counts_matches_that_made_the_cut(self):
        ranked = [("a", "test/a.cpp"), ("b", "test/b.cpp"), ("c", "test/c.cpp")]
        self.assertEqual(standing(ranked, 2, "src:test/")["support"], 2)

    def test_stub_only_when_every_kept_match_has_no_source(self):
        ranked = [("Handle", ""), ("Handle", "handle.hpp"), ("X", "x.hpp")]
        self.assertTrue(standing(ranked, 1, "Handle")["stub_only"])
        # the real node made the cut too, so the entry is met by content
        self.assertFalse(standing(ranked, 2, "Handle")["stub_only"])

    def test_fragile_boundary(self):
        self.assertTrue(is_fragile({"margin": 0}))
        self.assertTrue(is_fragile({"margin": FRAGILE_MARGIN - 1}))
        self.assertFalse(is_fragile({"margin": FRAGILE_MARGIN}))
        # a cut or absent entry is not fragile, it is missing
        self.assertFalse(is_fragile({"margin": -1}))
        self.assertFalse(is_fragile({"margin": None}))
        self.assertTrue(is_fragile({"margin": 9}, margin=10))
        self.assertFalse(is_fragile({"margin": 10}, margin=10))


class NoiseTest(unittest.TestCase):
    def test_stub_and_generic_are_noise_content_is_not(self):
        self.assertEqual(noise_kind("string", ""), "stub")
        self.assertEqual(noise_kind("Handle", ""), "stub")
        self.assertEqual(noise_kind("Real", "types.hpp"), "generic")
        self.assertEqual(noise_kind("types.hpp", "types.hpp"), "generic")
        self.assertIsNone(noise_kind("Swap", "portfolio/swap.hpp"))
        self.assertIsNone(noise_kind("Handle", "handle.hpp"))

    def test_precision_is_share_of_non_noise(self):
        nodes = [("Swap", "swap.hpp"), ("string", ""), ("Real", "types.hpp"),
                 ("Bond", "bond.hpp")]
        c = noise_counts(nodes)
        self.assertEqual((c["stub"], c["generic"], c["precision"]), (1, 1, 0.5))

    def test_precision_at_10_reads_only_the_head(self):
        nodes = [("string", "")] * 3 + [(f"C{i}", f"c{i}.hpp") for i in range(7)] \
            + [("vector", "")] * 20
        c = noise_counts(nodes)
        self.assertEqual(c["precision_at_10"], 0.7)
        self.assertLess(c["precision"], 0.5)

    def test_empty_answer_has_no_precision(self):
        self.assertIsNone(noise_counts([])["precision"])


class ControlsTest(unittest.TestCase):
    def test_list_controls_apply_to_every_entry(self):
        q = {"controls": ["c1", "c2"]}
        self.assertEqual(controls_for(q, "anything"), ["c1", "c2"])

    def test_dict_controls_combine_star_and_entry(self):
        q = {"controls": {"*": ["c1"], "A": ["c2", "c1"]}}
        self.assertEqual(controls_for(q, "A"), ["c1", "c2"])
        self.assertEqual(controls_for(q, "B"), ["c1"])

    def test_entry_in_a_control_answer_is_weak(self):
        adapter = FakeAdapter({
            "control 1": ([("Swap", "swap.hpp")], 1),
            "control 2": ([("Other", "o.hpp")], 1),
        })
        q = {"id": "q", "question": "how is a swap priced",
             "required_nodes": ["Swap", "LegData"], "controls": ["control 1", "control 2"]}
        weak, asked = run_controls(adapter, q, {})
        self.assertEqual(weak, {"Swap": ["control 1"]})
        self.assertEqual(asked, 2)

    def test_controls_are_asked_once_per_shape(self):
        adapter = FakeAdapter({"c": ([("X", "x.hpp")], 1)})
        cache = {}
        q = {"required_nodes": ["A", "B"], "controls": ["c"]}
        run_controls(adapter, q, cache)
        self.assertEqual(adapter.asked, ["c"])

    def test_a_control_answer_cut_by_the_budget_does_not_count(self):
        # Swap ranks 2nd of 2 candidates but the answer only kept 1
        adapter = FakeAdapter({"c": ([("X", "x.hpp"), ("Swap", "swap.hpp")], 1)})
        weak, _ = run_controls(adapter, {"required_nodes": ["Swap"], "controls": ["c"]}, {})
        self.assertEqual(weak, {})

    def test_extra_entries_can_be_checked(self):
        adapter = FakeAdapter({"c": ([("Gap", "g.hpp")], 1)})
        q = {"required_nodes": ["A"], "xfail_nodes": ["Gap"], "controls": ["c"]}
        weak, _ = run_controls(adapter, q, {}, entries=["A", "Gap"])
        self.assertEqual(weak, {"Gap": ["c"]})


class CheckSuiteTest(unittest.TestCase):
    def suite(self, *questions, why_from=None):
        meta = {"why_required_from": why_from} if why_from else {}
        return {"meta": meta, "questions": list(questions)}

    def q(self, qid="s01", **kw):
        return {"id": qid, "question": "how is X built", "required_nodes": ["A"], **kw}

    def test_a_clean_suite_has_no_problems(self):
        self.assertEqual(check_suite(self.suite(self.q())), [])

    def test_why_is_required_from_the_named_question_on(self):
        old = self.q("s50")
        new = self.q("s51")
        problems = check_suite(self.suite(old, new, why_from="s51"))
        self.assertEqual(len(problems), 1)
        self.assertIn("s51", problems[0])
        self.assertIn("no `why`", problems[0])
        ok = self.q("s51", why={"A": "the class the trade builds"})
        self.assertEqual(check_suite(self.suite(old, ok, why_from="s51")), [])

    def test_blank_why_does_not_count(self):
        problems = check_suite(self.suite(self.q("s51", why={"A": "  "}), why_from="s51"))
        self.assertTrue(problems)

    def test_why_must_name_a_rubric_entry(self):
        problems = check_suite(self.suite(self.q(why={"Typo": "x"})))
        self.assertTrue(any("not a rubric entry" in p for p in problems))

    def test_duplicate_entry_and_id_are_reported(self):
        problems = check_suite(self.suite(
            self.q(required_nodes=["A", "A"]), self.q()))
        self.assertTrue(any("more than once" in p for p in problems))
        self.assertTrue(any("duplicate question id" in p for p in problems))

    def test_entry_in_both_lists_is_reported(self):
        problems = check_suite(self.suite(self.q(xfail_nodes=["A"])))
        self.assertTrue(any("more than once" in p for p in problems))

    def test_variants_must_be_distinct_phrasings_with_a_rubric(self):
        self.assertTrue(check_suite(self.suite(self.q(variants=["how is x built"]))))
        self.assertTrue(check_suite(self.suite(self.q(variants=["v", "v"]))))
        self.assertTrue(check_suite(self.suite(self.q(variants=[""]))))
        bare = {"id": "s01", "question": "q", "variants": ["v"]}
        self.assertTrue(any("grade nothing" in p for p in check_suite(self.suite(bare))))
        self.assertEqual(check_suite(self.suite(self.q(variants=["v1", "v2"]))), [])

    def test_a_control_must_not_be_the_question_or_a_variant(self):
        self.assertTrue(check_suite(self.suite(self.q(controls=["how is X built"]))))
        self.assertTrue(check_suite(self.suite(
            self.q(variants=["v1"], controls=["V1"]))))
        self.assertEqual(check_suite(self.suite(self.q(controls=["how is Y built"]))), [])

    def test_controls_need_a_rubric_entry_to_test(self):
        bare = {"id": "s01", "question": "q", "controls": ["c"]}
        self.assertTrue(any("test nothing" in p for p in check_suite(self.suite(bare))))
        # a question with only known gaps keeps its controls: they decide
        # whether a gap that gets reached may be promoted
        gaps_only = {"id": "s01", "question": "q", "xfail_nodes": ["A"], "controls": ["c"]}
        self.assertEqual(check_suite(self.suite(gaps_only)), [])

    def test_xfail_variants_need_a_written_reason(self):
        q = self.q(xfail_variants=["a paraphrase that fails"])
        problems = check_suite(self.suite(q))
        self.assertTrue(any("xfail variant" in p and "no `why`" in p for p in problems))
        ok = self.q(xfail_variants=["a paraphrase that fails"],
                    why={"a paraphrase that fails": "loses LegData on 0.9.44"})
        self.assertEqual(check_suite(self.suite(ok)), [])
        # ... whatever the age of the question, unlike a rubric entry's why
        old = self.q("s01", xfail_variants=["p"])
        self.assertTrue(check_suite(self.suite(old, why_from="s51")))

    def test_an_xfail_variant_is_a_phrasing_like_any_other(self):
        why = {"p": "reason"}
        self.assertTrue(check_suite(self.suite(
            self.q(variants=["p"], xfail_variants=["p"], why=why))))
        self.assertTrue(check_suite(self.suite(
            self.q(xfail_variants=["p"], controls=["p"], why=why))))
        self.assertTrue(check_suite(self.suite(
            self.q(xfail_variants=["how is X built"], why={"how is X built": "r"}))))

    def test_phrasings_lists_the_question_variants_then_known_gaps(self):
        from oregraph.bench import phrasings
        q = {"question": "q", "variants": ["v1", "v2"], "xfail_variants": ["x1"]}
        self.assertEqual(phrasings(q), ["q", "v1", "v2", "x1"])

    def test_dict_controls_keys_must_be_entries(self):
        self.assertTrue(check_suite(self.suite(self.q(controls={"Nope": ["c"]}))))
        self.assertEqual(check_suite(self.suite(self.q(controls={"A": ["c"], "*": ["d"]}))), [])

    def test_the_real_suite_is_well_formed(self):
        suite = json.loads(SUITE.read_text(encoding="utf-8"))
        self.assertEqual(check_suite(suite), [])


class EvaluateTest(unittest.TestCase):
    def test_grades_and_places_every_rubric_entry(self):
        ranked = ranked_nodes(30, Swap=0, LegData=24, Late=28)
        adapter = FakeAdapter({"how": (ranked, 26)})
        q = {"id": "q", "question": "how", "required_nodes": ["Swap", "LegData"],
             "xfail_nodes": ["Late"]}
        ev = evaluate(adapter, q, "how")
        self.assertEqual(ev["status"], "xfail")
        self.assertEqual(ev["reached"], ["Swap", "LegData"])
        self.assertEqual(ev["missing_gap"], ["Late"])
        self.assertEqual(ev["standing"]["LegData"]["margin"], 26 - 25)
        self.assertEqual(ev["standing"]["Late"]["margin"], 26 - 29)
        self.assertEqual(ev["fragile"], ["LegData"])
        self.assertEqual(ev["rubric_total"], 3)

    def test_ungraded_question_reports_nothing(self):
        adapter = FakeAdapter({"how": (ranked_nodes(5), 5)})
        ev = evaluate(adapter, {"id": "q", "question": "how"}, "how")
        self.assertEqual((ev["status"], ev["reached"], ev["standing"], ev["rubric_total"]),
                         (None, [], {}, 0))

    def test_stub_only_required_entry_is_flagged(self):
        adapter = FakeAdapter({"how": ([("Handle", "")], 1)})
        ev = evaluate(adapter, {"id": "q", "question": "how", "required_nodes": ["Handle"]},
                      "how")
        self.assertEqual((ev["status"], ev["stub_only"]), ("pass", ["Handle"]))


class RunVsSourceTest(unittest.TestCase):
    def run_suite(self, table, questions):
        adapter = FakeAdapter(table)
        return run_vs_source(adapter, questions, Path("."), log=lambda *_: None)

    def test_delivered_counts_required_and_gaps_together(self):
        ranked = ranked_nodes(20, A=0, B=1, Gap=2)
        vs = self.run_suite(
            {"q1": (ranked, 15), "q2": (ranked_nodes(20), 15)},
            [{"id": "s1", "question": "q1", "required_nodes": ["A", "B"],
              "xfail_nodes": ["Gap", "Other"]},
             {"id": "s2", "question": "q2", "required_nodes": ["A"]}])
        t = vs["totals"]
        self.assertEqual((t["delivered"], t["rubric_total"]), (3, 5))
        self.assertEqual((t["required_delivered"], t["required_total"]), (2, 3))
        self.assertEqual((t["gaps_closed"], t["gaps_total"]), (1, 2))
        self.assertEqual((t["answers_failed"], t["xpass"]), (1, 1))
        row = vs["rows"][0]
        self.assertEqual((row["delivered"], row["rubric_total"]), (3, 4))

    def test_precision_pools_returned_nodes(self):
        noisy = [("Swap", "swap.hpp"), ("string", ""), ("vector", ""), ("Bond", "b.hpp")]
        vs = self.run_suite({"q": (noisy, 4)},
                            [{"id": "s1", "question": "q", "required_nodes": ["Swap"]}])
        t = vs["totals"]
        self.assertEqual((t["nodes_returned"], t["noise_nodes"], t["precision"]), (4, 2, 0.5))

    def test_weak_and_fragile_entries_are_counted(self):
        ranked = ranked_nodes(30, Hub=27)
        vs = self.run_suite(
            {"q": (ranked, 30), "ctl": ([("Hub", "hub.hpp")], 1)},
            [{"id": "s1", "question": "q", "required_nodes": ["Hub"], "controls": ["ctl"]}])
        row = vs["rows"][0]
        self.assertEqual(row["weak"], {"Hub": ["ctl"]})
        self.assertEqual(row["fragile"], ["Hub"])
        self.assertEqual((vs["totals"]["weak_entries"], vs["totals"]["fragile_entries"]), (1, 1))
        self.assertEqual(vs["totals"]["controls_run"], 1)

    def test_variants_are_graded_against_the_same_rubric(self):
        vs = self.run_suite(
            {"q": ([("A", "a.hpp"), ("B", "b.hpp")], 2),
             "v1": ([("A", "a.hpp"), ("B", "b.hpp")], 2),
             "v2": ([("A", "a.hpp"), ("X", "x.hpp")], 2)},
            [{"id": "s1", "question": "q", "required_nodes": ["A", "B"],
              "variants": ["v1", "v2"]}])
        v1, v2 = vs["rows"][0]["variants"]
        self.assertEqual((v1["answer_status"], v1["lost"]), ("pass", []))
        self.assertEqual((v2["answer_status"], v2["missing_nodes"], v2["lost"]),
                         ("fail", ["B"], ["B"]))
        t = vs["totals"]
        self.assertEqual((t["variants"], t["variants_failed"], t["variants_lost"]), (2, 1, 1))
        # the main question itself is unaffected
        self.assertEqual(vs["rows"][0]["answer_status"], "pass")

    def test_known_paraphrase_gaps_are_reported_but_never_gate(self):
        vs = self.run_suite(
            {"q": ([("A", "a.hpp")], 1),
             "good": ([("A", "a.hpp")], 1),
             "bad": ([("X", "x.hpp")], 1),
             "fixed": ([("A", "a.hpp")], 1)},
            [{"id": "s1", "question": "q", "required_nodes": ["A"],
              "variants": ["good"], "xfail_variants": ["bad", "fixed"]}])
        good, bad, fixed = vs["rows"][0]["variants"]
        self.assertEqual([v["known_gap_variant"] for v in (good, bad, fixed)],
                         [False, True, True])
        self.assertEqual((bad["answer_status"], fixed["answer_status"]), ("fail", "pass"))
        t = vs["totals"]
        # only the gating variant counts toward the gate
        self.assertEqual((t["variants"], t["variants_failed"]), (1, 0))
        self.assertEqual((t["variants_known_gaps"], t["variants_xfail"], t["variants_xpass"]),
                         (2, 1, 1))

    def test_a_failing_gating_variant_still_gates(self):
        vs = self.run_suite(
            {"q": ([("A", "a.hpp")], 1), "bad": ([("X", "x.hpp")], 1)},
            [{"id": "s1", "question": "q", "required_nodes": ["A"], "variants": ["bad"],
              "xfail_variants": []}])
        self.assertEqual(vs["totals"]["variants_failed"], 1)

    def test_answer_hash_tracks_the_served_nodes_only(self):
        a = ranked_nodes(10)
        one = self.run_suite({"q": (a, 5)}, [{"id": "s", "question": "q", "required_nodes": ["f0"]}])
        two = self.run_suite({"q": (a, 5)}, [{"id": "s", "question": "q", "required_nodes": ["f0"]}])
        other = self.run_suite({"q": (list(reversed(a)), 5)},
                               [{"id": "s", "question": "q", "required_nodes": ["f9"]}])
        self.assertEqual(one["rows"][0]["answer_sha256"], two["rows"][0]["answer_sha256"])
        self.assertNotEqual(one["rows"][0]["answer_sha256"], other["rows"][0]["answer_sha256"])


class ExplainTest(unittest.TestCase):
    def test_reports_each_half_and_the_merged_rank(self):
        ranked = ranked_nodes(30, Swap=0, LegData=24)
        adapter = FakeAdapter(
            {"how": (ranked, 26)},
            halves={("g", "how"): ranked_nodes(10, Swap=2),      # graphify: Swap #3
                    ("o", "how"): ranked_nodes(10, Swap=0),      # oregraph: Swap #1
                    ("gd", "how"): ranked_nodes(50, Swap=2, LegData=40),
                    ("od", "how"): ranked_nodes(50, Swap=0)})
        q = {"id": "s01", "question": "how", "required_nodes": ["Swap", "LegData"]}
        info = explain_question(adapter, q)
        swap, leg = info["rows"]
        self.assertEqual((swap["graphify"], swap["oregraph"], swap["merged"]), (3, 1, 1))
        self.assertEqual((leg["graphify"], leg["graphify_deep"]), (None, 41))
        self.assertEqual((leg["oregraph"], leg["oregraph_deep"]), (None, None))
        self.assertEqual((leg["merged"], leg["margin"], leg["fragile"]), (25, 1, True))
        self.assertTrue(leg["delivered"])

    def test_a_cut_entry_says_how_far(self):
        ranked = ranked_nodes(30, Gap=28)
        adapter = FakeAdapter({"how": (ranked, 20)})
        q = {"id": "s01", "question": "how", "required_nodes": ["f0"], "xfail_nodes": ["Gap"]}
        gap = explain_question(adapter, q)["rows"][1]
        self.assertEqual((gap["kind"], gap["merged"], gap["margin"], gap["delivered"]),
                         ("gap", 29, -9, False))

    def test_variant_index_selects_the_phrasing(self):
        adapter = FakeAdapter({"how": (ranked_nodes(3), 3), "alt": (ranked_nodes(3), 3)})
        q = {"id": "s01", "question": "how", "variants": ["alt"], "required_nodes": ["f0"]}
        self.assertEqual(explain_question(adapter, q, variant=1)["question"], "alt")

    def test_format_names_the_states(self):
        ranked = ranked_nodes(30, LegData=24, Handle=0)
        ranked[0] = ("Handle", "")
        adapter = FakeAdapter({"how": (ranked, 26)})
        q = {"id": "s01", "question": "how", "required_nodes": ["LegData", "Handle"],
             "xfail_nodes": ["Nope"]}
        text = format_explain(explain_question(adapter, q))
        self.assertIn("FRAGILE", text)
        self.assertIn("STUB-ONLY", text)
        self.assertIn("NOT REACHED", text)


if __name__ == "__main__":
    unittest.main()
