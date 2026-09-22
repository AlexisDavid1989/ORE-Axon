import copy
import tempfile
import unittest
from pathlib import Path

import networkx as nx

from oregraph import fieldmap, fieldmap_link, query
from oregraph.fieldmap import FieldmapError, FieldmapSnapshot
from oregraph.fieldmap_link import FIELDMAP_REPO, link_fieldmap
from oregraph.verify import _fieldmap_checks

DATABUILDERS = '''
ORE_REGISTER_TRADE_BUILDER("FxForward", FxForward, false)
ORE_REGISTER_TRADE_BUILDER("Swaption", Swaption, false)
'''
CONVENTIONS_CPP = '''
if (type == "Deposit") { convention = QuantLib::ext::make_shared<DepositConvention>(); }
'''
INSTRUMENTS_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:group name="oreTradeData"><xs:choice>
<xs:element type="fxForwardData" name="FxForwardData"/>
</xs:choice></xs:group>
<xs:complexType name="fxForwardData"><xs:sequence/></xs:complexType>
</xs:schema>'''
CONVENTIONS_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:complexType name="conventions"><xs:choice>
<xs:element type="depositType" name="Deposit"/>
</xs:choice></xs:complexType>
</xs:schema>'''
CURVECONFIG_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:element name="YieldCurve" type="yieldCurve"/>
<xs:complexType name="yieldCurve"><xs:all>
<xs:element name="Segments" type="segmentsType"/>
</xs:all></xs:complexType>
<xs:complexType name="segmentsType"><xs:sequence/></xs:complexType>
<xs:element name="InflationCurve" type="inflationCurve"/>
<xs:complexType name="inflationCurve"><xs:all>
<xs:element name="Segments" type="inflSegmentsType"/>
</xs:all></xs:complexType>
<xs:complexType name="inflSegmentsType"><xs:sequence/></xs:complexType>
<xs:element name="DefaultCurve" type="xs:string"/>
<xs:element name="DefaultCurve" type="defaultCurve"/>
<xs:element name="Configurations"><xs:complexType><xs:sequence/></xs:complexType></xs:element>
</xs:schema>'''
PRICING_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:element type="product" name="Product"/>
</xs:schema>'''


def code(label, repo="OREData", source="portfolio/x.hpp", **extra):
    return {"id": f"{repo}::{source.replace('/', '_')}_{label}", "label": label,
            "repo": repo, "_callable_class": True, "source_file": source,
            "repo_path": f"{repo}/ored/{source}", **extra}


def xsd_node(node_id, label, source_file):
    return {"id": f"OREXsd::{node_id}", "label": label, "repo": "OREXsd",
            "source_file": source_file}


def entry(meta, nodes=None, combinations=None):
    record = {"meta": meta}
    if combinations is not None:
        record["combinations"] = combinations
    else:
        record["nodes"] = nodes or []
    return record


def field(xpath, optional=False, **extra):
    return {"xpath": xpath, "tag": xpath.rsplit("/", 1)[-1], "is_field": True,
            "is_optional": optional, **extra}


class FieldmapLinkTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = Path(self._tmp.name)
        for rel, text in {
            "OREData/ored/utilities/databuilders.cpp": DATABUILDERS,
            "OREData/ored/configuration/conventions.cpp": CONVENTIONS_CPP,
            "OREData/ored/configuration/yieldcurveconfig.cpp":
                'void YieldCurveConfig::fromXML(XMLNode* n) { XMLUtils::checkNode(n, "YieldCurve"); }',
            "OREData/ored/configuration/conventions.hpp": "// Deposit",
            "xsd/instruments.xsd": INSTRUMENTS_XSD,
            "xsd/conventions.xsd": CONVENTIONS_XSD,
            "xsd/curveconfig.xsd": CURVECONFIG_XSD,
            "xsd/pricingengines.xsd": PRICING_XSD,
        }.items():
            path = self.engine / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

        self.fx = code("FxForward", source="portfolio/fxforward.hpp")
        self.nodes = [
            self.fx,
            # Other repos carry a node for the same label: the instrument in
            # QuantExt, a mere mention in OREAnalytics. Neither may win.
            code("FxForward", repo="QuantExt", source="instruments/fxforward.hpp"),
            code("DepositConvention", source="configuration/conventions.hpp"),
            code("Swaption", source="portfolio/swaption.hpp"),
            code("YieldCurveConfig", source="configuration/yieldcurveconfig.hpp"),
            code("YieldCurveConfig", repo="OREAnalytics", source="app/inputparameters.hpp"),
            code("PriceSegment", source="configuration/commoditycurveconfig.hpp"),
            code("SwaptionEngineBuilder", source="portfolio/builders/swaption.hpp"),
            code("HandWrittenBuilder", source="portfolio/builders/swaption.hpp"),
            xsd_node("xsd_instruments_fx_forward_data", "fxForwardData (complexType)",
                     "xsd/instruments.xsd"),
            xsd_node("xsd_instruments_schema", "Instruments Schema (instruments.xsd)",
                     "xsd/instruments.xsd"),
            xsd_node("xsd_conventions_schema", "Conventions Schema (conventions.xsd)",
                     "xsd/conventions.xsd"),
            xsd_node("xsd_curveconfig_schema", "Curve Configuration Schema (curveconfig.xsd)",
                     "xsd/curveconfig.xsd"),
            xsd_node("xsd_pricingengines_product", "product (complexType)",
                     "xsd/pricingengines.xsd"),
            xsd_node("xsd_pricingengines_schema", "Pricing Engines Schema (pricingengines.xsd)",
                     "xsd/pricingengines.xsd"),
        ]
        registrar = {"id": "OREData::databuilders", "label": "dataBuilders()", "repo": "OREData"}
        self.nodes.append(registrar)
        self.links = [{"source": registrar["id"],
                       "target": next(n["id"] for n in self.nodes
                                      if n["label"] == "SwaptionEngineBuilder"),
                       "relation": "registers", "context": "ore_engine_registration"}]

    def tearDown(self):
        self._tmp.cleanup()

    def snapshot(self, **domains):
        return FieldmapSnapshot(source="/forge", version={"commit": "abc123", "dirty": False},
                                domains={d: domains.get(d, {}) for d in fieldmap.DOMAINS})

    def run_link(self, **domains):
        return link_fieldmap(self.snapshot(**domains), self.nodes, self.links,
                             self.engine, community_base=5_000_000)

    def edges_from(self, edges, entry_id, relation):
        return [e for e in edges if e["source"] == entry_id and e["relation"] == relation]

    # ---- trades: linked from source, fields carried, nothing guessed ---------

    def test_trade_links_to_home_repo_class_and_schema_type(self):
        trade = entry({"XML_Node_Name": "FxForwardData", "Trade_Type": "FxForward",
                       "Asset_Class": "FX"},
                      [field("Trade/FxForwardData/BoughtCurrency", value_set="Currency"),
                       field("Trade/FxForwardData/Settlement", optional=True),
                       {"xpath": "Trade/FxForwardData", "is_field": False}])
        nodes, edges, stats = self.run_link(trade={"FX Forward": trade})

        (entry_node,) = nodes
        self.assertEqual(entry_node["id"], f"{FIELDMAP_REPO}::trade/FX Forward")
        self.assertEqual(entry_node["label"], "FX Forward [trade mapping]")
        (cls,) = self.edges_from(edges, entry_node["id"], "maps_to_class")
        self.assertEqual(cls["target"], self.fx["id"])          # OREData, not QuantExt
        self.assertEqual((cls["confidence"], cls["context"]),
                         ("EXTRACTED", "fieldmap_trade_registry"))
        (schema,) = self.edges_from(edges, entry_node["id"], "maps_to_schema")
        self.assertEqual(schema["target"], "OREXsd::xsd_instruments_fx_forward_data")
        self.assertEqual((schema["anchor"], schema["xsd_type"]), ("type", "fxForwardData"))
        self.assertEqual(stats["domains"]["trade"]["class_linked"], 1)

    def test_fields_are_attributes_of_the_entry_not_nodes(self):
        trade = entry({"XML_Node_Name": "FxForwardData", "Trade_Type": "FxForward"},
                      [field("Trade/FxForwardData/BoughtCurrency", data_type="String",
                             value_set="Currency"),
                       field("Trade/FxForwardData/Settlement", optional=True),
                       {"xpath": "Trade/FxForwardData", "is_field": False}])
        nodes, edges, stats = self.run_link(trade={"FX Forward": trade})

        self.assertEqual(len(nodes), 1)                          # containers and fields: no nodes
        self.assertEqual({e["relation"] for e in edges} - {"maps_to_class", "maps_to_schema"},
                         set())
        self.assertEqual(nodes[0]["field_count"], 2)             # the container is not a field
        self.assertEqual(nodes[0]["required_count"], 1)
        self.assertEqual(nodes[0]["fields"][0],
                         {"xpath": "Trade/FxForwardData/BoughtCurrency", "optional": False,
                          "data_type": "String", "value_set": "Currency"})
        self.assertEqual(stats["domains"]["trade"]["fields"], 2)

    def test_unknown_trade_type_is_reported_never_guessed(self):
        trade = entry({"XML_Node_Name": "MysteryData", "Trade_Type": "Mystery"})
        nodes, edges, stats = self.run_link(trade={"Mystery": trade})

        self.assertEqual(edges, [])
        self.assertIn("Mystery: Trade_Type 'Mystery' is not in TradeFactory's registry",
                      stats["unresolved_class"]["trade"])
        self.assertEqual(stats["unresolved_schema"]["trade"], ["Mystery: MysteryData"])

    def test_source_wins_over_forge_when_they_disagree(self):
        # ORE_Forge names a class conventions.cpp does not dispatch "Deposit" to.
        convention = entry({"XML_Node_Name": "Deposit", "Cpp_Class_Name": "WrongConvention"})
        nodes, edges, stats = self.run_link(convention={"Deposit": convention})

        (cls,) = self.edges_from(edges, nodes[0]["id"], "maps_to_class")
        self.assertEqual(cls["target"],
                         next(n["id"] for n in self.nodes if n["label"] == "DepositConvention"))
        self.assertEqual(cls["context"], "fieldmap_convention_dispatch")
        self.assertEqual(len(stats["class_disagreements"]), 1)
        self.assertIn("WrongConvention", stats["class_disagreements"][0])

    # ---- claims: corroborated by the class's own source, or left INFERRED ----

    def test_claim_is_extracted_only_when_the_class_source_names_the_tag(self):
        supported = entry({"XML_Node_Name": "YieldCurve", "Cpp_Class_Name": "YieldCurveConfig"})
        unsupported = entry({"XML_Node_Name": "NeverMentioned", "Cpp_Class_Name": "YieldCurveConfig"})
        nodes, edges, stats = self.run_link(
            curve_config={"YieldCurve": supported, "Other": unsupported})

        by_entry = {n["entry"]: n["id"] for n in nodes}
        (good,) = self.edges_from(edges, by_entry["YieldCurve"], "maps_to_class")
        (weak,) = self.edges_from(edges, by_entry["Other"], "maps_to_class")
        self.assertEqual((good["confidence"], good["context"]),
                         ("EXTRACTED", "fieldmap_class_source"))
        self.assertEqual((weak["confidence"], weak["context"]), ("INFERRED", "fieldmap_claim"))
        self.assertTrue(any("NeverMentioned" in s for s in stats["unsupported_claims"]))
        # The OREAnalytics stub for the same class must not make it ambiguous.
        self.assertEqual(good["target"], weak["target"])

    def test_forward_declaration_does_not_make_a_real_definition_ambiguous(self):
        # Two OREData candidates (home-repo bias can't disambiguate) for the same
        # label, neither file-stem-named after the class: one is a real
        # definition, the other only forward-declares it - the real bug found
        # in OREAnalytics' app/inputparameters.hpp, reproduced with two OREData
        # files so home-repo preference is deliberately not what resolves this.
        aggregator = self.engine / "OREData/ored/portfolio/aggregator.hpp"
        aggregator.parent.mkdir(parents=True, exist_ok=True)
        aggregator.write_text("class ScatteredThing;\n", encoding="utf-8")
        (self.engine / "OREData/ored/portfolio/scattered.hpp").write_text(
            "class ScatteredThing : public XMLSerializable {\n"
            "    void fromXML(XMLNode* n) { XMLUtils::checkNode(n, \"Scattered\"); }\n"
            "};\n", encoding="utf-8")
        self.nodes.append(code("ScatteredThing", source="portfolio/aggregator.hpp"))
        self.nodes.append(code("ScatteredThing", source="portfolio/scattered.hpp"))

        curve_config = entry({"XML_Node_Name": "Scattered", "Cpp_Class_Name": "ScatteredThing"})
        nodes, edges, stats = self.run_link(curve_config={"Scattered": curve_config})

        self.assertEqual(stats["unresolved_class"], {})
        (cls,) = self.edges_from(edges, nodes[0]["id"], "maps_to_class")
        self.assertEqual(cls["source_file"], "portfolio/scattered.hpp")  # the real definition
        # Also corroborated by the tag, since the real definition is the one found.
        self.assertEqual(cls["confidence"], "EXTRACTED")

    def test_nested_class_links_to_its_enclosing_class_as_inferred(self):
        nested = entry({"XML_Node_Name": "OffPeakDaily",
                        "Cpp_Class_Name": "PriceSegment::OffPeakDaily"})
        nodes, edges, _ = self.run_link(curve_config={"OffPeakDaily": nested})

        (cls,) = self.edges_from(edges, nodes[0]["id"], "maps_to_class")
        self.assertEqual(cls["target"],
                         next(n["id"] for n in self.nodes if n["label"] == "PriceSegment"))
        self.assertEqual((cls["confidence"], cls["context"]),
                         ("INFERRED", "fieldmap_claim_nested_outer"))

    # ---- schema anchoring -----------------------------------------------------

    def test_builtin_typed_leaf_does_not_make_a_real_type_ambiguous(self):
        # `DefaultCurve` is a string leaf in one place and a complex type in another.
        nodes, edges, stats = self.run_link(
            curve_config={"DefaultCurve": entry({"XML_Node_Name": "DefaultCurve"})})
        self.assertEqual(stats["unresolved_schema"], {})
        (schema,) = self.edges_from(edges, nodes[0]["id"], "maps_to_schema")
        self.assertEqual(schema["xsd_type"], "defaultCurve")

    def test_anonymous_root_element_anchors_at_the_schema_file(self):
        nodes, edges, _ = self.run_link(
            curve_config={"Configurations": entry({"XML_Node_Name": "Configurations"})})
        (schema,) = self.edges_from(edges, nodes[0]["id"], "maps_to_schema")
        self.assertEqual(schema["anchor"], "file")
        self.assertEqual(schema["target"], "OREXsd::xsd_curveconfig_schema")
        self.assertNotIn("xsd_type", schema)

    def test_parent_node_narrows_an_ambiguous_element_name(self):
        # curveconfig.xsd declares "Segments" twice, once under YieldCurve and
        # once under InflationCurve, each with its own type - unresolvable by
        # name alone. ORE_Forge's own Parent_Node picks the right one.
        yc_segments = entry({"XML_Node_Name": "Segments", "Parent_Node": "YieldCurve"})
        infl_segments = entry({"XML_Node_Name": "Segments", "Parent_Node": "InflationCurve"})
        nodes, edges, stats = self.run_link(
            curve_config={"Segments": yc_segments, "InflationSegments": infl_segments})

        self.assertEqual(stats["unresolved_schema"], {})
        by_entry = {n["entry"]: n["id"] for n in nodes}
        (yc,) = self.edges_from(edges, by_entry["Segments"], "maps_to_schema")
        (infl,) = self.edges_from(edges, by_entry["InflationSegments"], "maps_to_schema")
        self.assertEqual(yc["xsd_type"], "segmentsType")
        self.assertEqual(infl["xsd_type"], "inflSegmentsType")
        self.assertEqual((yc["context"], yc["confidence"]), ("fieldmap_xsd_parent", "EXTRACTED"))

    def test_ambiguous_element_without_a_resolving_parent_stays_unresolved(self):
        # No Parent_Node at all - same "never guess" rule as any other
        # ambiguity link_fieldmap refuses to resolve on its own.
        generic = entry({"XML_Node_Name": "Segments"})
        nodes, edges, stats = self.run_link(curve_config={"Segments": generic})

        self.assertEqual(edges, [])
        self.assertEqual(stats["unresolved_schema"]["curve_config"], ["Segments: Segments"])

    def test_forge_xsd_type_that_the_schema_contradicts_is_reported(self):
        trade = entry({"XML_Node_Name": "FxForwardData", "Trade_Type": "FxForward",
                       "XSD_Type": "someOtherData"})
        nodes, edges, stats = self.run_link(trade={"FX Forward": trade})
        (schema,) = self.edges_from(edges, nodes[0]["id"], "maps_to_schema")
        self.assertEqual(schema["xsd_type"], "fxForwardData")   # the schema wins
        self.assertEqual(len(stats["schema_disagreements"]), 1)

    # ---- pricing engines ---------------------------------------------------------

    def test_pricing_product_carries_a_field_list_per_combination(self):
        product = entry(
            {"XML_Node_Name": "Product", "Trade_Type": "Swaption",
             "Cpp_Builders": ["SwaptionEngineBuilder", "HandWrittenBuilder", "GoneBuilder"]},
            combinations=[
                {"Model": "LGM", "Engine": "FD", "nodes": [field("Product/Model")]},
                {"Model": "LGM", "Engine": "MC", "substituted": ["LGM", "FD"],
                 "nodes": [field("Product/Model"), field("Product/Engine", optional=True)]}])
        nodes, edges, stats = self.run_link(pricing_engine={"Swaption": product})

        (node,) = nodes
        self.assertEqual(node["combination_count"], 2)
        self.assertEqual([len(c["fields"]) for c in node["combinations"]], [1, 2])
        self.assertNotIn("fields", node)                         # no single total
        self.assertEqual(stats["domains"]["pricing_engine"]["fields"], 3)
        self.assertEqual(stats["substituted_combinations"], ["Swaption / LGM / MC -> ['LGM', 'FD']"])

        by_role = {(e["role"], e["class_name"]): e for e in edges
                   if e["relation"] == "maps_to_class"}
        # a registration edge in the graph corroborates the builder...
        self.assertEqual(by_role[("engine_builder", "SwaptionEngineBuilder")]["confidence"],
                         "EXTRACTED")
        # ...ORE_Forge's word alone does not...
        self.assertEqual(by_role[("engine_builder", "HandWrittenBuilder")]["confidence"],
                         "INFERRED")
        # ...and a builder that is not in the graph is reported, not linked.
        self.assertNotIn(("engine_builder", "GoneBuilder"), by_role)
        self.assertIn("Swaption: GoneBuilder", stats["unresolved_class"]["pricing_engine"])
        self.assertEqual(by_role[("trade", "Swaption")]["context"], "fieldmap_trade_registry")

    def test_repeated_xpath_is_reported_not_silently_dropped(self):
        trade = entry({"XML_Node_Name": "FxForwardData", "Trade_Type": "FxForward"},
                      [field("Trade/A"), field("Trade/A")])
        nodes, _, stats = self.run_link(trade={"FX Forward": trade})
        self.assertEqual(nodes[0]["field_count"], 1)
        self.assertEqual(stats["duplicate_xpaths"], ["trade/FX Forward#Trade/A"])

    # ---- graph hygiene -----------------------------------------------------------

    def test_pass_is_additive_and_leaves_its_inputs_untouched(self):
        before = copy.deepcopy((self.nodes, self.links))
        trade = entry({"XML_Node_Name": "FxForwardData", "Trade_Type": "FxForward"},
                      [field("Trade/A")])
        nodes, edges, _ = self.run_link(trade={"FX Forward": trade})

        self.assertEqual((self.nodes, self.links), before)
        self.assertTrue(all(n["repo"] == FIELDMAP_REPO and n["_origin"] == "fieldmap_link"
                            for n in nodes))
        self.assertTrue(all(e["_origin"] == "fieldmap_link" for e in edges))

    def test_nodes_are_concepts_and_communities_start_past_the_base(self):
        trade = entry({"XML_Node_Name": "FxForwardData", "Trade_Type": "FxForward"})
        nodes, _, _ = self.run_link(
            trade={"A": trade, "B.1/x": trade})
        self.assertEqual([n["community"] for n in nodes], [5_000_000, 5_000_001])
        # graphify treats an extensionless source_file as a concept node and keeps
        # it out of god_nodes / surprising connections - so no dot may sneak in.
        for n in nodes:
            self.assertEqual(n["file_type"], "concept")
            self.assertNotIn(".", n["source_file"].split("/")[-1])

    def test_relations_agree_with_the_query_layer(self):
        self.assertEqual(set(fieldmap_link.FIELDMAP_RELATIONS), set(query.FIELDMAP_RELATIONS))
        for relation in fieldmap_link.FIELDMAP_RELATIONS:
            self.assertIn(relation, query.RELATION_COST)
            self.assertIn(relation, query.BUNDLE_RELATIONS)
            self.assertNotIn(relation, query.IMPACT_RELATIONS)


class SnapshotTest(unittest.TestCase):
    def test_round_trip_and_old_format_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            snap = FieldmapSnapshot(source="/forge", version={"commit": "abc", "dirty": False},
                                    domains={"trade": {"X": {"meta": {}, "nodes": [{"xpath": "a"}]}}})
            fieldmap.save(snap, path)
            loaded = fieldmap.load(path)
            self.assertEqual((loaded.domains, loaded.version), (snap.domains, snap.version))
            self.assertEqual(loaded.node_count("trade"), 1)

            path.write_text('{"source": "/forge", "trade_types": [], "nodes_by_trade": {}}',
                            encoding="utf-8")
            with self.assertRaisesRegex(FieldmapError, "format 1.*Re-run"):
                fieldmap.load(path)


class QueryFieldsTest(unittest.TestCase):
    def graph(self):
        graph = nx.MultiDiGraph()
        graph.add_node("cls", label="FxForward", repo="OREData", repo_path="OREData/fxforward.hpp")
        graph.add_node("xsd", label="fxForwardData (complexType)", repo="OREXsd",
                       source_file="xsd/instruments.xsd")
        graph.add_node("entry", label="FX Forward [trade mapping]", repo=FIELDMAP_REPO,
                       kind="entry", domain="trade", entry="FX Forward", trade_type="FxForward",
                       xml_node="FxForwardData", asset_class="FX",
                       source_file="fieldmap/trade/FX Forward",
                       fields=[{"xpath": "Trade/FxForwardData/BoughtCurrency", "optional": False,
                                "data_type": "String", "value_set": "Currency"},
                               {"xpath": "Trade/FxForwardData/Settlement", "optional": True}])
        graph.add_edge("entry", "cls", relation="maps_to_class", confidence="EXTRACTED",
                       context="fieldmap_trade_registry", via="Trade_Type=FxForward", role="parser")
        graph.add_edge("entry", "xsd", relation="maps_to_schema", confidence="EXTRACTED",
                       context="fieldmap_xsd_dispatch", xsd_type="fxForwardData", anchor="type")
        return graph

    def test_renders_the_whole_chain_and_finds_the_entry_from_the_class(self):
        for symbol in ("FxForward", "FX Forward", "FxForwardData"):
            output = query.query_fields(self.graph(), symbol)
            self.assertIn("ENTRY FX Forward [trade mapping]", output, symbol)
            self.assertIn("class : FxForward", output)
            self.assertIn("EXTRACTED via fieldmap_trade_registry", output)
            self.assertIn("schema: fxForwardData (complexType) [src=xsd/instruments.xsd]", output)
            self.assertIn("R  Trade/FxForwardData/BoughtCurrency  (String, value_set=Currency)",
                          output)
            self.assertIn("O  Trade/FxForwardData/Settlement", output)

    def test_xpath_filter_and_budget_and_no_match(self):
        graph = self.graph()
        filtered = query.query_fields(graph, "FxForward", xpath="settle")
        self.assertIn("1 field(s), 0 required (of 2; filtered on 'settle')", filtered)
        self.assertNotIn("BoughtCurrency", filtered)
        self.assertIn("TRUNCATED", query.query_fields(graph, "FxForward", limit=1))
        self.assertNotIn("TRUNCATED", query.query_fields(graph, "FxForward", limit=2))
        self.assertEqual(query.query_fields(graph, "Nothing"), "NO FIELD MAPPING: Nothing")

    def test_example_bundle_does_not_cross_a_file_level_schema_anchor(self):
        # Two entries whose XSD type has no node both anchor at the schema file's
        # summary node. That hub says nothing about the second entry being
        # related to the first, so a bundle around one must not pull in the other.
        graph = self.graph()
        graph.add_node("hub", label="Instruments Schema (instruments.xsd)", repo="OREXsd",
                       source_file="xsd/instruments.xsd")
        graph.add_node("other", label="Ascot [trade mapping]", repo=FIELDMAP_REPO, kind="entry",
                       domain="trade", entry="Ascot", source_file="fieldmap/trade/Ascot")
        graph.add_edge("entry", "hub", relation="maps_to_schema", confidence="EXTRACTED",
                       anchor="file")
        graph.add_edge("other", "hub", relation="maps_to_schema", confidence="EXTRACTED",
                       anchor="file")

        output = query.query_example(graph, "FxForward")

        self.assertIn("fieldmap/trade/FX Forward", output)
        self.assertNotIn("Ascot", output)

    def test_example_bundle_gets_a_fieldmap_section_only_when_a_fieldmap_exists(self):
        with_map = self.graph()
        without = nx.MultiDiGraph()
        without.add_node("cls", label="FxForward", repo_path="OREData/ored/portfolio/fxforward.hpp")
        self.assertIn("FIELDMAP:\n  fieldmap/trade/FX Forward", query.query_example(with_map, "FxForward"))
        self.assertNotIn("FIELDMAP", query.query_example(without, "FxForward"))


class VerifyFieldmapTest(unittest.TestCase):
    class Cfg:
        fieldmap = None

    def run_checks(self, nodes, links, meta):
        results = []
        _fieldmap_checks(self.Cfg(), meta, nodes, links,
                         lambda name, ok, detail, severity="error":
                         results.append((name, ok, severity, detail)))
        return {name: (ok, severity, detail) for name, ok, severity, detail in results}

    def graph(self):
        entry_node = {"id": f"{FIELDMAP_REPO}::trade/X", "repo": FIELDMAP_REPO, "kind": "entry",
                      "entry": "X", "field_count": 2,
                      "fields": [{"xpath": "a"}, {"xpath": "b"}]}
        edge = {"source": entry_node["id"], "target": "cls", "relation": "maps_to_class",
                "_origin": "fieldmap_link"}
        meta = {"fieldmap": {"domains": {"trade": {"entries": 1, "fields": 2, "combinations": 0,
                                                   "class_linked": 1, "schema_linked": 0}},
                             "edges": 1, "snapshot": {"commit": "abc"}}}
        return [entry_node], [edge], meta

    def test_a_consistent_graph_passes_the_structure_check(self):
        nodes, links, meta = self.graph()
        self.assertTrue(self.run_checks(nodes, links, meta)["fieldmap structure"][0])

    def test_a_dropped_field_fails_the_structure_check(self):
        nodes, links, meta = self.graph()
        nodes[0]["fields"] = nodes[0]["fields"][:1]          # a truncated attribute
        ok, severity, detail = self.run_checks(nodes, links, meta)["fieldmap structure"]
        self.assertFalse(ok)
        self.assertEqual(severity, "error")
        self.assertIn("fields carried on entries: 1", detail)

    def test_field_nodes_fail_the_structure_check(self):
        # The design that measurably broke retrieval: one node per field.
        nodes, links, meta = self.graph()
        nodes.append({"id": f"{FIELDMAP_REPO}::trade/X#a", "repo": FIELDMAP_REPO,
                      "kind": "field", "label": "a"})
        ok, severity, detail = self.run_checks(nodes, links, meta)["fieldmap structure"]
        self.assertFalse(ok)
        self.assertEqual(severity, "error")
        self.assertIn("fields must be attributes, not nodes", detail)

    def test_missing_fieldmap_is_only_a_finding_when_it_is_configured(self):
        self.assertEqual(self.run_checks([], [], {}), {})
        self.Cfg.fieldmap = Path("/forge")
        try:
            ok, severity, _ = self.run_checks([], [], {})["fieldmap merged"]
        finally:
            self.Cfg.fieldmap = None
        self.assertEqual((ok, severity), (False, "warn"))


if __name__ == "__main__":
    unittest.main()
