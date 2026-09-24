import unittest

from oregraph.bench import _missing_nodes, grade_answer


def answer(*nodes):
    """A query_graph-shaped answer: one `NODE <label> [src=<file> ...]` per node."""
    return "\n".join(f"NODE {label} [src={src} loc=L1]" for label, src in nodes)


class MissingNodesTest(unittest.TestCase):
    def test_label_matches_whole_not_substring(self):
        out = answer(("SwapIndex", "indexes/swapindex.hpp"))
        self.assertEqual(_missing_nodes(out, ["Swap"]), ["Swap"])
        self.assertEqual(_missing_nodes(out, ["SwapIndex"]), [])

    def test_file_qualifier_disambiguates_duplicate_labels(self):
        out = answer(("YieldCurve", "termstructures/yieldcurve.hpp"))
        self.assertEqual(_missing_nodes(out, ["YieldCurve@marketdata/yieldcurve.hpp"]),
                         ["YieldCurve@marketdata/yieldcurve.hpp"])
        out = answer(("YieldCurve", "marketdata/yieldcurve.hpp"))
        self.assertEqual(_missing_nodes(out, ["YieldCurve@marketdata/yieldcurve.hpp"]), [])

    def test_src_entry_matches_any_node_from_that_path(self):
        out = answer(("Foo", "test/swaption/swaption.cpp"))
        self.assertEqual(_missing_nodes(out, ["src:test/swaption"]), [])
        self.assertEqual(_missing_nodes(out, ["src:test/bond"]), ["src:test/bond"])

    def test_reports_only_the_missing_entries_in_order(self):
        out = answer(("A", "a.hpp"), ("C", "c.hpp"))
        self.assertEqual(_missing_nodes(out, ["A", "B", "C", "D"]), ["B", "D"])

    def test_empty_answer_misses_everything(self):
        self.assertEqual(_missing_nodes("", ["A", "src:x"]), ["A", "src:x"])


class GradeAnswerTest(unittest.TestCase):
    def grade(self, out, **question):
        return grade_answer(out, {"id": "q", "question": "?", **question})

    def test_no_rubric_is_ungraded(self):
        self.assertEqual(self.grade(answer(("A", "a.hpp"))), (None, [], []))

    def test_required_all_present_passes(self):
        self.assertEqual(self.grade(answer(("A", "a.hpp")), required_nodes=["A"]),
                         ("pass", [], []))

    def test_required_missing_fails_and_names_it(self):
        status, missing, gaps = self.grade(answer(("A", "a.hpp")),
                                           required_nodes=["A", "B"])
        self.assertEqual((status, missing, gaps), ("fail", ["B"], []))

    def test_unmet_known_gap_is_xfail_not_fail(self):
        status, missing, gaps = self.grade(answer(("A", "a.hpp")),
                                           required_nodes=["A"], xfail_nodes=["B"])
        self.assertEqual((status, missing, gaps), ("xfail", [], ["B"]))

    def test_reached_known_gap_is_xpass(self):
        status, missing, gaps = self.grade(answer(("A", "a.hpp"), ("B", "b.hpp")),
                                           xfail_nodes=["B", "C"])
        self.assertEqual((status, missing, gaps), ("xpass", [], ["C"]))

    def test_required_still_gates_when_a_gap_is_also_declared(self):
        # A half-right question: the working half must keep gating, and the gap
        # must not mask the failure.
        status, missing, _ = self.grade(answer(("Z", "z.hpp")),
                                        required_nodes=["A"], xfail_nodes=["B"])
        self.assertEqual((status, missing), ("fail", ["A"]))

    def test_fieldmap_rubric_skipped_without_snapshot(self):
        for entry in ("EuropeanSwaption@fieldmap/pricing_engine",
                      "src:fieldmap/pricing_engine"):
            with self.subTest(entry=entry):
                self.assertEqual(
                    grade_answer("", {"required_nodes": [entry]}, has_fieldmap=False),
                    ("skip", [], []))
                self.assertEqual(
                    grade_answer("", {"xfail_nodes": [entry]}, has_fieldmap=False),
                    ("skip", [], []))

    def test_fieldmap_rubric_graded_when_snapshot_present(self):
        status, missing, _ = grade_answer(
            "", {"required_nodes": ["X@fieldmap/trade"]}, has_fieldmap=True)
        self.assertEqual((status, missing), ("fail", ["X@fieldmap/trade"]))

    def test_non_fieldmap_rubric_unaffected_by_missing_snapshot(self):
        self.assertEqual(
            grade_answer(answer(("A", "a.hpp")), {"required_nodes": ["A"]},
                         has_fieldmap=False),
            ("pass", [], []))


if __name__ == "__main__":
    unittest.main()
