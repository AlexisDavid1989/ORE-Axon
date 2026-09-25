"""`bench --baseline`: what counts as a regression and what is only a change."""
import unittest

from oregraph.bench_compare import compare_results, format_comparison


def row(qid="s01", status="pass", **kw):
    base = {"id": qid, "question": f"question {qid}", "answer_status": status,
            "graph_tokens": 2000, "source_files": 10, "source_tokens": 5000,
            "missing_nodes": [], "known_gaps": [], "closed_gaps": [],
            "reached_nodes": ["A"], "weak": {}, "fragile": [], "variants": [],
            "answer_sha256": "aaa"}
    return {**base, **kw}


def results(*rows, **totals):
    return {"meta": {"graphify_version": "0.9.44", "graph_nodes": 10, "graph_edges": 20,
                     "questions_sha256": "x"},
            "vs_source": {"rows": list(rows), "totals": totals}}


def compare(old_rows, new_rows, **kw):
    return compare_results(results(*old_rows), results(*new_rows), **kw)


class RegressionTest(unittest.TestCase):
    def test_identical_runs_are_identical(self):
        c = compare([row()], [row()])
        self.assertTrue(c["identical"])
        self.assertTrue(c["ok"])
        self.assertEqual(c["changes"], [])

    def test_a_question_that_now_fails_is_a_regression(self):
        c = compare([row()], [row(status="fail", missing_nodes=["A"], reached_nodes=[])])
        self.assertEqual(c["regressions"], 1)
        self.assertFalse(c["ok"])
        lines = c["changes"][0]["regressions"]
        self.assertTrue(any("PASS -> FAIL" in l for l in lines))
        self.assertTrue(any("now missing: A" in l for l in lines))

    def test_a_fixed_question_is_an_improvement_not_a_regression(self):
        c = compare([row(status="fail", missing_nodes=["A"], reached_nodes=[])], [row()])
        self.assertEqual(c["regressions"], 0)
        self.assertTrue(c["ok"])
        self.assertTrue(c["changes"][0]["improved"])

    def test_a_reopened_known_gap_is_a_regression(self):
        old = row(status="xpass", closed_gaps=["G"], reached_nodes=["A", "G"])
        new = row(status="xfail", known_gaps=["G"], closed_gaps=[], reached_nodes=["A"])
        c = compare([old], [new])
        self.assertEqual(c["regressions"], 1)
        self.assertTrue(any("no longer reached: G" in l for l in c["changes"][0]["regressions"]))

    def test_reopened_gap_is_seen_in_an_older_baseline_without_reached_nodes(self):
        old = row(status="xpass", closed_gaps=["G"])
        new = row(status="xfail", known_gaps=["G"])
        for r in (old, new):
            del r["reached_nodes"]
        self.assertEqual(compare([old], [new])["regressions"], 1)

    def test_promotion_is_not_a_regression(self):
        # G moved from xfail_nodes to required_nodes and is still reached
        old = row(status="xpass", closed_gaps=["G"], reached_nodes=["A", "G"])
        new = row(status="pass", closed_gaps=[], reached_nodes=["A", "G"])
        c = compare([old], [new])
        self.assertEqual(c["regressions"], 0)

    def test_a_newly_weak_entry_is_a_regression(self):
        c = compare([row(weak={})], [row(weak={"A": ["a control"]})])
        self.assertEqual(c["regressions"], 1)
        self.assertTrue(any("newly weak" in l for l in c["changes"][0]["regressions"]))

    def test_weak_is_not_judged_against_a_baseline_that_never_measured_it(self):
        old = row()
        del old["weak"]
        self.assertEqual(compare([old], [row(weak={"A": ["c"]})])["regressions"], 0)

    def test_a_variant_that_now_fails_or_loses_a_node_is_a_regression(self):
        v = lambda status, lost=(): {"question": "v", "answer_status": status,
                                     "lost": list(lost)}
        c = compare([row(variants=[v("pass")])], [row(variants=[v("fail", ["A"])])])
        self.assertEqual(c["regressions"], 1)
        c = compare([row(variants=[v("xfail")])], [row(variants=[v("xfail", ["A"])])])
        self.assertEqual(c["regressions"], 1)
        c = compare([row(variants=[v("fail", ["A"])])], [row(variants=[v("pass")])])
        self.assertEqual(c["regressions"], 0)

    def test_a_removed_question_is_a_regression_an_added_one_is_not(self):
        c = compare([row("s01"), row("s02")], [row("s01"), row("s03")])
        self.assertEqual(c["removed"], ["s02"])
        self.assertEqual(c["added"], ["s03"])
        self.assertEqual(c["regressions"], 1)

    def test_going_from_graded_to_skipped_is_a_regression(self):
        c = compare([row()], [row(status="skip", reached_nodes=[])])
        self.assertEqual(c["regressions"], 1)


class ChangeTest(unittest.TestCase):
    def test_token_and_file_changes_are_reported_but_do_not_fail(self):
        c = compare([row()], [row(graph_tokens=1990, source_files=9, answer_sha256="bbb")])
        self.assertEqual(c["regressions"], 0)
        self.assertTrue(c["ok"])
        self.assertFalse(c["identical"])
        text = " ".join(c["changes"][0]["other"])
        self.assertIn("tokens 2,000 -> 1,990", text)
        self.assertIn("source files 10 -> 9", text)

    def test_a_changed_answer_with_the_same_numbers_is_noticed(self):
        c = compare([row()], [row(answer_sha256="bbb")])
        self.assertFalse(c["identical"])
        self.assertIn("answer changed", c["changes"][0]["other"][0])

    def test_strict_fails_on_any_difference(self):
        self.assertFalse(compare([row()], [row(answer_sha256="bbb")], strict=True)["ok"])
        self.assertTrue(compare([row()], [row()], strict=True)["ok"])

    def test_becoming_fragile_is_information(self):
        c = compare([row()], [row(fragile=["A"])])
        self.assertEqual(c["regressions"], 0)
        self.assertIn("newly fragile: A", c["changes"][0]["other"])

    def test_formatting_names_the_regression(self):
        c = compare([row()], [row(status="fail", missing_nodes=["A"], reached_nodes=[])])
        text = format_comparison(c, "old.json")
        self.assertIn("REGRESSION", text)
        self.assertIn("1 regression", text)
        self.assertIn("old.json", text)


if __name__ == "__main__":
    unittest.main()
