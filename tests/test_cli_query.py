"""`oregraph query` must print the answer the MCP server serves.

It printed graphify's half alone (`serve._query_graph_text`) while its docstring, and
docs/QUERIES.md, said it was the same as the server's - so Copilot users, who go through the
CLI because they have no MCP server, never got the docs / tests / schema / fieldmap channels."""
import contextlib
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from oregraph import cli


class QueryCommandTest(unittest.TestCase):
    def run_query(self, **overrides):
        args = SimpleNamespace(question="what tests cover credit default swaps", mode="bfs",
                               depth=9, budget=1500, **overrides)
        cfg = SimpleNamespace(merged_graph=Path(__file__))          # exists
        out = io.StringIO()
        with mock.patch.object(cli, "_cfg", return_value=cfg), \
                mock.patch.object(cli, "_require_graphify"), \
                mock.patch("graphify.serve._load_graph", return_value="GRAPH"), \
                mock.patch("graphify.serve._query_graph_text", return_value="GRAPHIFY ONLY") as base, \
                mock.patch("oregraph.query.query_graph_text", return_value="FUSED") as fused, \
                contextlib.redirect_stdout(out):
            cli.cmd_query(args)
        return out.getvalue().strip(), fused, base

    def test_it_prints_the_fused_answer_not_graphifys_alone(self):
        text, fused, base = self.run_query()
        self.assertEqual(text, "FUSED")
        base.assert_not_called()

    def test_the_question_mode_and_budget_reach_it_and_depth_is_capped_at_six(self):
        _text, fused, _base = self.run_query()
        fused.assert_called_once_with("GRAPH", "what tests cover credit default swaps",
                                      mode="bfs", depth=6, token_budget=1500)


if __name__ == "__main__":
    unittest.main()
