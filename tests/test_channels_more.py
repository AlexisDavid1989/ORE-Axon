"""Further behaviour of `oregraph/channels.py`, each test named for what a user would have
seen go wrong: names with no word boundary, neighbours that share only the seed's word,
derived classes of a framework base, a builder the code never links to, a type's components."""
import unittest

from oregraph import channels
from test_channels import Graph, QueryQuestionTest, labels


class SegmentationTest(unittest.TestCase):
    VOCAB = frozenset({"digital", "cms", "credit", "default", "swap", "data", "zero", "coupon"})

    def test_a_name_with_no_boundary_is_cut_into_the_graphs_own_words(self):
        self.assertEqual(channels.segment("digitalcms", self.VOCAB), ["digital", "cms"])
        self.assertEqual(channels.segment("creditdefaultswapdata", self.VOCAB),
                         ["credit", "default", "swap", "data"])

    def test_a_word_or_an_uncuttable_string_is_left_whole(self):
        self.assertEqual(channels.segment("swap", self.VOCAB), ["swap"])
        self.assertEqual(channels.segment("sensitivityanalysis", self.VOCAB), ["sensitivityanalysis"])

    def test_the_vocabulary_ignores_names_that_are_themselves_unbroken(self):
        # A file node labelled `creditdefaultswapdata.cpp` must not put that string in the
        # vocabulary: it could then never be cut.
        b = Graph()
        b.node("f", "creditdefaultswapdata.cpp", "test/creditdefaultswapdata.cpp", repo="ORETests")
        b.node("c", "CreditDefaultSwap", "x.hpp")
        vocab = channels._vocabulary(b.g)
        self.assertNotIn("creditdefaultswapdata", vocab)
        self.assertIn("credit", vocab)

    def test_a_test_file_is_found_through_its_segmented_name(self):
        b = Graph()
        b.node("v", "CreditDefaultSwap", "x.hpp")
        b.node("t", "digitalcms.cpp", "OREData/test/digitalcms.cpp", repo="ORETests")
        b.node("cms", "CMSSpread", "y.hpp")
        b.node("dig", "DigitalOption", "z.hpp")
        found = labels(b.g, channels.kind_seeds(b.g, "tests",
                                                channels.channel_terms("what tests cover the CMS trades")))
        self.assertIn("digitalcms.cpp", found)


class OrderingTest(unittest.TestCase):
    def test_words_a_seed_already_says_earn_no_ordering_credit(self):
        # Fifty neighbours of a `Swap` seed are named ...Swap...; that is the seed's word,
        # not a sign that the question wants them over `LegData`.
        b = Graph()
        b.node("seed", "Swap", "portfolio/swap.hpp", cls=True)
        stems = channels.content_stems("how is a swap priced")
        self.assertEqual(channels.unaccounted_stems(b.g, stems, ["seed"]), {channels.stem("priced")})

    def test_a_neighbour_named_after_swap_does_not_outrank_a_referenced_class(self):
        b = Graph()
        b.node("seed", "Swap", "portfolio/swap.hpp", cls=True)
        for i, name in enumerate(("swapLength", "buildSwap", "LegData")):
            b.node(f"n{i}", name, f"x/{name}.hpp")
            b.edge("seed", f"n{i}", "references")
        found = QueryQuestionTest().answer(b.g, "how is a swap priced")
        self.assertEqual(found[:4], ["Swap", "swapLength", "buildSwap", "LegData"])      # order kept

    def test_a_framework_bases_derived_classes_come_after_its_other_neighbours(self):
        # `Trade` has dozens; the tail lists none of them, and in the traversal they follow
        # what the seed references, not the other way round.
        b = Graph()
        b.node("seed", "Trade", "portfolio/trade.hpp", cls=True)
        b.node("other", "Envelope", "portfolio/envelope.hpp")
        b.edge("seed", "other", "references")
        for i in range(channels.DERIVED_MAX + 1):
            b.node(f"c{i}", f"Kind{i}", f"portfolio/k{i}.hpp", cls=True)
            b.edge(f"c{i}", "seed", "inherits")
        found = QueryQuestionTest().answer(b.g, "what is a trade")
        self.assertLess(found.index("Envelope"), found.index("Kind0"))


class DerivedClassesTest(unittest.TestCase):
    def family(self, n):
        b = Graph()
        b.node("base", "Interpolation", "math/interpolation.hpp", cls=True)
        for i in range(n):
            b.node(f"d{i}", f"Kind{i}Interpolation", f"math/k{i}.hpp", cls=True)
            b.edge(f"d{i}", "base", "inherits")
        return b

    def test_the_best_known_implementation_comes_first(self):
        b = self.family(3)
        b.node("user", "Curve", "x.hpp")
        b.edge("user", "d2", "constructs")
        self.assertEqual(channels.derived_classes(b.g, "base")[0], "d2")

    def test_a_framework_base_lists_none(self):
        # `PricingEngine` has hundreds; ten of them would be arbitrary.
        self.assertEqual(channels.derived_classes(self.family(channels.DERIVED_MAX + 1).g, "base"), [])

    def test_only_the_main_subject_gets_them(self):
        b = self.family(3)
        b.node("second", "Trade", "portfolio/trade.hpp", cls=True)
        b.node("kid", "Swap", "portfolio/swap.hpp", cls=True)
        b.edge("kid", "second", "inherits")
        _lead, tail = channels.plan(b.g, "how does interpolation work with a trade", ["base", "second"])
        self.assertIn("d0", tail)
        self.assertNotIn("kid", tail)

    def test_framework_bases_are_not_listed_as_ancestors(self):
        b = Graph()
        b.node("hw", "HullWhite", "models/hullwhite.hpp", cls=True)
        b.node("obs", "Observer", "patterns/observer.hpp", cls=True)
        b.node("model", "ShortRateModel", "models/model.hpp", cls=True)
        b.edge("hw", "obs", "inherits")
        b.edge("hw", "model", "inherits")
        for i in range(channels.DERIVED_MAX + 1):
            b.node(f"o{i}", f"Obs{i}", "x.hpp", cls=True)
            b.edge(f"o{i}", "obs", "inherits")
        self.assertEqual(labels(b.g, channels.ancestors(b.g, "hw")), ["ShortRateModel"])


class PricingChainTest(unittest.TestCase):
    def test_a_quantlib_seed_stands_for_the_ore_trade_of_the_same_name(self):
        b = Graph()
        b.node("ql", "Bond", "instruments/bond.hpp", cls=True)
        b.node("ore", "Bond", "portfolio/bond.hpp", cls=True)
        self.assertEqual(channels.pricing_subjects(b.g, ["ql"]), ["ore"])

    def test_a_registry_builder_leads_to_the_engine_its_header_includes(self):
        b = Graph()
        b.node("t", "Bond", "portfolio/bond.hpp", cls=True)
        b.entry("e", "pricing_engine", "Bond")
        b.node("builder", "BondDiscountingEngineBuilder", "portfolio/builders/bond.hpp", cls=True)
        b.node("engine", "DiscountingRiskyBondEngine",
               "pricingengines/discountingriskybondengine.hpp", cls=True)
        b.edge("e", "t", "maps_to_class")
        b.edge("e", "builder", "maps_to_class")
        b.edge("builder", "engine", "includes")
        self.assertEqual(labels(b.g, channels.builder_engines(b.g, "builder")),
                         ["DiscountingRiskyBondEngine"])

    def test_the_base_builder_beside_a_leaf_builder_is_included(self):
        # The registry names `MidPointCdsEngineBuilder`; the curves are read in its base.
        b = Graph()
        b.node("leaf", "MidPointCdsEngineBuilder", "portfolio/builders/creditdefaultswap.hpp", cls=True)
        b.node("base", "CreditDefaultSwapEngineBuilder", "portfolio/builders/creditdefaultswap.hpp", cls=True)
        b.node("fw", "CachingPricingEngineBuilder", "portfolio/cachingenginebuilder.hpp", cls=True)
        b.edge("leaf", "base", "inherits")
        b.edge("leaf", "fw", "inherits")
        self.assertEqual(labels(b.g, channels.builder_bases(b.g, "leaf")),
                         ["CreditDefaultSwapEngineBuilder"])

    def test_the_plain_builder_comes_before_its_decorated_variants(self):
        b = Graph()
        b.node("t", "Swap", "portfolio/swap.hpp", cls=True)
        b.entry("e", "pricing_engine", "Swap")
        for i, name in enumerate(("CamAmcSwapEngineBuilder", "AmcCgCurrencySwapEngineBuilder",
                                  "SwapEngineBuilder")):
            b.node(f"b{i}", name, "portfolio/builders/swap.hpp", cls=True)
            b.edge("e", f"b{i}", "maps_to_class")
        b.edge("e", "t", "maps_to_class")
        self.assertEqual(labels(b.g, channels.registry_builders(b.g, "t"))[0], "SwapEngineBuilder")


class SchemaCompositionTest(unittest.TestCase):
    def test_what_a_type_is_composed_of_follows_it(self):
        b = Graph()
        b.node("cds", "creditDefaultSwapData (complexType)", "xsd/instruments.xsd", repo="OREXsd")
        b.node("leg", "legData (complexType)", "xsd/instruments.xsd", repo="OREXsd")
        b.edge("cds", "leg", "composed_of")
        lead, tail = channels.plan(b.g, "how does the ORE XSD define a credit default swap trade", [])
        self.assertEqual(labels(b.g, lead), ["creditDefaultSwapData (complexType)"])
        self.assertIn("legData (complexType)", labels(b.g, tail))


class FieldmapNamesTest(unittest.TestCase):
    def test_the_entry_whose_name_is_the_topic_beats_ones_that_contain_it(self):
        b = Graph()
        b.entry("a", "trade", "Interest Rate Swaption", trade_type="Swaption")
        b.entry("b", "trade", "Commodity Swaption", trade_type="CommoditySwaption")
        b.entry("c", "trade", "Forward Starting Swaption", trade_type="ForwardStartingSwaption")
        terms = channels.channel_terms("which pricing engine prices a Swaption")
        found = channels.fieldmap_priority(b.g, terms, {"pricing_engine", "trade"})
        self.assertEqual(labels(b.g, found)[0], "Interest Rate Swaption [trade mapping]")

    def test_a_trade_entry_is_part_of_a_pricing_engine_answer_without_the_word_trade(self):
        b = Graph()
        b.entry("t", "trade", "Interest Rate Swaption", trade_type="Swaption")
        b.entry("p", "pricing_engine", "EuropeanSwaption")
        b.edge("t", "p", "maps_to_pricing_engine")
        terms = channels.channel_terms("which pricing engine is used for swaptions")
        domains = channels.detect_intents(terms).fieldmap
        self.assertIn("trade", domains)
        self.assertIn("Interest Rate Swaption [trade mapping]",
                      labels(b.g, channels.fieldmap_priority(b.g, terms, domains)))

    def test_a_trade_subject_brings_the_builder_that_reads_its_curves(self):
        b = Graph()
        b.entry("t", "trade", "CDS", trade_type="CreditDefaultSwap")
        b.entry("p", "pricing_engine", "CreditDefaultSwap")
        b.node("leaf", "MidPointCdsEngineBuilder", "portfolio/builders/creditdefaultswap.hpp", cls=True)
        b.node("base", "CreditDefaultSwapEngineBuilder", "portfolio/builders/creditdefaultswap.hpp", cls=True)
        b.edge("t", "p", "maps_to_pricing_engine")
        b.edge("p", "leaf", "maps_to_class")
        b.edge("leaf", "base", "inherits")
        terms = channels.channel_terms("which curve config does a credit default swap resolve to")
        found = labels(b.g, channels.fieldmap_priority(
            b.g, terms, channels.detect_intents(terms).fieldmap))
        self.assertIn("CreditDefaultSwapEngineBuilder", found)


class LexicalChannelTest(unittest.TestCase):
    def test_a_label_made_mostly_of_the_questions_words_is_surfaced(self):
        b = Graph()
        b.node("p", "parsePeriod", "utilities/parsers.cpp")
        found = channels.lexical_global(b.g, "what is a Period and how is it parsed")
        self.assertEqual(labels(b.g, found), ["parsePeriod"])

    def test_a_long_label_that_only_mentions_two_of_the_words_is_not(self):
        # `CreditDefaultSwapOption::AuctionSettlementInformation::auctionFinalPrice()` says
        # "swap" and "price" by accident of being long.
        b = Graph()
        b.node("x", "CreditDefaultSwapOption::AuctionSettlementInformation::auctionFinalPrice()", "y.hpp")
        self.assertEqual(channels.lexical_global(b.g, "how is a swap priced"), [])


if __name__ == "__main__":
    unittest.main()
