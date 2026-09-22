import tempfile
import unittest
from pathlib import Path

from oregraph.xsd_link import (_parse_reference_datum_registrations, link_xsd)

REFERENCEDATA_XSD = '''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
<xs:group name="referenceDataTypes">
  <xs:choice>
    <xs:element type="bondReferenceDatum" name="BondReferenceData"/>
    <xs:element type="cboReferenceDatum" name="CboReferenceData"/>
    <xs:element type="bondBasketData" name="BondBasketData"/>
  </xs:choice>
</xs:group>
</xs:schema>'''

DATABUILDERS_CPP = '''
ORE_REGISTER_REFERENCE_DATUM("Bond", BondReferenceDatum, false)
ORE_REGISTER_REFERENCE_DATUM("CBO", CboReferenceDatum, false)
ORE_REGISTER_REFERENCE_DATUM("BondBasket", BondBasketReferenceDatum, false)
'''


def write(base: Path, rel: str, text: str) -> None:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def xsd_node(node_id: str, source_file: str) -> dict:
    return {"id": f"OREXsd::{node_id}", "label": node_id, "repo": "OREXsd",
            "source_file": source_file}


def code_node(label: str, source_file: str) -> dict:
    return {"id": f"OREData::{label.lower()}", "label": label, "repo": "OREData",
            "source_file": source_file, "_callable_class": True}


class ParseReferenceDatumRegistrationsTest(unittest.TestCase):
    def test_extracts_the_dispatch_string_and_class(self):
        result = _parse_reference_datum_registrations(DATABUILDERS_CPP)
        self.assertEqual(result, {"Bond": "BondReferenceDatum", "CBO": "CboReferenceDatum",
                                  "BondBasket": "BondBasketReferenceDatum"})


class ReferenceDataDispatchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.engine = Path(self._tmp.name)
        write(self.engine, "xsd/referencedata.xsd", REFERENCEDATA_XSD)
        write(self.engine, "OREData/ored/utilities/databuilders.cpp", DATABUILDERS_CPP)
        write(self.engine, "xsd/instruments.xsd",
              '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')
        write(self.engine, "xsd/conventions.xsd",
              '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"/>')
        write(self.engine, "OREData/ored/configuration/conventions.cpp", "")

        self.nodes = [
            xsd_node("xsd_referencedata_bond_reference_datum", "xsd/referencedata.xsd"),
            xsd_node("xsd_referencedata_cbo_reference_datum", "xsd/referencedata.xsd"),
            xsd_node("xsd_referencedata_bond_basket_data", "xsd/referencedata.xsd"),
            code_node("BondReferenceDatum", "portfolio/referencedata.hpp"),
            code_node("CboReferenceDatum", "portfolio/referencedata.hpp"),
            code_node("BondBasketReferenceDatum", "portfolio/referencedata.hpp"),
        ]

    def tearDown(self):
        self._tmp.cleanup()

    def test_exact_and_normalized_registrations_both_resolve(self):
        edges, stats = link_xsd(self.nodes, self.engine)
        by_target = {e["target"]: e for e in edges if e.get("relation") == "implements"
                    and "referencedata" in e["target"]}
        self.assertEqual(by_target["OREXsd::xsd_referencedata_bond_reference_datum"]["source"],
                         "OREData::bondreferencedatum")
        cbo = by_target["OREXsd::xsd_referencedata_cbo_reference_datum"]
        self.assertEqual(cbo["source"], "OREData::cboreferencedatum")
        # "Cbo" (stripped element name) vs "CBO" (registered string): only the
        # normalized fallback bridges the case difference.
        self.assertIn("_normalized", cbo["context"])
        # BondBasketData doesn't end in "ReferenceData" - only the shorter
        # "Data" suffix applies, giving candidate "BondBasket", which matches
        # the registration table exactly.
        basket = by_target["OREXsd::xsd_referencedata_bond_basket_data"]
        self.assertEqual(basket["source"], "OREData::bondbasketreferencedatum")
        self.assertNotIn("_normalized", basket["context"])

        rd = stats["reference_data_dispatch"]
        self.assertEqual((rd["matched_exact"], rd["matched_normalized"]), (2, 1))
        self.assertEqual(rd["attempted"], 3)
        self.assertEqual(rd["unmatched_names"], [])

    def test_a_genuine_referencedata_suffix_is_not_shadowed_by_the_shorter_one(self):
        # If the longer suffix were tried second (or not preferred), "BondReferenceData"
        # would also match via "Data" -> candidate "BondReference", which isn't
        # registered at all - it must never fall through to that.
        edges, _ = link_xsd(self.nodes, self.engine)
        bond = next(e for e in edges if e["target"] == "OREXsd::xsd_referencedata_bond_reference_datum")
        self.assertEqual(bond["source"], "OREData::bondreferencedatum")

    def test_no_engine_root_skips_the_pass_rather_than_guessing(self):
        _, stats = link_xsd(self.nodes, engine_root=None)
        self.assertEqual(stats["reference_data_dispatch"], {"skipped": "no engine_root"})


if __name__ == "__main__":
    unittest.main()
