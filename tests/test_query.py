import unittest

import networkx as nx

from oregraph.query import (query_example, query_impact, query_path,
                            query_symbol, resolve_exact)


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


if __name__ == "__main__":
    unittest.main()