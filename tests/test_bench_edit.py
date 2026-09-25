"""`bench --promote`: textual edits that keep the hand-formatted layout."""
import difflib
import json
import unittest
from pathlib import Path

from oregraph.bench_cli import promotable
from oregraph.bench_edit import (_column, _member, add_fields_text,
                                 append_questions_text, format_question,
                                 parse_spans, promote_text, render_list)

SUITE = Path(__file__).resolve().parent.parent / "bench" / "source_questions.json"

SAMPLE = '''{
  "meta": {"version": 5},
  "questions": [
    {"id": "s01", "question": "one", "mode": "bfs", "depth": 3,
     "required_nodes": ["A@a.hpp",
                        "B@b.hpp"],
     "xfail_nodes": ["G1@g.hpp",
                     "G2@g.hpp"]},
    {"id": "s02", "question": "two", "mode": "bfs", "depth": 3,
     "required_nodes": ["A"],
     "xfail_nodes": ["G"]},
    {"id": "s03", "question": "three", "mode": "bfs", "depth": 2,
     "xfail_nodes": ["X",
                     "Y"]},
    {"id": "s04", "question": "four", "mode": "bfs", "depth": 2,
     "required_nodes": ["Z"]}
  ]
}
'''


def changed_lines(before, after):
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), n=0, lineterm="")
    return [l for l in diff if l[:1] in "+-" and l[:3] not in ("+++", "---")]


class PromoteTextTest(unittest.TestCase):
    def promote(self, moves, text=SAMPLE):
        out = promote_text(text, moves)
        return out, {q["id"]: q for q in json.loads(out)["questions"]}

    def test_appends_to_required_in_its_own_alignment(self):
        out, qs = self.promote({"s01": ["G1@g.hpp"]})
        self.assertEqual(qs["s01"]["required_nodes"], ["A@a.hpp", "B@b.hpp", "G1@g.hpp"])
        self.assertEqual(qs["s01"]["xfail_nodes"], ["G2@g.hpp"])
        self.assertIn('     "required_nodes": ["A@a.hpp",\n'
                      '                        "B@b.hpp",\n'
                      '                        "G1@g.hpp"],\n'
                      '     "xfail_nodes": ["G2@g.hpp"]},\n', out)

    def test_only_the_touched_lines_change(self):
        out, _ = self.promote({"s01": ["G1@g.hpp"]})
        touched = changed_lines(SAMPLE, out)
        self.assertTrue(all("s02" not in l and "s03" not in l and "s04" not in l
                            for l in touched))
        # every line of the other questions is byte-identical
        tail = SAMPLE[SAMPLE.index('{"id": "s02"'):]
        self.assertTrue(out.endswith(tail))

    def test_emptied_xfail_is_removed_with_its_separator(self):
        out, qs = self.promote({"s02": ["G"]})
        self.assertEqual(qs["s02"]["required_nodes"], ["A", "G"])
        self.assertNotIn("xfail_nodes", qs["s02"])
        self.assertIn('     "required_nodes": ["A",\n'
                      '                        "G"]},\n', out)

    def test_all_gaps_moved_renames_xfail_in_place(self):
        out, qs = self.promote({"s03": ["X", "Y"]})
        self.assertEqual(qs["s03"]["required_nodes"], ["X", "Y"])
        self.assertNotIn("xfail_nodes", qs["s03"])
        self.assertIn('     "required_nodes": ["X",\n'
                      '                        "Y"]},\n', out)

    def test_some_gaps_moved_creates_required_before_xfail(self):
        out, qs = self.promote({"s03": ["Y"]})
        self.assertEqual(qs["s03"]["required_nodes"], ["Y"])
        self.assertEqual(qs["s03"]["xfail_nodes"], ["X"])
        self.assertIn('     "required_nodes": ["Y"],\n     "xfail_nodes": ["X"]},\n', out)

    def test_several_questions_at_once(self):
        out, qs = self.promote({"s01": ["G2@g.hpp"], "s02": ["G"], "s03": ["X"]})
        self.assertEqual(qs["s01"]["xfail_nodes"], ["G1@g.hpp"])
        self.assertNotIn("xfail_nodes", qs["s02"])
        self.assertEqual(qs["s03"]["xfail_nodes"], ["Y"])
        self.assertEqual(qs["s04"], {"id": "s04", "question": "four", "mode": "bfs",
                                     "depth": 2, "required_nodes": ["Z"]})

    def test_no_moves_is_a_no_op(self):
        self.assertEqual(promote_text(SAMPLE, {}), SAMPLE)
        self.assertEqual(promote_text(SAMPLE, {"s01": []}), SAMPLE)

    def test_refuses_an_entry_that_is_not_a_known_gap(self):
        with self.assertRaises(ValueError):
            promote_text(SAMPLE, {"s01": ["A@a.hpp"]})
        with self.assertRaises(ValueError):
            promote_text(SAMPLE, {"s09": ["X"]})
        with self.assertRaises(ValueError):
            promote_text(SAMPLE, {"s04": ["Z"]})     # no xfail_nodes at all

    def test_crlf_files_stay_crlf(self):
        crlf = SAMPLE.replace("\n", "\r\n")
        out = promote_text(crlf, {"s01": ["G1@g.hpp"], "s03": ["X", "Y"]})
        self.assertNotIn("\n", out.replace("\r\n", ""))
        self.assertEqual(json.loads(out)["questions"][0]["required_nodes"][-1], "G1@g.hpp")

    def test_other_fields_after_xfail_survive_its_removal(self):
        text = SAMPLE.replace('     "xfail_nodes": ["G"]},',
                              '     "xfail_nodes": ["G"],\n     "why": {"A": "because"}},')
        out, qs = self.promote({"s02": ["G"]}, text)
        self.assertEqual(qs["s02"]["why"], {"A": "because"})
        self.assertEqual(qs["s02"]["required_nodes"], ["A", "G"])
        self.assertNotIn("xfail_nodes", qs["s02"])


class RealFileLayoutTest(unittest.TestCase):
    """The renderer's layout rule has to be the one the real file uses, or
    promoting would reflow every list it touches."""

    def test_every_list_in_the_real_file_renders_to_itself(self):
        text = SUITE.read_bytes().decode("utf-8")
        nl = "\r\n" if "\r\n" in text else "\n"
        questions = _member(parse_spans(text), "questions")[3].items
        checked = 0
        for q in questions:
            for key in ("required_nodes", "xfail_nodes"):
                member = _member(q, key)
                if member is None:
                    continue
                span = text[member[3].start:member[3].end]
                col = _column(text, member[3].start) + 1
                self.assertEqual(render_list(json.loads(span), col, nl), span, key)
                checked += 1
        self.assertGreater(checked, 50)

    def test_promoting_in_the_real_file_touches_only_the_lines_it_names(self):
        text = SUITE.read_bytes().decode("utf-8")
        suite = json.loads(text)
        move = {q["id"]: [q["xfail_nodes"][0]] for q in suite["questions"]
                if q.get("xfail_nodes") and q["id"] in ("s03", "s06", "s19")}
        out = promote_text(text, move)
        after = {q["id"]: q for q in json.loads(out)["questions"]}
        for qid, entries in move.items():
            self.assertIn(entries[0], after[qid]["required_nodes"])
            self.assertNotIn(entries[0], after[qid].get("xfail_nodes", []))
        untouched = [q for q in suite["questions"] if q["id"] not in move]
        self.assertEqual([q for q in json.loads(out)["questions"] if q["id"] not in move],
                         untouched)
        touched = changed_lines(text.replace("\r\n", "\n"), out.replace("\r\n", "\n"))
        self.assertLessEqual(len(touched), 16)


class AuthoringTest(unittest.TestCase):
    """Writing new questions and fields in the file's own layout."""

    def real(self):
        text = SUITE.read_bytes().decode("utf-8")
        return text, "\r\n" if "\r\n" in text else "\n"

    def test_format_question_reproduces_every_existing_question(self):
        text, nl = self.real()
        questions = _member(parse_spans(text), "questions")[3].items
        for span in questions:
            original = text[text.rfind("\n", 0, span.start) + 1:span.end]
            self.assertEqual(format_question(json.loads(text[span.start:span.end]), nl),
                             original)
        self.assertGreaterEqual(len(questions), 50)

    def test_new_field_kinds_follow_the_same_alignment(self):
        q = {"id": "s99", "question": "q", "mode": "bfs", "depth": 2,
             "required_nodes": ["A", "B"], "variants": ["v1", "v2"],
             "controls": {"A": ["c1", "c2"], "*": ["c3"]},
             "why": {"A": "because", "B": "so"}}
        self.assertEqual(format_question(q), "\n".join([
            '    {"id": "s99", "question": "q", "mode": "bfs", "depth": 2,',
            '     "required_nodes": ["A",',
            '                        "B"],',
            '     "variants": ["v1",',
            '                  "v2"],',
            '     "controls": {"A": ["c1", "c2"],',
            '                  "*": ["c3"]},',
            '     "why": {"A": "because",',
            '             "B": "so"}}']))
        self.assertEqual(json.loads(format_question(q)), q)

    def test_append_questions_leaves_the_rest_of_the_file_alone(self):
        text, nl = self.real()
        new = [{"id": "s98", "question": "one", "mode": "bfs", "depth": 2,
                "required_nodes": ["A", "B"]},
               {"id": "s99", "question": "two", "mode": "dfs", "depth": 3,
                "xfail_nodes": ["C"]}]
        out = append_questions_text(text, new)
        self.assertEqual(json.loads(out)["questions"][-2:], new)
        original_end = text.index(nl + "  ]")
        self.assertTrue(out.startswith(text[:original_end]))
        self.assertTrue(out.endswith(text[original_end:]))
        self.assertEqual(append_questions_text(text, []), text)

    def test_add_fields_appends_after_the_last_member(self):
        out = add_fields_text(SAMPLE, {"s02": {"variants": ["a", "b"]},
                                       "s04": {"controls": ["c"], "why": {"Z": "r"}}})
        qs = {q["id"]: q for q in json.loads(out)["questions"]}
        self.assertEqual(qs["s02"]["variants"], ["a", "b"])
        self.assertEqual(qs["s04"]["why"], {"Z": "r"})
        self.assertIn('     "xfail_nodes": ["G"],\n     "variants": ["a",\n'
                      '                  "b"]},\n', out)
        self.assertEqual(changed_lines(SAMPLE, out)[0][0], "-")
        untouched = SAMPLE[SAMPLE.index('{"id": "s01"'):SAMPLE.index('{"id": "s02"')]
        self.assertIn(untouched, out)

    def test_add_fields_refuses_to_overwrite(self):
        with self.assertRaises(ValueError):
            add_fields_text(SAMPLE, {"s01": {"required_nodes": ["X"]}})
        with self.assertRaises(ValueError):
            add_fields_text(SAMPLE, {"s77": {"why": {}}})

    def test_add_fields_keeps_crlf(self):
        crlf = SAMPLE.replace("\n", "\r\n")
        out = add_fields_text(crlf, {"s02": {"variants": ["a", "b"]}})
        self.assertNotIn("\n", out.replace("\r\n", ""))
        self.assertEqual(json.loads(out)["questions"][1]["variants"], ["a", "b"])


class PromotableTest(unittest.TestCase):
    def row(self, **kw):
        base = {"id": "s01", "answer_status": "xpass", "closed_gaps": ["G"],
                "standing": {"G": {"rank": 5, "margin": 80, "stub_only": False}},
                "weak": {}}
        return {**base, **kw}

    def test_a_solid_reached_gap_is_promoted(self):
        moves, held = promotable([self.row()])
        self.assertEqual((moves, held), ({"s01": ["G"]}, []))

    def test_only_xpass_rows_are_considered(self):
        self.assertEqual(promotable([self.row(answer_status="pass")]), ({}, []))

    def test_weak_fragile_and_stub_only_are_held_back_with_a_reason(self):
        cases = {
            "weak": self.row(weak={"G": ["some control"]}),
            "fragile": self.row(standing={"G": {"rank": 80, "margin": 3, "stub_only": False}}),
            "stub-only": self.row(standing={"G": {"rank": 5, "margin": 80, "stub_only": True}}),
        }
        for reason, r in cases.items():
            with self.subTest(reason=reason):
                moves, held = promotable([r])
                self.assertEqual(moves, {})
                self.assertIn(reason, held[0][2])
                moves, held = promotable([r], allow_weak=True)
                self.assertEqual((moves, held), ({"s01": ["G"]}, []))


if __name__ == "__main__":
    unittest.main()
