"""verify's view of the last bench run: weak, fragile and stub-only entries, and
refusing to judge results that no longer describe the suite or the graph."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from oregraph.verify import _bench_results_checks


class BenchResultsChecksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.suite = root / "source_questions.json"
        self.suite.write_text('{"questions": []}', encoding="utf-8")
        self.graph = root / "graph.json"
        self.graph.write_text("{}", encoding="utf-8")
        self.out = root / "bench"
        self.out.mkdir()
        self.cfg = SimpleNamespace(bench_out=self.out, merged_graph=self.graph)
        self.checks = []

    def check(self, name, ok, detail="", severity="error"):
        self.checks.append((name, ok, detail, severity))

    def write_results(self, rows, **meta):
        gstat = self.graph.stat()
        base = {"questions_sha256": hashlib.sha256(self.suite.read_bytes()).hexdigest(),
                "graph_mtime_ns": gstat.st_mtime_ns, "graph_size": gstat.st_size,
                "fragile_margin": 25}
        (self.out / "results.json").write_text(json.dumps({
            "meta": {**base, **meta},
            "vs_source": {"rows": rows, "totals": {"controls_run": 4}}}), encoding="utf-8")

    def run_checks(self):
        _bench_results_checks(self.cfg, self.suite, self.check)
        self.assertEqual(len(self.checks), 1)
        return self.checks[0]

    def test_no_results_yet_is_a_warning_not_a_failure(self):
        name, ok, detail, severity = self.run_checks()
        self.assertEqual((ok, severity), (True, "warn"))
        self.assertIn("run `oregraph bench`", detail)

    def test_clean_results_pass(self):
        self.write_results([{"id": "s01", "weak": {}, "fragile": [], "stub_only": []}])
        _name, ok, detail, _sev = self.run_checks()
        self.assertTrue(ok)
        self.assertIn("4 control queries", detail)

    def test_weak_fragile_and_stub_only_are_each_named(self):
        self.write_results([
            {"id": "s34", "weak": {"Swap@portfolio/swap.hpp": ["what fields for a Bond"]},
             "fragile": ["LegData"], "stub_only": ["IrLgm1fParametrization"]}])
        _name, ok, detail, severity = self.run_checks()
        self.assertFalse(ok)
        self.assertEqual(severity, "warn")
        self.assertIn("1 weak", detail)
        self.assertIn("s34:Swap@portfolio/swap.hpp", detail)
        self.assertIn("1 fragile", detail)
        self.assertIn("within 25 nodes", detail)
        self.assertIn("1 stub-only", detail)

    def test_results_for_another_question_file_are_not_judged(self):
        self.write_results([{"id": "s01", "weak": {"A": ["c"]}}])
        self.suite.write_text('{"questions": [], "changed": true}', encoding="utf-8")
        _name, ok, detail, _sev = self.run_checks()
        self.assertFalse(ok)
        self.assertIn("question file changed", detail)
        self.assertNotIn("weak", detail.replace("weak and fragile", ""))

    def test_results_for_another_graph_are_not_judged(self):
        self.write_results([{"id": "s01", "weak": {"A": ["c"]}}])
        self.graph.write_text('{"nodes": []}', encoding="utf-8")
        _name, ok, detail, _sev = self.run_checks()
        self.assertFalse(ok)
        self.assertIn("graph was rebuilt", detail)

    def test_results_from_before_the_measurement_existed_are_not_judged(self):
        (self.out / "results.json").write_text(json.dumps({
            "meta": {"questions_sha256": hashlib.sha256(self.suite.read_bytes()).hexdigest()},
            "vs_source": {"rows": [], "totals": {}}}), encoding="utf-8")
        _name, ok, detail, _sev = self.run_checks()
        self.assertFalse(ok)
        self.assertIn("predate", detail)


if __name__ == "__main__":
    unittest.main()
