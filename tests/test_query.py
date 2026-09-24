import unittest

import networkx as nx

from oregraph.query import (query_example, query_flow, query_impact, query_path,
                            query_symbol, resolve_exact, resolve_question)


class QueryPathTest(unittest.TestCase):
    def test_qualified_member_resolves_header_and_source(self):
        graph = nx.DiGraph()
        graph.add_node("class", label="Trade", repo_path="src/trade.hpp")
        graph.add_node("declaration", label="build", repo_path="src/trade.hpp")
        graph.add_node("implementation", label="build", repo_path="src/trade.cpp")
        graph.add_node("target", label="Engine", repo_path="src/engine.hpp")
        graph.add_edge("implementation", "target", relation="constructs",
                       confidence="RESOLVED")

        self.assertEqual(
            resolve_exact(graph, "Trade::build"),
            ["declaration", "implementation"])
        output = query_path(graph, ["Trade::build", "Engine"])
        self.assertIn("--constructs [RESOLVED]-->", output)

    def test_parallel_semantic_relation_is_not_collapsed(self):
        graph = nx.MultiGraph()
        graph.add_node("trade", label="Trade")
        graph.add_node("engine", label="Engine")
        graph.add_edge("trade", "engine", relation="includes")
        graph.add_edge("trade", "engine", relation="constructs",
                       confidence="RESOLVED")

        output = query_path(graph, ["Trade", "Engine"])

        self.assertIn("--constructs [RESOLVED]-->", output)
        self.assertIn("--constructs [RESOLVED]-->", query_symbol(graph, "Trade"))

    def test_impact_separates_incoming_and_outgoing(self):
        graph = nx.MultiDiGraph()
        graph.add_node("caller", label="Caller", repo_path="caller.cpp")
        graph.add_node("subject", label="Subject", repo_path="subject.hpp")
        graph.add_node("target", label="Target", repo_path="target.hpp")
        graph.add_edge("caller", "subject", relation="calls")
        graph.add_edge("subject", "target", relation="uses")
        graph.add_edge("subject", "target", relation="includes")

        output = query_impact(graph, "Subject")

        self.assertIn("IN <--calls-- Caller", output)
        self.assertIn("OUT --uses--> Target", output)
        self.assertNotIn("includes", output)

    def test_example_bundle_categorizes_and_reports_gaps(self):
        graph = nx.MultiDiGraph()
        graph.add_node("trade", label="Trade",
                       repo_path="OREData/ored/portfolio/trade.hpp")
        graph.add_node("builder", label="TradeEngineBuilder",
                       repo_path="OREData/ored/portfolio/builders/trade.hpp")
        graph.add_edge("trade", "builder", relation="uses")

        output = query_example(graph, "Trade")

        self.assertIn("TRADE/DATA:", output)
        self.assertIn("BUILDER:", output)
        self.assertIn("OREData/ored/portfolio/builders/trade.hpp", output)
        self.assertIn("SCHEMA:\n  MISSING FROM CONNECTED GRAPH CONTEXT", output)

    def test_flow_discovers_endpoint_without_target_name(self):
        graph = nx.MultiDiGraph()
        graph.add_node("trade", label="ConvertibleBond",
                       repo_path="OREData/ored/portfolio/convertiblebond.hpp")
        graph.add_node("build", label="build",
                       repo_path="OREData/ored/portfolio/convertiblebond.hpp")
        graph.add_node("builder", label="ConvertibleBondEngineBuilder",
                       repo_path="OREData/ored/portfolio/builders/convertiblebond.hpp")
        graph.add_node("engine", label="FdConvertibleBondEngine",
                       repo_path="QuantExt/qle/pricingengines/fdconvertiblebondengine.hpp")
        graph.add_node("calculate", label="calculate",
                   repo_path="QuantExt/qle/pricingengines/fdconvertiblebondengine.cpp")
        graph.add_edge("build", "builder", relation="uses", confidence="RESOLVED")
        graph.add_edge("builder", "engine", relation="constructs", confidence="RESOLVED")
        graph.add_edge("builder", "calculate", relation="calls", confidence="RESOLVED")

        output = query_flow(graph, "ConvertibleBond")

        self.assertIn("Implementation flow from: ConvertibleBond::build", output)
        self.assertIn("PRICING ENGINES:", output)
        self.assertIn("FdConvertibleBondEngine", output)
        self.assertIn("--constructs [RESOLVED]-->", output)
        self.assertNotIn("calculate", output)

    @staticmethod
    def _builder_graph(builder_path, link_relation="defines"):
        """build --uses--> Builder --link--> engineImpl --constructs--> Engine."""
        graph = nx.MultiDiGraph()
        graph.add_node("trade", label="ConvertibleBond",
                       repo_path="OREData/ored/portfolio/convertiblebond.hpp")
        graph.add_node("build", label="build",
                       repo_path="OREData/ored/portfolio/convertiblebond.hpp")
        graph.add_node("builder", label="ConvertibleBondEngineBuilder",
                       repo_path=builder_path)
        graph.add_node("impl", label="engineImpl", repo_path=builder_path)
        graph.add_node("engine", label="FdConvertibleBondEngine",
                       repo_path="QuantExt/qle/pricingengines/fdconvertiblebondengine.hpp")
        graph.add_edge("build", "builder", relation="uses", confidence="RESOLVED")
        graph.add_edge("builder", "impl", relation=link_relation, confidence="EXTRACTED")
        graph.add_edge("impl", "engine", relation="constructs", confidence="RESOLVED")
        return graph

    def test_flow_crosses_defines_between_a_builder_and_its_engine_impl(self):
        # graphify 0.9.51+ links the two with `defines`; earlier versions used
        # `references`, which the flow followed. Losing this step is what made
        # `verify` stop discovering the convertible FD engine after the upgrade.
        for relation in ("defines", "references"):
            with self.subTest(relation=relation):
                output = query_flow(self._builder_graph(
                    "OREData/ored/portfolio/builders/convertiblebond.hpp", relation),
                    "ConvertibleBond")
                self.assertIn("FdConvertibleBondEngine", output)

    def test_flow_does_not_follow_defines_outside_builders(self):
        output = query_flow(self._builder_graph(
            "OREData/ored/portfolio/convertiblebond.hpp"), "ConvertibleBond")
        self.assertNotIn("FdConvertibleBondEngine", output)

    def test_flow_never_reports_a_member_reached_through_defines(self):
        graph = self._builder_graph(
            "OREData/ored/portfolio/builders/convertiblebond.hpp")
        graph.add_node("member", label="engine",
                       repo_path="OREData/ored/portfolio/builders/convertiblebond.hpp")
        graph.add_edge("builder", "member", relation="defines", confidence="EXTRACTED")

        output = query_flow(graph, "ConvertibleBond")

        self.assertIn("FdConvertibleBondEngine", output)
        self.assertNotIn("--> engine [src=", output)   # the member; engineImpl is fine

    def test_seed_prefers_the_connected_definition_over_a_same_label_declaration(self):
        # Same label, same score: the forward declaration's id sorts first, but
        # the class that has the relations is the one the question is about.
        graph = nx.MultiDiGraph()
        graph.add_node("a_decl", label="AmcCalculator", _callable_class=True,
                       source_file="engine/amcvaluationengine.cpp")
        graph.add_node("z_real", label="AmcCalculator", _callable_class=True,
                       source_file="pricingengines/amccalculator.hpp")
        for other in ("m1", "m2", "m3"):
            graph.add_node(other, label=other)
            graph.add_edge("z_real", other, relation="defines")
        graph.add_node("only", label="only")
        graph.add_edge("a_decl", "only", relation="references")

        self.assertEqual(resolve_question(graph, "how does the amc calculator work")[0],
                         "z_real")


if __name__ == "__main__":
    unittest.main()