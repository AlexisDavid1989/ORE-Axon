import tempfile
import unittest
from pathlib import Path

from oregraph.chunks import Chunk
from oregraph.link_schema import (_defines_class, _resolve_code_node,
                                  _root_class_declarations, link_schema)

OREDATA_ROOT = "OREData/ored"
OREANALYTICS_ROOT = "OREAnalytics/orea"


def write(base: Path, rel: str, text: str) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def xsd_element_node(node_id: str, element_name: str) -> dict:
    """A node shaped the way the real OREXsd extraction labels a root
    element's own node - "<Name> (element)" - which is what Tier 4 looks up
    by (the element's own name, not its declared type's name)."""
    return {"id": f"OREXsd::{node_id}", "label": f"{element_name} (element)", "repo": "OREXsd",
            "source_file": "xsd/ore.xsd"}


class DefinesClassTest(unittest.TestCase):
    def test_a_real_definition_matches(self):
        self.assertTrue(_defines_class("class StressTestScenarioData : public XMLSerializable {",
                                       "StressTestScenarioData"))
        self.assertTrue(_defines_class("struct Foo final {", "Foo"))

    def test_a_forward_declaration_does_not_match(self):
        self.assertFalse(_defines_class("class StressTestScenarioData;", "StressTestScenarioData"))

    def test_a_bare_mention_does_not_match(self):
        text = "void setStressScenarioData(shared_ptr<StressTestScenarioData>& x);"
        self.assertFalse(_defines_class(text, "StressTestScenarioData"))

    def test_a_different_class_with_the_name_as_a_substring_does_not_match(self):
        self.assertFalse(_defines_class("class OtherStressTestScenarioData {", "StressTestScenarioData"))


class ResolveCodeNodeTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def node(self, label, repo_path, repo="OREData"):
        return {"id": f"{repo}::{repo_path}", "label": label, "repo": repo,
                "source_file": repo_path.split("/", 1)[-1], "repo_path": repo_path}

    def test_forward_declaration_is_not_preferred_over_nothing(self):
        # Reproduces the real bug: OREAnalytics' app/inputparameters.hpp forward-
        # declares a class its own file (scenario/stressscenariodata.hpp) defines.
        write(self.engine, f"{OREANALYTICS_ROOT}/app/inputparameters.hpp",
              "class StressTestScenarioData;\n")
        write(self.engine, f"{OREANALYTICS_ROOT}/scenario/stressscenariodata.hpp",
              "class StressTestScenarioData : public XMLSerializable {\npublic:\nvoid fromXML();\n};\n")
        by_label = {"StressTestScenarioData": [
            self.node("StressTestScenarioData", f"{OREANALYTICS_ROOT}/app/inputparameters.hpp",
                     "OREAnalytics"),
            self.node("StressTestScenarioData", f"{OREANALYTICS_ROOT}/scenario/stressscenariodata.hpp",
                     "OREAnalytics"),
        ]}
        node = _resolve_code_node(self.engine, "StressTestScenarioData", by_label)
        self.assertIsNotNone(node)
        self.assertEqual(node["repo_path"], f"{OREANALYTICS_ROOT}/scenario/stressscenariodata.hpp")

    def test_two_real_definitions_stay_unresolved(self):
        write(self.engine, "a.hpp", "class Dup {\n};\n")
        write(self.engine, "b.hpp", "class Dup {\n};\n")
        by_label = {"Dup": [self.node("Dup", "a.hpp"), self.node("Dup", "b.hpp")]}
        self.assertIsNone(_resolve_code_node(self.engine, "Dup", by_label))

    def test_change_is_monotonic_single_candidate_still_short_circuits(self):
        by_label = {"Solo": [self.node("Solo", "solo.hpp")]}
        # No file on disk at all - the forward-decl check must never even run
        # when there is only one candidate, so a missing file can't matter.
        node = _resolve_code_node(self.engine, "Solo", by_label)
        self.assertEqual(node["repo_path"], "solo.hpp")


class RootClassDeclarationsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = Path(self._tmp.name)
        self.chunks_by_name = {
            "OREData": Chunk("OREData", OREDATA_ROOT, (".",)),
            "OREAnalytics": Chunk("OREAnalytics", OREANALYTICS_ROOT, (".",)),
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_finds_checknode_getnodename_and_raw_name_idioms(self):
        write(self.engine, f"{OREDATA_ROOT}/utilities/calendaradjustmentconfig.cpp",
              'void CalendarAdjustmentConfig::fromXML(XMLNode* node) {\n'
              '    XMLUtils::checkNode(node, "CalendarAdjustments");\n}\n')
        write(self.engine, f"{OREDATA_ROOT}/model/crossassetmodeldata.cpp",
              'void CrossAssetModelData::fromXML(XMLNode* root) {\n'
              '    if (XMLUtils::getNodeName(root) == "CrossAssetModel") {}\n}\n')
        write(self.engine, f"{OREDATA_ROOT}/portfolio/portfolio.cpp",
              'void Portfolio::fromXML(XMLNode* node) {\n'
              '    QL_REQUIRE(std::string(node->name()) == "Portfolio", "x");\n}\n')

        decl = _root_class_declarations(self.engine, self.chunks_by_name)

        self.assertEqual(decl["CalendarAdjustments"], {"CalendarAdjustmentConfig"})
        self.assertEqual(decl["CrossAssetModel"], {"CrossAssetModelData"})
        self.assertEqual(decl["Portfolio"], {"Portfolio"})

    def test_a_tag_check_with_no_preceding_fromxml_is_not_attributed_to_anything(self):
        write(self.engine, f"{OREDATA_ROOT}/utilities/orphan.cpp",
              'XMLUtils::checkNode(node, "Orphan");\n')  # no fromXML def in this file at all
        decl = _root_class_declarations(self.engine, self.chunks_by_name)
        self.assertNotIn("Orphan", decl)

    def test_two_classes_validating_the_same_tag_are_both_recorded_not_guessed_between(self):
        write(self.engine, f"{OREDATA_ROOT}/a.cpp",
              'void A::fromXML(XMLNode* node) { XMLUtils::checkNode(node, "Shared"); }\n')
        write(self.engine, f"{OREDATA_ROOT}/b.cpp",
              'void B::fromXML(XMLNode* node) { XMLUtils::checkNode(node, "Shared"); }\n')
        decl = _root_class_declarations(self.engine, self.chunks_by_name)
        self.assertEqual(decl["Shared"], {"A", "B"})

    def test_a_tag_check_is_attributed_to_the_nearest_preceding_fromxml_not_the_first(self):
        write(self.engine, f"{OREDATA_ROOT}/multi.cpp",
              'void First::fromXML(XMLNode* node) { doNothing(); }\n'
              'void Second::fromXML(XMLNode* node) { XMLUtils::checkNode(node, "Tag"); }\n')
        decl = _root_class_declarations(self.engine, self.chunks_by_name)
        self.assertEqual(decl["Tag"], {"Second"})


class LinkSchemaTier4Test(unittest.TestCase):
    """End-to-end: link_schema() actually produces a Tier 4 edge for a root
    element whose tag has no name resemblance at all to its implementing
    class - the case Tiers 1-3 structurally cannot find."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = Path(self._tmp.name)
        write(self.engine, "xsd/ore.xsd",
              '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">\n'
              '<xs:element name="ORE" type="ore"/>\n'
              '<xs:complexType name="ore"><xs:sequence/></xs:complexType>\n'
              '</xs:schema>\n')
        write(self.engine, f"{OREANALYTICS_ROOT}/app/parameters.cpp",
              'void Parameters::fromXML(XMLNode* node) {\n'
              '    XMLUtils::checkNode(node, "ORE");\n}\n')
        write(self.engine, f"{OREDATA_ROOT}/portfolio/databuilders.hpp", "")
        write(self.engine, f"{OREDATA_ROOT}/utilities/databuilders.cpp", "")
        write(self.engine, f"{OREDATA_ROOT}/configuration/conventions.cpp", "")

        self.chunks = [
            Chunk("OREData", OREDATA_ROOT, (".",)),
            Chunk("OREAnalytics", OREANALYTICS_ROOT, (".",)),
            Chunk("OREXsd", "xsd", (".",), kind="semantic"),
        ]
        self.graphs = {
            "OREData": {"nodes": [], "links": []},
            "OREAnalytics": {"nodes": [
                {"id": "parameters", "label": "Parameters", "repo": "OREAnalytics",
                 "source_file": "app/parameters.hpp", "repo_path": f"{OREANALYTICS_ROOT}/app/parameters.hpp",
                 "_callable_class": True},
            ], "links": []},
            "OREXsd": {"nodes": [xsd_element_node("xsd_ore_ore", "ORE")], "links": []},
        }

    def tearDown(self):
        self._tmp.cleanup()

    def test_root_tag_resolves_to_an_unrelated_class_name(self):
        edges, stats = link_schema(self.engine, self.chunks,
                                   {k: dict(v) for k, v in self.graphs.items()},
                                   {c.name: c.root for c in self.chunks})
        tier4 = [e for e in edges if e.get("_tier") == 4]
        self.assertEqual(len(tier4), 1)
        # SCHEMA_FOR direction is xsd -> class.
        self.assertEqual(tier4[0]["source"], "OREXsd::xsd_ore_ore")
        self.assertEqual(tier4[0]["target"], "parameters")
        self.assertEqual(tier4[0]["confidence"], "EXTRACTED")
        self.assertEqual(stats["tier_counts"]["4"], 1)


if __name__ == "__main__":
    unittest.main()
