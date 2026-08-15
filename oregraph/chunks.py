"""The ORE corpus map.

ORE is far too large to graph in one pass (~5,000 code files; graphify warns
above 500), so it is split into chunks that are extracted independently and
stitched together afterwards by `merge.py`.

Two rules govern this file:

1. **Never change the target list of a chunk that has curated labels.**
   Community ids come out of Louvain clustering and are not stable when the
   corpus changes. `labels/<chunk>.json` is keyed by community id, so editing a
   labelled chunk's targets silently repoints every label. Add new content as a
   *new* chunk instead. (`labels/<chunk>.anchors.json` makes labels survive
   ordinary code drift, but not a deliberate corpus change.)

2. **Every path in the repo should belong to exactly one chunk.** Run
   `python -m oregraph coverage` to check; it reports files no chunk claims.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Chunk:
    name: str
    #: Directory (relative to the Engine repo) used to relativize source_file
    #: paths. Chunks that split one logical project must share a root so their
    #: node paths stay consistent for the later merge.
    root: str
    #: Paths relative to `root`. A trailing "/**" means "the directory tree";
    #: a glob like "*.hpp" matches files directly in root only.
    targets: tuple[str, ...]
    kind: str = "code"          # code | semantic
    note: str = ""
    #: Chunks added after the original labelling pass have no curated labels yet.
    labelled: bool = True

    def resolve(self, engine: Path) -> list[Path]:
        """Expand targets into concrete existing paths."""
        base = engine / self.root
        out: list[Path] = []
        for t in self.targets:
            if t == ".":
                if base.exists():
                    out.append(base)
            elif any(ch in t for ch in "*?["):
                out.extend(sorted(p for p in base.glob(t) if p.is_file()))
            else:
                p = base / t
                if p.exists():
                    out.append(p)
        return out


QL = "QuantLib/ql"

# ---------------------------------------------------------------------------
# Original chunks - these carry curated labels. DO NOT edit their targets.
# ---------------------------------------------------------------------------
LABELLED: tuple[Chunk, ...] = (
    Chunk("QuantLib-01-foundations", QL,
          ("math", "patterns", "utilities", "currencies", "quotes")),
    Chunk("QuantLib-02-timeinfra", QL,
          ("time", "cashflows", "indexes", "legacy")),
    Chunk("QuantLib-03-methods-termstructures", QL,
          ("methods", "termstructures")),
    Chunk("QuantLib-04-instruments-pricing", QL,
          ("instruments", "pricingengines")),
    Chunk("QuantLib-05-models", QL, ("models",)),
    Chunk("QuantLib-06-experimental", QL, ("experimental",)),
    Chunk("QuantExt", "QuantExt/qle", (".",)),
    Chunk("OREData", "OREData/ored", (".",)),
    Chunk("OREAnalytics", "OREAnalytics/orea", (".",)),
    Chunk("App", "App", (".",)),
)

# ---------------------------------------------------------------------------
# Chunks added to close coverage gaps. New, so not labelled yet.
# ---------------------------------------------------------------------------
ADDED: tuple[Chunk, ...] = (
    Chunk("QuantLib-00-core", QL, ("*.hpp", "*.cpp"), labelled=False,
          note="Top-level ql/ headers - Instrument, StochasticProcess, "
               "TermStructure, Quote, Settings, Handle. The base classes the "
               "rest of ORE inherits from; omitted from the original chunk map."),
    Chunk("QuantLib-07-processes", QL, ("processes",), labelled=False,
          note="ql/processes - omitted from the original chunk map entirely."),
    Chunk("ORESwig", "ORE-SWIG",
          ("OREData-SWIG", "OREAnalytics-SWIG", "QuantExt-SWIG", "test",
           "setup.py", "__init__.py"),
          labelled=False, note="Python/Java bindings and their pytest suite."),
    Chunk("OREToolsFrontEnd", ".", ("Tools", "FrontEnd"), labelled=False,
          note="Python tooling, comparison harness, npvcube dashboards."),
    Chunk("ORETests", ".",
          ("OREData/test", "OREAnalytics/test", "QuantExt/test", "ORETest",
           "QuantLib/test-suite"),
          labelled=False, note="All C++ unit-test suites."),
    Chunk("OREExamples", "Examples", (".",), labelled=False,
          note="Example drivers and portfolios. AST covers the .py/.ipynb; the "
               "XML/CSV configs need the semantic pass (see `semantic` command)."),
    Chunk("QuantLibExamples", "QuantLib/Examples", (".",), labelled=False,
          note="QuantLib's own example programs (AsianOption, Bonds, CDS, ...) - "
               "distinct from ORE's top-level Examples/. Found by `coverage`, "
               "omitted from the original chunk map."),
    Chunk("QuantLibFuzzTests", "QuantLib/fuzz-test-suite", (".",), labelled=False,
          note="QuantLib fuzzing harnesses. Found by `coverage`."),
    Chunk("QuantLibTools", "QuantLib/tools", (".",), labelled=False,
          note="QuantLib maintainer scripts (check_header.py, etc). Found by "
               "`coverage`."),
    Chunk("PythonIntegration", "PythonIntegration", (".",), labelled=False,
          note="A top-level dir with no chunk at all in the original map. "
               "Found by `coverage`."),
)

# Semantic chunks - built from committed extraction JSON, no LLM needed at build
# time. See semantic-chunks/ and `python -m oregraph semantic --help`.
SEMANTIC: tuple[Chunk, ...] = (
    Chunk("OREDocs", "Docs", (".",), kind="semantic",
          note="329 LaTeX files (UserGuide, ScriptedTrade, model docs)."),
    Chunk("OREXsd", "xsd", (".",), kind="semantic",
          note="23 XSD schemas defining every ORE input format."),
    Chunk("OREExamplesConfig", "Examples", (".",), kind="semantic",
          labelled=False,
          note="Example XML portfolios and CSV market data. Not yet extracted - "
               "run `python -m oregraph semantic --corpus examples`."),
)

CODE_CHUNKS: tuple[Chunk, ...] = LABELLED + ADDED
ALL_CHUNKS: tuple[Chunk, ...] = CODE_CHUNKS + SEMANTIC

BY_NAME = {c.name: c for c in ALL_CHUNKS}

#: Include-prefix -> chunk root, used by link.py to resolve C++ #include
#: directives across chunk boundaries.
INCLUDE_ROOTS = {
    "ql/": QL,
    "qle/": "QuantExt/qle",
    "ored/": "OREData/ored",
    "orea/": "OREAnalytics/orea",
}


def code_chunks(include_added: bool = True) -> tuple[Chunk, ...]:
    return CODE_CHUNKS if include_added else LABELLED
