import unittest

import networkx as nx

from oregraph.query import _CONCEPT_SEEDS, _mentions, resolve_question


def graph(*nodes):
    """Nodes as (id, label, is_class); labels normalise the way merge writes them."""
    g = nx.MultiDiGraph()
    for node_id, label, is_class in nodes:
        g.add_node(node_id, label=label, norm_label=label.lower(),
                   source_file=f"{node_id}.hpp", _callable_class=is_class)
    return g


class MentionsTest(unittest.TestCase):
    def test_matches_the_plain_word(self):
        self.assertTrue(_mentions(["how", "sensitivity", "works"], "sensitivity"))

    def test_matches_an_inflected_word(self):
        # "sensitivities" and "bootstrapping" are how people actually ask.
        self.assertTrue(_mentions(["portfolio", "sensitivities"], "sensitivity"))
        self.assertTrue(_mentions(["curve", "bootstrapping"], "bootstrap"))

    def test_matches_a_multi_word_concept_only_when_adjacent(self):
        self.assertTrue(_mentions(["the", "yield", "curve", "build"], "yield curve"))
        self.assertFalse(_mentions(["yield", "of", "a", "curve"], "yield curve"))

    def test_short_words_must_match_exactly(self):
        # Prefix matching on a 3-letter key would fire on "amcharts", "csavvy".
        self.assertTrue(_mentions(["what", "amc", "does"], "amc"))
        self.assertFalse(_mentions(["amcalculator"], "amc"))


class ResolveQuestionTest(unittest.TestCase):
    def label(self, g, node_ids):
        return [g.nodes[n]["label"] for n in node_ids]

    def test_class_outranks_a_member_that_matches_exactly(self):
        # The defect this whole seeder exists for: `sensitivity` is a real field
        # name, and matching it exactly must not outrank the class named after
        # the same concept.
        g = graph(("field", "sensitivity", False),
                  ("cls", "SensitivityAnalysis", True))
        seeds = self.label(g, resolve_question(g, "how is sensitivity computed"))
        self.assertEqual(seeds[0], "SensitivityAnalysis")
        if "sensitivity" in seeds:
            self.assertLess(seeds.index("SensitivityAnalysis"),
                            seeds.index("sensitivity"))

    def test_adjacent_words_join_into_an_identifier(self):
        g = graph(("y", "yield", False), ("c", "curve", False),
                  ("yc", "YieldCurve", True))
        seeds = self.label(g, resolve_question(g, "how is a yield curve built"))
        self.assertEqual(seeds[0], "YieldCurve")

    def test_concept_alias_bridges_a_name_the_code_does_not_share(self):
        # Nothing in ORE is called "xva"; it is computed in PostProcess.
        g = graph(("pp", "PostProcess", True), ("other", "Portfolio", True))
        seeds = self.label(g, resolve_question(g, "how is XVA computed"))
        self.assertEqual(seeds, ["PostProcess"])

    def test_unknown_question_seeds_nothing_rather_than_guessing(self):
        g = graph(("pp", "PostProcess", True))
        self.assertEqual(resolve_question(g, "zzzz qqqq"), [])


class ConceptSeedsTest(unittest.TestCase):
    def test_keys_are_lowercase_and_values_are_non_empty(self):
        for concept, targets in _CONCEPT_SEEDS.items():
            with self.subTest(concept=concept):
                self.assertEqual(concept, concept.lower())
                self.assertTrue(targets)

    def test_no_concept_is_a_duplicate_of_another(self):
        self.assertEqual(len(_CONCEPT_SEEDS), len(set(_CONCEPT_SEEDS)))


if __name__ == "__main__":
    unittest.main()
