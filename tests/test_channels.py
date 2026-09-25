"""Intent-routed retrieval channels (`oregraph/channels.py`) and the two changes to
`query.py` that ship with them: same-label seeds prefer the defining file, and nodes
are ordered by how much of the question their label says, hop by hop.

Each test pins something that went wrong while these were built, named for what a
user would have seen."""
import unittest

import networkx as nx

from oregraph import channels
from oregraph.query import query_question, resolve_question


class Graph:
    """A small merged-graph stand-in (a DiGraph, as graphify loads it)."""

    def __init__(self):
        self.g = nx.DiGraph()

    def node(self, node_id, label, source="", repo="OREData", cls=False, **extra):
        self.g.add_node(node_id, label=label, norm_label=label.lower(),
                        source_file=source, repo=repo, _callable_class=cls,
                        source_location=extra.pop("loc", ""), **extra)
        return node_id

    def edge(self, a, b, relation):
        self.g.add_edge(a, b, relation=relation, confidence="EXTRACTED")

    def entry(self, node_id, domain, name, trade_type="", xml_node="", cpp=""):
        return self.node(node_id, f"{name} [{domain.replace('_', ' ')} mapping]",
                         f"fieldmap/{domain}/{name}", repo="OREFieldmap", kind="entry",
                         domain=domain, entry=name, trade_type=trade_type,
                         xml_node=xml_node, cpp_class_name=cpp)


def labels(g, ids):
    return [g.nodes[n]["label"] for n in ids]


class WordsTest(unittest.TestCase):
    def test_a_typed_identifier_is_split_where_it_is_joined(self):
        # "DefaultCurve" is what people paste; the docs say "Default Curve".
        self.assertEqual(channels.channel_terms("the DefaultCurve config"),
                         ["default", "curve", "config"])

    def test_intent_words_are_not_split(self):
        # complexType became ["complex", "type"], which then matched every
        # "... complexType" node in the schema instead of the topic.
        terms = channels.channel_terms("which complexType defines a bond")
        self.assertIn("complextype", terms)
        self.assertNotIn("complex", terms)

    def test_two_letter_words_survive(self):
        # "FX volatility" lost its "fx" and matched every volatility entry.
        self.assertIn("fx", channels.channel_terms("which convention does an FX volatility config use"))

    def test_the_stemmer_joins_the_forms_people_use(self):
        for a, b in (("interpolate", "interpolation"), ("priced", "pricing"),
                     ("parsed", "parse"), ("swaps", "swap"), ("conventions", "convention")):
            with self.subTest(a=a, b=b):
                self.assertEqual(channels.stem(a), channels.stem(b))
        self.assertNotEqual(channels.stem("swaption"), channels.stem("swap"))


class IntentsTest(unittest.TestCase):
    def intents(self, question):
        return channels.detect_intents(channels.channel_terms(question))

    def test_artifact_kinds(self):
        self.assertTrue(self.intents("what tests cover credit default swaps").tests)
        self.assertTrue(self.intents("what does the ORE user guide say about netting").docs)
        self.assertTrue(self.intents("which XSD complexType defines a swaption").schema)
        self.assertTrue(self.intents("how is a bond priced").pricing)

    def test_a_plain_code_question_names_no_kind(self):
        it = self.intents("how does the Hull-White model work")
        self.assertFalse(it.tests or it.docs or it.schema or it.fieldmap)

    def test_fieldmap_domains_are_named_by_paraphrase(self):
        # "what engine does ORE use to value an FX option" never says "pricing engine".
        for question in ("which pricing engine prices an FX option trade",
                         "what engine does ORE use to value an FX option"):
            with self.subTest(question=question):
                self.assertIn("pricing_engine", self.intents(question).fieldmap)
        self.assertIn("convention", self.intents("which conventions does a curve use").fieldmap)
        self.assertIn("curve_config", self.intents("which curve configuration does a CDS use").fieldmap)


class KindSeedsTest(unittest.TestCase):
    def setUp(self):
        b = Graph()
        b.node("d1", "Default Curve from CDS", "Docs/UserGuide/curve_configurations/default_curves_from_cds.tex", repo="OREDocs")
        b.node("d2", "Netting Set Definitions", "Docs/UserGuide/nettingdata.tex", repo="OREDocs")
        b.node("d3", "Simulation Configuration", "Docs/UserGuide/parameterisation/simulation.tex", repo="OREDocs")
        b.node("t1", "cds.cpp", "OREData/test/cds.cpp", repo="ORETests")
        b.node("t1b", "CommonVars", "OREData/test/cds.cpp", repo="ORETests")
        b.node("t2", "creditdefaultswapdata.cpp", "OREData/test/creditdefaultswapdata.cpp", repo="ORETests")
        b.node("t3", "yieldcurve.cpp", "OREData/test/yieldcurve.cpp", repo="ORETests")
        b.node("x1", "swaptionData (complexType)", "xsd/instruments.xsd", repo="OREXsd")
        b.node("x2", "swapData (complexType)", "xsd/instruments.xsd", repo="OREXsd")
        b.node("x3", "creditDefaultSwapData (complexType)", "xsd/instruments.xsd", repo="OREXsd")
        b.node("x4", "cdsVolatility (complexType)", "xsd/curveconfig.xsd", repo="OREXsd")
        self.b, self.g = b, b.g

    def seeds(self, kind, question, **kw):
        return labels(self.g, channels.kind_seeds(self.g, kind, channels.channel_terms(question), **kw))

    def test_a_page_titled_for_the_topic_is_found_though_no_class_shares_its_score(self):
        self.assertEqual(self.seeds("docs", "how does the ORE user guide describe default curve configuration")[0],
                         "Default Curve from CDS")

    def test_a_pasted_identifier_finds_the_page_titled_with_spaces(self):
        self.assertEqual(self.seeds("docs", "what does the user guide say about the DefaultCurve")[0],
                         "Default Curve from CDS")

    def test_tests_are_found_for_the_words_the_question_uses_not_the_acronym(self):
        found = self.seeds("tests", "what tests cover credit default swaps")
        self.assertIn("cds.cpp", found)
        self.assertIn("creditdefaultswapdata.cpp", found)
        self.assertNotIn("yieldcurve.cpp", found)

    def test_a_file_is_one_answer_and_the_file_node_stands_for_it(self):
        found = self.seeds("tests", "what tests cover credit default swaps")
        self.assertEqual(found.count("cds.cpp") + found.count("CommonVars"), 1)
        self.assertIn("cds.cpp", found)

    def test_every_schema_type_is_its_own_answer_although_they_share_a_file(self):
        found = self.seeds("schema", "which XSD complexType defines a swaption trade")
        self.assertEqual(found[0], "swaptionData (complexType)")

    def test_swaption_is_not_a_swap(self):
        # 'swaption'.startswith('swap') made "swaption" match every swap* type.
        self.assertNotIn("swapData (complexType)",
                         self.seeds("schema", "which XSD complexType defines a swaption trade"))

    def test_a_typed_acronym_finds_the_spelled_out_name_below_the_real_words(self):
        found = self.seeds("schema", "what elements does the schema define for a CDS trade")
        self.assertIn("creditDefaultSwapData (complexType)", found)
        spelled = self.seeds("schema", "how does the ORE XSD define a credit default swap trade")
        # The real words outrank the acronym: cdsVolatility matches "cds" only.
        self.assertEqual(spelled[0], "creditDefaultSwapData (complexType)")

    def test_a_topic_nothing_matches_is_silent(self):
        self.assertEqual(self.seeds("docs", "what does the user guide say about zebras"), [])
        self.assertEqual(self.seeds("tests", "what tests cover"), [])


class FieldmapPriorityTest(unittest.TestCase):
    def setUp(self):
        b = Graph()
        b.node("cds_cls", "CreditDefaultSwap", "portfolio/creditdefaultswap.hpp", cls=True)
        b.node("dcc", "DefaultCurveConfig", "configuration/defaultcurveconfig.hpp", cls=True)
        b.node("ycc", "YieldCurveConfig", "configuration/yieldcurveconfig.hpp", cls=True)
        b.entry("t_cds", "trade", "CDS", trade_type="CreditDefaultSwap", cpp="CreditDefaultSwap")
        b.entry("t_swap", "trade", "Swap", trade_type="Swap")
        b.entry("c_def", "curve_config", "DefaultCurve", xml_node="DefaultCurves")
        b.entry("c_yield", "curve_config", "YieldCurve", xml_node="YieldCurves")
        b.entry("c_bond", "curve_config", "BondYield", xml_node="BondYields")
        b.entry("c_cdsvol", "curve_config", "CDSVolatility", xml_node="CDSVolatilities")
        b.entry("c_fxvol", "curve_config", "FXVolatility", xml_node="FXVolatilities")
        b.entry("v_cds", "convention", "CDS")
        b.entry("v_zero", "convention", "Zero")
        b.entry("v_ois", "convention", "OIS")
        b.entry("p_cds", "pricing_engine", "CreditDefaultSwap")
        b.node("cds_builder", "CreditDefaultSwapEngineBuilder", "portfolio/builders/creditdefaultswap.hpp", cls=True)
        for a, rel, c in (("t_cds", "maps_to_curve_config", "c_def"), ("t_cds", "maps_to_curve_config", "c_yield"),
                          ("t_cds", "maps_to_class", "cds_cls"), ("t_cds", "maps_to_pricing_engine", "p_cds"),
                          ("p_cds", "maps_to_class", "cds_builder"), ("p_cds", "maps_to_class", "cds_cls"),
                          ("c_def", "maps_to_convention", "v_cds"), ("c_def", "maps_to_class", "dcc"),
                          ("c_yield", "maps_to_convention", "v_zero"), ("c_yield", "maps_to_convention", "v_ois"),
                          ("c_yield", "maps_to_class", "ycc"), ("c_cdsvol", "maps_to_convention", "v_cds")):
            b.edge(a, c, rel)
        self.g = b.g

    def priority(self, question):
        terms = channels.channel_terms(question)
        return labels(self.g, channels.fieldmap_priority(
            self.g, terms, channels.detect_intents(terms).fieldmap))

    def test_a_trade_leads_to_the_curve_configs_it_resolves_to(self):
        found = self.priority("which curve config does a credit default swap resolve to")
        for want in ("CDS [trade mapping]", "DefaultCurve [curve config mapping]",
                     "YieldCurve [curve config mapping]", "DefaultCurveConfig"):
            self.assertIn(want, found)

    def test_a_curve_config_leads_to_its_conventions_and_not_to_other_yield_entries(self):
        found = self.priority("which conventions does a yield curve config use")
        self.assertIn("YieldCurve [curve config mapping]", found)
        self.assertIn("Zero [convention mapping]", found)
        self.assertIn("OIS [convention mapping]", found)
        self.assertNotIn("BondYield [curve config mapping]", found)

    def test_an_entry_matching_one_of_two_topic_words_is_not_followed(self):
        # "FX volatility": CDSVolatility matches "volatility" only. Following it
        # returned the CDS convention for a question about FX.
        found = self.priority("which convention does an FX volatility config use")
        self.assertNotIn("CDS [convention mapping]", found)

    def test_a_paraphrase_without_the_domain_phrase_reaches_the_same_entries(self):
        found = self.priority("which engine builder is used to value a credit default swap")
        self.assertIn("CreditDefaultSwapEngineBuilder", found)

    def test_the_marker_word_curve_does_not_hide_the_trade(self):
        # In "curve configuration does a CDS trade use" the entry that matters
        # is the trade; every curve config named ...CurveConfig also says "curve".
        found = self.priority("what curve configuration does a CDS trade use")
        self.assertIn("CDS [trade mapping]", found)
        self.assertIn("DefaultCurve [curve config mapping]", found)

    def test_nothing_matching_is_silent(self):
        self.assertEqual(self.priority("which convention does a zebra use"), [])


class PricingTest(unittest.TestCase):
    def build(self):
        b = Graph()
        b.node("fx", "FxOption", "portfolio/fxoption.hpp", cls=True)
        b.node("build", "build", "portfolio/fxoption.hpp")
        b.node("builder", "FxEuropeanOptionEngineBuilder", "portfolio/builders/fxoption.hpp", cls=True)
        b.node("engine", "AnalyticEuropeanEngine", "pricingengines/vanilla/analyticeuropeanengine.hpp", cls=True)
        b.node("other", "Portfolio", "portfolio/portfolio.hpp", cls=True)
        b.edge("fx", "build", "defines")
        b.edge("build", "builder", "uses")
        b.edge("builder", "engine", "constructs")
        b.node("cap", "CapFloor", "portfolio/capfloor.hpp", cls=True)
        b.entry("e_cap", "pricing_engine", "CapFloor")
        b.node("cap_builder", "CapFloorEngineBuilder", "portfolio/builders/capfloor.hpp", cls=True)
        b.edge("e_cap", "cap", "maps_to_class")
        b.edge("e_cap", "cap_builder", "maps_to_class")
        return b.g

    def test_flow_follows_build_to_its_builder_and_engine(self):
        g = self.build()
        self.assertEqual(labels(g, channels.flow_nodes(g, "fx")),
                         ["FxEuropeanOptionEngineBuilder", "AnalyticEuropeanEngine"])

    def test_flow_is_empty_for_a_class_that_is_not_a_trade(self):
        g = self.build()
        self.assertEqual(channels.flow_nodes(g, "other"), [])

    def test_the_registry_finds_a_builder_no_code_edge_reaches(self):
        # A builder is looked up by trade-type string; CapFloor::build has no edge to it.
        g = self.build()
        self.assertEqual(labels(g, channels.registry_builders(g, "cap")), ["CapFloorEngineBuilder"])


class StructureTest(unittest.TestCase):
    def build(self):
        b = Graph()
        b.node("hdr", "binomialtree.hpp", "methods/lattices/binomialtree.hpp")
        b.node("bt", "BinomialTree", "methods/lattices/binomialtree.hpp", cls=True, loc="L40")
        for i, name in enumerate(("Tian", "CoxRossRubinstein", "JarrowRudd")):
            n = b.node(f"s{i}", name, "methods/lattices/binomialtree.hpp", cls=True, loc=f"L{100 + 30 * i}")
            b.edge("hdr", n, "contains")
        b.node("far", "Elsewhere", "methods/lattices/other.hpp", cls=True, loc="L5")
        b.edge("hdr", "bt", "contains")
        b.node("hw", "HullWhite", "models/hullwhite.hpp", cls=True)
        b.node("oam", "OneFactorAffineModel", "models/onefactoraffinemodel.hpp", cls=True)
        b.node("ofm", "OneFactorModel", "models/onefactormodel.hpp", cls=True)
        b.node("srm", "ShortRateModel", "models/model.hpp", cls=True)
        b.edge("hw", "oam", "inherits")
        b.edge("oam", "ofm", "inherits")
        b.edge("ofm", "srm", "inherits")
        return b.g

    def test_siblings_are_the_classes_in_the_same_header_nearest_first(self):
        g = self.build()
        self.assertEqual(labels(g, channels.file_siblings(g, "bt")),
                         ["Tian", "CoxRossRubinstein", "JarrowRudd"])

    def test_siblings_stop_at_the_limit(self):
        g = self.build()
        self.assertEqual(len(channels.file_siblings(g, "bt", limit=2)), 2)

    def test_ancestors_walk_the_inheritance_chain_upwards(self):
        g = self.build()
        self.assertEqual(labels(g, channels.ancestors(g, "hw")),
                         ["OneFactorAffineModel", "OneFactorModel", "ShortRateModel"])

    def test_a_non_class_has_neither(self):
        g = self.build()
        g.nodes["bt"]["_callable_class"] = False
        self.assertEqual(channels.file_siblings(g, "bt"), [])
        self.assertEqual(channels.ancestors(g, "bt"), [])


class ResolveQuestionTest(unittest.TestCase):
    def test_a_type_mention_in_a_busier_header_does_not_beat_the_defining_file(self):
        # `DayCounter` the class (degree 3) vs the node every header that holds a
        # DayCounter member gets for the type (callablebond.hpp, degree 70 in the
        # real graph): "how is a day count convention implemented" seeded the latter.
        b = Graph()
        b.node("cls", "DayCounter", "time/daycounter.hpp", cls=True)
        b.node("ref", "DayCounter", "experimental/callablebonds/callablebond.hpp", cls=True)
        for i in range(10):
            b.node(f"u{i}", f"user{i}", "x.hpp")
            b.edge("ref", f"u{i}", "references")
        b.edge("cls", "u0", "references")
        seeds = resolve_question(b.g, "how is a day count convention implemented")
        self.assertEqual(b.g.nodes[seeds[0]]["source_file"], "time/daycounter.hpp")


class QueryQuestionTest(unittest.TestCase):
    def star(self, *names, seed="Bond", source="instruments/bond.hpp"):
        b = Graph()
        b.node("seed", seed, source, cls=True)
        for i, name in enumerate(names):
            b.node(f"n{i}", name, f"x/{name}.hpp")
            b.edge("seed", f"n{i}", "uses")
        return b.g

    def answer(self, g, question, **kw):
        text = query_question(g, question, **kw)
        return [line.split(" [src=")[0][5:] for line in text.splitlines() if line.startswith("NODE ")]

    def test_ties_keep_the_traversal_order(self):
        # With no label saying more of the question, the answer is the traversal's.
        g = self.star("alpha", "beta", "gamma")
        self.assertEqual(self.answer(g, "how is a bond"), ["Bond", "alpha", "beta", "gamma"])

    def test_a_label_covering_more_of_the_question_comes_first_within_its_hop(self):
        g = self.star("alpha", "parsePeriod", "gamma", seed="Period")
        self.assertEqual(self.answer(g, "what is a Period and how is it parsed")[:3],
                         ["Period", "parsePeriod", "alpha"])

    def test_a_single_shared_word_never_lifts_a_node_over_a_nearer_hop(self):
        b = Graph()
        b.node("seed", "Bond", "instruments/bond.hpp", cls=True)
        b.node("near", "alpha", "x/alpha.hpp")
        b.node("far", "bondHelper", "x/bondhelper.hpp")
        b.edge("seed", "near", "uses")
        b.edge("near", "far", "uses")
        self.assertEqual(self.answer(b.g, "how is a bond priced")[:3], ["Bond", "alpha", "bondHelper"])

    def test_a_label_saying_two_words_of_the_question_is_surfaced_wherever_it_is(self):
        # `parsePeriod` sits two hops out; nothing seeds it and no channel names it.
        b = Graph()
        b.node("seed", "Period", "time/period.hpp", cls=True)
        b.node("near", "alpha", "x/alpha.hpp")
        b.node("far", "parsePeriod", "utilities/parsers.cpp")
        b.edge("seed", "near", "uses")
        b.edge("near", "far", "uses")
        self.assertEqual(self.answer(b.g, "what is a Period and how is it parsed")[:3],
                         ["Period", "parsePeriod", "alpha"])

    def test_the_members_other_code_calls_come_before_the_ones_nobody_does(self):
        b = Graph()
        b.node("seed", "Calendar", "time/calendar.hpp", cls=True)
        for i, name in enumerate(("impl_", "isBusinessDay", "name_")):
            b.node(f"m{i}", name, "time/calendar.hpp")
            b.edge("seed", f"m{i}", "defines")
        b.node("user", "Schedule", "time/schedule.hpp")
        b.edge("user", "m1", "calls")
        self.assertEqual(self.answer(b.g, "how does QuantLib represent a calendar")[:3],
                         ["Calendar", "isBusinessDay", "impl_"])

    def test_the_kind_a_question_asks_for_leads_the_answer(self):
        b = Graph()
        b.node("seed", "CreditDefaultSwap", "instruments/creditdefaultswap.hpp", cls=True)
        b.node("t1", "cds.cpp", "OREData/test/cds.cpp", repo="ORETests")
        text = self.answer(b.g, "what tests cover credit default swaps")
        self.assertEqual(text[0], "cds.cpp")

    def test_the_tail_completes_the_answer_without_being_expanded(self):
        g = Graph()
        g.node("seed", "BinomialTree", "methods/lattices/binomialtree.hpp", cls=True, loc="L1")
        g.node("hdr", "binomialtree.hpp", "methods/lattices/binomialtree.hpp")
        g.node("sib", "CoxRossRubinstein", "methods/lattices/binomialtree.hpp", cls=True, loc="L9")
        g.node("noise", "unrelated", "x/unrelated.hpp")
        g.edge("hdr", "seed", "contains")
        g.edge("hdr", "sib", "contains")
        g.edge("sib", "noise", "uses")
        found = self.answer(g.g, "how does the binomial tree work", depth=1)
        self.assertIn("CoxRossRubinstein", found)
        self.assertNotIn("unrelated", found)

    def test_nothing_to_go_on_is_still_no_match(self):
        g = self.star("alpha")
        self.assertTrue(query_question(g, "zzzz qqqq").startswith("NO MATCH"))


if __name__ == "__main__":
    unittest.main()
