import tempfile
import unittest
from pathlib import Path

from oregraph.symbol_links import link_symbols


class SymbolLinksTest(unittest.TestCase):
    def test_construction_requires_matching_include(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory)
            source = engine / "OREData" / "trade.cpp"
            header = engine / "OREData" / "trade.hpp"
            target = engine / "QuantExt" / "qle" / "target.hpp"
            unrelated = engine / "Other" / "unrelated.hpp"
            for path in (source, header, target, unrelated):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            source.write_text(
                "#include <qle/target.hpp>\n"
                "void Trade::build() { auto x = make_shared<Target>(); "
                "auto z = dynamic_pointer_cast<Target>(x); "
                "auto y = make_shared<Unrelated>(); }\n",
                encoding="utf-8")
            nodes = [
                {"id": "source", "label": "trade.cpp",
                 "repo_path": "OREData/trade.cpp"},
                {"id": "build", "label": "build",
                 "repo_path": "OREData/trade.hpp"},
                {"id": "target", "label": "Target",
                 "repo_path": "QuantExt/qle/target.hpp"},
                {"id": "unrelated", "label": "Unrelated",
                 "repo_path": "Other/unrelated.hpp"},
            ]

            edges, stats = link_symbols(engine, nodes)

        self.assertEqual(stats["by_relation"], {"constructs": 1, "uses": 1})
        self.assertEqual({edge["source"] for edge in edges}, {"build"})
        self.assertEqual({edge["target"] for edge in edges}, {"target"})
        self.assertEqual({edge["confidence"] for edge in edges}, {"RESOLVED"})


if __name__ == "__main__":
    unittest.main()