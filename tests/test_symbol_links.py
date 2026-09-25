import tempfile
import unittest
from pathlib import Path

from oregraph.symbol_links import link_inheritance, link_symbols


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


class InheritanceLinksTest(unittest.TestCase):
    """`class Actual360 : public DayCounter` is seen in one header; the base is a stub
    the extractor wrote there. Resolving it gives the defining class its derived ones."""

    @staticmethod
    def cls(node_id, label, source):
        return {"id": node_id, "label": label, "source_file": source, "_callable_class": True}

    @staticmethod
    def stub(node_id, label):
        return {"id": node_id, "label": label, "source_file": ""}

    @staticmethod
    def inherits(source, target):
        return {"source": source, "target": target, "relation": "inherits",
                "confidence": "EXTRACTED", "source_file": "x.hpp", "source_location": "L9"}

    def link(self, nodes, links):
        return link_inheritance(nodes, links)

    def test_a_stub_base_is_pointed_at_the_class_in_the_file_named_after_it(self):
        nodes = [self.cls("dc", "DayCounter", "time/daycounter.hpp"),
                 self.cls("dc_user", "DayCounter", "experimental/callablebond.hpp"),
                 self.cls("a360", "Actual360", "time/daycounters/actual360.hpp"),
                 self.stub("dc_stub", "DayCounter")]
        edges, stats = self.link(nodes, [self.inherits("a360", "dc_stub")])
        self.assertEqual([(e["source"], e["target"]) for e in edges], [("a360", "dc")])
        self.assertEqual(stats["definer"], 1)
        self.assertEqual(edges[0]["relation"], "inherits")
        self.assertEqual(edges[0]["confidence"], "INFERRED")

    def test_the_only_class_of_that_name_is_the_base_even_when_not_in_a_file_named_for_it(self):
        nodes = [self.cls("m", "Model", "models/basemodels.hpp"),
                 self.cls("d", "Derived", "d.hpp"), self.stub("s", "Model")]
        edges, stats = self.link(nodes, [self.inherits("d", "s")])
        self.assertEqual([(e["source"], e["target"]) for e in edges], [("d", "m")])
        self.assertEqual(stats["unique"], 1)

    def test_a_name_two_modules_define_is_left_alone(self):
        # `Bond` is a QuantLib instrument and an ORE trade: a wrong base is worse than none.
        nodes = [self.cls("b1", "Bond", "instruments/bond.hpp"), self.cls("b2", "Bond", "portfolio/bond.hpp"),
                 self.cls("d", "Derived", "d.hpp"), self.stub("s", "Bond")]
        edges, stats = self.link(nodes, [self.inherits("d", "s")])
        self.assertEqual(edges, [])
        self.assertEqual(stats["definer"] + stats["unique"], 0)

    def test_a_name_nobody_defines_is_left_alone(self):
        nodes = [self.cls("d", "Derived", "d.hpp"), self.stub("s", "Impl")]
        edges, stats = self.link(nodes, [self.inherits("d", "s")])
        self.assertEqual(edges, [])
        self.assertEqual(stats["unknown"], 1)

    def test_an_edge_that_already_reaches_a_class_is_not_touched_or_repeated(self):
        nodes = [self.cls("dc", "DayCounter", "time/daycounter.hpp"),
                 self.cls("a360", "Actual360", "a.hpp"), self.stub("s", "DayCounter")]
        links = [self.inherits("a360", "dc"), self.inherits("a360", "s")]
        edges, _stats = self.link(nodes, links)
        self.assertEqual(edges, [])

    def test_the_stub_edge_is_kept_and_a_class_is_never_its_own_base(self):
        nodes = [self.cls("x", "Foo", "foo.hpp"), self.stub("s", "Foo")]
        edges, _stats = self.link(nodes, [self.inherits("x", "s")])
        self.assertEqual(edges, [])            # x would inherit itself


if __name__ == "__main__":
    unittest.main()
