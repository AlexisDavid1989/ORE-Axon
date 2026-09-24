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

    def _link_header(self, header_text, nodes):
        """(source, target) pairs from one header, with `Engine` as the target."""
        with tempfile.TemporaryDirectory() as directory:
            engine = Path(directory)
            header = engine / "OREData" / "builder.hpp"
            target = engine / "QuantExt" / "qle" / "engine.hpp"
            for path in (header, target):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            header.write_text("#include <qle/engine.hpp>\n" + header_text,
                              encoding="utf-8")
            all_nodes = nodes + [
                {"id": "engine", "label": "Engine",
                 "repo_path": "QuantExt/qle/engine.hpp"}]
            edges, _stats = link_symbols(engine, all_nodes)
        return {(edge["source"], edge["target"]) for edge in edges}

    @staticmethod
    def _class(node_id, label, line):
        return {"id": node_id, "label": label, "_callable_class": True,
                "repo_path": "OREData/builder.hpp", "source_location": f"L{line}"}

    def test_inline_construct_belongs_to_enclosing_class_not_a_nested_type(self):
        # The nested `Curves` has the shorter id. Header-inline code has no
        # `Class::method` span, so this used to fall back to the shortest id in
        # the file and attribute the construction to `Curves`.
        edges = self._link_header(
            "class Builder {\n"
            "  struct Curves { int a_; };\n"
            "  void engineImpl() { auto e = make_shared<Engine>(); }\n"
            "};\n",
            [self._class("c", "Curves", 3), self._class("builder_class", "Builder", 2)])
        self.assertEqual(edges, {("builder_class", "engine")})

    def test_construct_inside_the_nested_types_own_method_stays_with_it(self):
        edges = self._link_header(
            "class Builder {\n"
            "  struct Curves { void make() { auto e = make_shared<Engine>(); } };\n"
            "};\n",
            [self._class("c", "Curves", 3), self._class("builder_class", "Builder", 2)])
        self.assertEqual(edges, {("c", "engine")})

    def test_enum_class_and_forward_declaration_are_not_scopes(self):
        edges = self._link_header(
            "class Fwd;\n"
            "enum class Kind { A, B };\n"
            "class Builder {\n"
            "  void engineImpl() { auto e = make_shared<Engine>(); }\n"
            "};\n",
            [self._class("k", "Kind", 3), self._class("builder_class", "Builder", 4)])
        self.assertEqual(edges, {("builder_class", "engine")})


if __name__ == "__main__":
    unittest.main()
