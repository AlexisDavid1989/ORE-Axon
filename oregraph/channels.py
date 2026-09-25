"""Intent-routed retrieval channels for `query_question`.

`query_question` seeds from one lexical scale: every node is scored by how a
question word matches its label, and the best six win. That scale cannot serve a
question that names a *kind of artifact* rather than a symbol. A user-guide page
titled "Default Curve from CDS" scores ~10 against a code class's 120, so
"how does the user guide describe default curves" seeds six classes and no page;
"what tests cover credit default swaps" cannot see `test/cds.cpp` because the
question says "credit default swaps", not "cds"; and "which conventions does a
yield curve config use" cannot follow the typed `maps_to_convention` links the
fieldmap carries, because a walk that treats every edge alike reaches
`YieldCurve [curve config mapping]` and then 171 trades before its 13 conventions.

Each channel here answers one kind of question by searching *that kind of node*
and handing the result to the ranker as priority nodes:

  tests / docs / schema   the ORETests / OREDocs / OREXsd nodes that match the
                          topic (question words minus the kind's own vocabulary)
  fieldmap                the OREFieldmap entries that match the topic, then the
                          entries in the domains the question names, by link type
  pricing                 the engine builders and engines a trade class is priced
                          with: through `build`, and through the fieldmap registry
                          (builders are looked up by trade-type string, so no code
                          edge exists)
  structure               same-header siblings and base classes of the top seeds
  schema composition      what a schema type is composed of (`legData` for a credit default swap)
  lexical                 nodes anywhere whose label is made mostly of the question's words

Every channel is silent when the topic matches nothing, so a misfiring intent
costs no more than the words it would have spent. The intent vocabulary is
ORE-independent English about artifacts ("tests", "user guide", "schema",
"convention"), not a list of answers; `tests/test_channels.py` checks that
paraphrases reach the same nodes.

Evidence (docs/RETRIEVAL.md): on `g01-g17`, questions written from the source and never
tuned on, the served answer goes from 5/17 to 16/17 questions passing; on the development
set `h01-h16`, from 8/16 to 15/16.
"""
from __future__ import annotations

import heapq
import math
import re
from dataclasses import dataclass, field

from .query import _QUESTION_STOPWORDS, _label, _weight, _word_matches

# --- intent vocabulary ------------------------------------------------------
TEST_WORDS = ("test", "regression", "coverage")
DOC_WORDS = ("guide", "userguide", "documentation", "docs", "doc", "manual")
SCHEMA_WORDS = ("xsd", "schema", "complextype")
PRICING_WORDS = ("price", "pricing", "valuation", "npv", "value", "built", "build")
#: Phrases naming a fieldmap domain. "engine" alone is enough for pricing_engine:
#: "what engine does ORE use to value an FX option" says no "pricing".
FIELDMAP_PHRASES = (("pricing engine", "pricing_engine"), ("engine", "pricing_engine"),
                    ("curve config", "curve_config"), ("convention", "convention"),
                    ("fieldmap", "*"), ("field mapping", "*"), ("mapping", "*"))
#: Words that never name a topic here: they are about the question, or about every
#: ORE trade, so matching them would only add noise.
FILLER = frozenset("""ore quantlib quantext oredata oreanalytics say says describe describes cover covers
check checks define defines use uses used does file files exist exists resolve resolves have has
verify verifies validate validates exercise exercises contain contains include includes show shows
trade trades xml field fields parameter parameters setting settings work works
element elements type types unit units suite section sections page pages
link links linked reference references referenced map maps mapped relate relates related""".split())
#: Module names are one word to a person ("OREData"), not "ORE" and "data".
MODULE_NAMES = ("oredata", "oreanalytics", "quantext", "quantlib", "ore")
#: Words that name the domain of a fieldmap entry, not the entry ("[curve config mapping]").
FIELDMAP_DOMAIN_WORDS = ("config", "configuration", "engine", "pricing", "price", "convention",
                         "fieldmap", "mapping", "field", "fields", "trade", "value")

KIND_REPOS = {"tests": frozenset({"ORETests"}), "docs": frozenset({"OREDocs"}),
              "schema": frozenset({"OREXsd", "OREXsdSupplement"})}
#: How many nodes each kind channel contributes.
KIND_LIMIT = {"tests": 8, "docs": 5, "schema": 6}
DOMAIN_RELATION = {"pricing_engine": "maps_to_pricing_engine", "curve_config": "maps_to_curve_config",
                   "convention": "maps_to_convention"}

#: An entry must cover this share of the topic terms the fieldmap knows about, and
#: score at least RELATIVE_CUTOFF of the best entry: "FX volatility" must not follow
#: `CDSVolatility`, which matches one of the two words.
COVERAGE_MIN = 0.66
RELATIVE_CUTOFF = 0.6
#: A term found only as the initials of a longer name counts for less than one found
#: as a word: "cds" is a hint, and must not outrank `creditDefaultSwapData`.
ACRONYM_WEIGHT = 0.6
#: What a node keeps of its score when the question accounts for none of its file's name:
#: a test *file* named for the topic is the answer, a label that mentions it in an
#: unrelated file (`createCdsVolCurve` in testmarket.hpp) is not.
FILE_NAME_FLOOR = 0.3
#: A name that the question's own phrase spells or starts ("fx option" -> `FxOption`,
#: `FxOptionAmerican`) beats one that merely contains both words (`FxAsianOptionArithmeticPrice`).
PHRASE_BONUS = 0.5
#: A word that both names a domain and appears in entry names ("curve" in "curve config"
#: and in `YieldCurve`) still helps rank, but is not required.
MARKER_WEIGHT = 0.25
FIELDMAP_LIMIT = 28
STRUCTURE_SEEDS = 3          # top class seeds whose siblings and base classes are added
SIBLING_LIMIT = 10
ANCESTOR_DEPTH, ANCESTOR_LIMIT = 4, 8
DERIVED_LIMIT, DERIVED_MAX = 10, 40
FLOW_TRADES, FLOW_PER_KIND, REGISTRY_LIMIT = 2, 2, 6
LEXICAL_LIMIT, LEXICAL_MIN_OVERLAP, LEXICAL_SHARE = 3, 2, 0.5
REGISTRY_ENGINES = 4          # builders whose engines are followed
COMPOSITION_TYPES, COMPOSITION_LIMIT = 4, 6   # schema types whose components are added, per type

_WORD = re.compile(r"[A-Za-z0-9']+")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_SUFFIXES = ("ations", "ation", "ators", "ator", "ings", "ing", "ions", "ion", "ates", "ate",
             "ers", "er", "ed", "es", "s", "e", "y")


# --- words -------------------------------------------------------------------
def split_tokens(text: str) -> list[str]:
    """camelCase / snake_case / spaced text as lower-case words; parenthesised
    qualifiers like "(complexType)" and "[curve config mapping]" are not part of a name."""
    text = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", text)
    return [p.lower() for p in _CAMEL.findall(text) if len(p) > 1]


def stem(word: str) -> str:
    """Suffix stripping strong enough for interpolate/interpolation, priced/pricing/price,
    parsed/parse. Deliberately not shared with `query._stem`, which the alias matcher's
    tests pin."""
    word = word.lower()
    for suffix in _SUFFIXES:
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[:-len(suffix)]
    return word


_PROTECTED = frozenset(SCHEMA_WORDS + DOC_WORDS + TEST_WORDS + MODULE_NAMES + ("fieldmap",))


def channel_terms(question: str) -> list[str]:
    """The question's words with a typed identifier split at its camelCase joins
    ("DefaultCurve" -> default, curve), stopwords removed and 2-letter words kept ("fx").
    The intent words are not split: "complexType" is one word, not "complex", "type"."""
    out = []
    for word in _WORD.findall(question):
        parts = [word] if word.lower() in _PROTECTED else (_CAMEL.findall(word) or [word])
        for part in parts:
            part = part.lower().replace("'", "")
            if part and part not in _QUESTION_STOPWORDS and len(part) > 1:
                out.append(part)
    return out


def _has(terms: list[str], words: tuple) -> bool:
    return any(_word_matches(t, w) for t in terms for w in words)


def _mentions(terms: list[str], phrase: str) -> bool:
    wanted = phrase.split()
    return any(all(_word_matches(t, w) for t, w in zip(terms[i:i + len(wanted)], wanted))
               for i in range(len(terms) - len(wanted) + 1))


@dataclass
class Intents:
    tests: bool = False
    docs: bool = False
    schema: bool = False
    pricing: bool = False
    fieldmap: set = field(default_factory=set)      # domains named; "*" = all


def detect_intents(terms: list[str]) -> Intents:
    domains = {domain for phrase, domain in FIELDMAP_PHRASES if _mentions(terms, phrase)}
    if domains & {"pricing_engine", "curve_config", "*"}:
        domains.add("trade")            # those links start at a trade entry: it is part of the answer
    return Intents(tests=_has(terms, TEST_WORDS), docs=_has(terms, DOC_WORDS),
                   schema=_has(terms, SCHEMA_WORDS), pricing=_has(terms, PRICING_WORDS),
                   fieldmap=domains)


def topic_terms(terms: list[str], drop: tuple = ()) -> list[str]:
    """What the question is *about*: its words minus filler and the kind's own vocabulary."""
    return [t for t in terms
            if len(t) >= 2 and t not in FILLER and not any(_word_matches(t, w) for w in drop)]


def _initials(words) -> str:
    return "".join(w[0] for w in words)


class Topic:
    """The question's topic words, prepared once: stems, adjacent-word joins ("fxoption")
    and acronyms ("cds"), each with the positions it covers."""
    __slots__ = ("terms", "stems", "forms", "whole")

    def __init__(self, terms: list[str]):
        self.terms = terms
        self.whole = "".join(terms)          # the whole topic as one name: "fx option" -> fxoption
        self.stems = [stem(t) for t in terms]
        self.forms = []
        for size in (2, 3, 4):
            for i in range(len(terms) - size + 1):
                words, cover = terms[i:i + size], set(range(i, i + size))
                join = "".join(words)
                if len(join) >= 3:
                    self.forms.append((join, stem(join), cover, "join"))
                acronym = _initials(words)
                if len(acronym) >= 3:
                    self.forms.append((acronym, acronym, cover, "acronym"))

    def __len__(self):
        return len(self.terms)


# --- scoring one name against the topic -----------------------------------------
class Name:
    """A node's (or fieldmap entry's) searchable name, prepared once. `more` are further
    word sequences that name the same thing (a file stem, segmented)."""
    __slots__ = ("tokens", "stems", "joined", "joined_stem", "acronyms")

    def __init__(self, text: str, joined_from: str | None = None, more: tuple = ()):
        seqs = [split_tokens(text), *[list(m) for m in more]]
        self.tokens = {t for seq in seqs for t in seq}
        self.stems = {stem(t) for t in self.tokens}
        self.joined = re.sub(r"[^a-z0-9]", "", (joined_from or text).lower())
        self.joined_stem = stem(self.joined)
        self.acronyms = {_initials(seq[i:i + n]) for seq in seqs for n in (2, 3, 4)
                         for i in range(len(seq) - n + 1)}


def _vocabulary(graph) -> frozenset:
    """Every word the graph's identifiers are made of: what a name with no word boundary
    ("digitalcms", "creditdefaultswapdata") can be cut into. Only words that stand at a
    real boundary count - a file node's label is itself such a name, and a vocabulary that
    contains it can never cut it."""
    cache = graph.graph.get("_channel_vocab")
    if cache is None:
        words = set()
        for node_id, data in graph.nodes(data=True):
            parts = split_tokens(_label(node_id, data).rsplit(".", 1)[0])
            if len(parts) >= 2:
                words.update(t for t in parts if 3 <= len(t) <= 12)
            elif parts and 3 <= len(parts[0]) <= 8:
                words.add(parts[0])
        cache = graph.graph["_channel_vocab"] = frozenset(words)
    return cache


def segment(text: str, vocab) -> list[str]:
    """*text* as the fewest vocabulary words that spell it, or [text] when none do
    ("digitalcms" -> digital, cms). A string that is itself a word is not cut."""
    if text in vocab or len(text) < 6:
        return [text]
    best: list = [None] * (len(text) + 1)
    best[0] = []
    for end in range(3, len(text) + 1):
        for start in range(max(0, end - 20), end - 2):
            word = text[start:end]
            if best[start] is not None and word in vocab:
                cand = best[start] + [word]
                if best[end] is None or len(cand) < len(best[end]):
                    best[end] = cand
    return best[len(text)] or [text]


def _term_in(topic: Topic, i: int, name: Name) -> bool:
    if topic.stems[i] in name.stems:
        return True
    term = topic.terms[i]
    return len(term) >= 5 and any(t.startswith(term) for t in name.tokens)


def score_name(topic: Topic, name: Name, idf: dict, weight: dict | None = None):
    """idf-weighted topic coverage of one name -> (score, matched term positions).

    A term found as a word counts in full, so does one found through an adjacent-word
    join ("fx option" -> FxOption). A term found only as an acronym - either direction,
    "cds" in the question for CreditDefaultSwap, or "credit default swap" for `cds` -
    counts ACRONYM_WEIGHT."""
    w = dict(weight or {})
    direct = {i for i in range(len(topic)) if _term_in(topic, i, name)}
    joined_hit, acronym_hit, phrase_cover = set(), set(), set()
    for i, term in enumerate(topic.terms):
        if len(term) >= 3 and term in name.acronyms:
            acronym_hit.add(i)
    for form, form_stem, cover, kind in topic.forms:
        if kind == "join":
            if name.joined == form:
                # The phrase spells the whole name ("yield curve" -> YieldCurve): the
                # strongest evidence there is, so no word in it is a mere marker.
                for i in cover:
                    w.pop(i, None)
            if (name.joined == form or (len(form) >= 8 and name.joined.startswith(form))
                    or name.joined_stem == form_stem):
                joined_hit |= cover
                phrase_cover |= cover
        elif form in name.tokens:
            acronym_hit |= cover
    if name.joined == topic.whole:
        # A name that *is* the topic ("Swaption") is the entry the question names, unlike
        # `CommoditySwaption` and `Forward Starting Swaption`, which only contain the word.
        phrase_cover |= set(range(len(topic)))
        joined_hit |= set(range(len(topic)))
        for i in range(len(topic)):
            w.pop(i, None)
    full = direct | joined_hit
    score = (sum(idf.get(i, 1.0) * w.get(i, 1.0) for i in full)
             + PHRASE_BONUS * sum(idf.get(i, 1.0) * w.get(i, 1.0) for i in phrase_cover)
             + ACRONYM_WEIGHT * sum(idf.get(i, 1.0) * w.get(i, 1.0) for i in acronym_hit - full))
    return score, full | acronym_hit


def _idf(topic: Topic, names: list[Name]) -> tuple[dict, list[int]]:
    """idf of each topic term over *names*, and the terms the kind knows at all
    (a filler word like "elements" matches nothing and must not count against coverage)."""
    df = [sum(1 for nm in names if _term_in(topic, i, nm)) for i in range(len(topic))]
    idf = {i: math.log(1 + len(names) / (1 + df[i])) for i in range(len(topic))}
    return idf, [i for i in range(len(topic)) if df[i] > 0]


# --- kind channels ---------------------------------------------------------------
def _kind_items(graph, kind: str) -> list[tuple]:
    cache = graph.graph.setdefault("_channel_kinds", {})
    if kind not in cache:
        repos, items, vocab = KIND_REPOS[kind], [], _vocabulary(graph)
        for node_id, data in graph.nodes(data=True):
            if data.get("repo") not in repos:
                continue
            source = str(data.get("source_file") or "")
            base = source.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            label = _label(node_id, data)
            words = tuple(segment(base.lower(), vocab)) if base else ()
            name = Name(label, joined_from=base, more=(words,) if words else ())
            items.append((node_id, source, label, name, words or (base.lower(),), base.lower()))
        cache[kind] = items
    return cache[kind]


def _named(topic: Topic, words: tuple) -> float:
    """Share of a file name's words that the topic accounts for: a word the question
    says, or one of the 2-4 words whose initials the question spells ("cds")."""
    covered = {i for i, w in enumerate(words) if stem(w) in topic.stems}
    for size in (2, 3, 4):
        for i in range(len(words) - size + 1):
            if _initials(words[i:i + size]) in topic.terms:
                covered.update(range(i, i + size))
    return len(covered) / max(1, len(words))


_DROP = {"tests": TEST_WORDS, "docs": DOC_WORDS + ("user",), "schema": SCHEMA_WORDS}


def kind_seeds(graph, kind: str, terms: list[str], limit: int | None = None) -> list:
    """The best `limit` nodes of *kind* for the question's topic, best first.

    Tests and docs are answered a file at a time (any node of `test/cds.cpp` says the
    file is relevant, so the file's own node stands for it); schema types are each
    their own answer, although they share one file."""
    words = topic_terms(terms, _DROP[kind])
    items = _kind_items(graph, kind)
    if not words or not items:
        return []
    topic = Topic(words)
    idf, _known = _idf(topic, [it[3] for it in items])
    best: dict = {}
    for node_id, source, label, name, file_words, base in items:
        score, matched = score_name(topic, name, idf)
        if not matched:
            continue
        # A file named for the topic beats one that merely mentions it: share of the
        # file-name words the question accounts for, spelled or as an acronym.
        score *= FILE_NAME_FLOOR + (1 - FILE_NAME_FLOOR) * _named(topic, file_words)
        is_file_node = label.rsplit(".", 1)[0].lower() == base
        rank = (score, is_file_node, graph.degree(node_id))
        key = str(node_id) if kind == "schema" else source
        if key not in best or rank > best[key][0]:
            best[key] = (rank, node_id)
    ordered = sorted(best.values(), key=lambda v: (-v[0][0], -int(v[0][1]), -v[0][2], str(v[1])))
    return [n for _rank, n in ordered[:limit or KIND_LIMIT[kind]]]


# --- fieldmap channel -------------------------------------------------------------
def _entries(graph) -> list[tuple]:
    cache = graph.graph.get("_channel_entries")
    if cache is None:
        cache = []
        for node_id, data in graph.nodes(data=True):
            if data.get("repo") != "OREFieldmap" or data.get("kind") != "entry":
                continue
            # An entry answers to its own names. A curve config's C++ class name
            # ("CDSVolatilityCurveConfig") would make every one of them match "curve".
            keys = ("entry", "trade_type", "xml_node") + (("cpp_class_name",)
                                                          if data.get("domain") == "trade" else ())
            names = [Name(str(data.get(k) or "")) for k in keys if data.get(k)]
            cache.append((node_id, data, names))
        graph.graph["_channel_entries"] = cache
    return cache


def _out(graph, node_id, relation: str) -> list:
    return [m for _u, m, e in graph.out_edges(node_id, data=True) if e.get("relation") == relation]


def _in(graph, node_id, relation: str) -> list:
    return [u for u, _v, e in graph.in_edges(node_id, data=True) if e.get("relation") == relation]


def _marker_weights(terms: list[str], topic: list[str]) -> dict:
    """"curve" in "which curve config ..." names the domain; in "yield curve config" it
    is also part of the entry's name. Either way it is a weak term."""
    marked = {a for a, b in zip(terms, terms[1:]) if b.startswith("config")}
    return {i: MARKER_WEIGHT for i, t in enumerate(topic) if t in marked}


def fieldmap_priority(graph, terms: list[str], domains: set, limit: int = FIELDMAP_LIMIT) -> list:
    """Fieldmap entries (and the classes they name) that answer a question about
    *domains*: the entries matching the topic, those in the requested domains, and the
    entries the matching ones link to by type - "which conventions does a yield curve
    config use" is YieldCurve's `maps_to_convention` targets."""
    if not graph.is_directed():
        return []
    words = topic_terms(terms, FIELDMAP_DOMAIN_WORDS)
    entries = _entries(graph)
    if not words or not entries:
        return []
    topic = Topic(words)
    idf, known = _idf(topic, [nm for _n, _d, names in entries for nm in names])
    weight = _marker_weights(terms, words)
    core = [i for i in known if i not in weight]
    scored = []
    for node_id, data, names in entries:
        best_score, best_matched = 0.0, set()
        for nm in names:
            score, matched = score_name(topic, nm, idf, weight)
            if score > best_score:
                best_score, best_matched = score, matched
        if not best_matched:
            continue
        coverage = len(best_matched & set(core)) / max(1, len(core))
        if coverage >= COVERAGE_MIN:
            scored.append((best_score * (0.5 + 0.5 * coverage), node_id, data))
    scored.sort(key=lambda s: (-s[0], str(s[1])))
    if not scored:
        return []
    chosen = [s for s in scored if s[0] >= RELATIVE_CUTOFF * scored[0][0]]

    def wanted(domain):
        return "*" in domains or domain in domains

    out: list = []
    seen: set = set()

    def add(node_id):
        if node_id not in seen and len(out) < limit:
            seen.add(node_id)
            out.append(node_id)

    def add_with_classes(node_id):
        # An entry and the class / builder it names are one answer: "which pricing
        # engine" is the entry and its EngineBuilder.
        add(node_id)
        for cls in _out(graph, node_id, "maps_to_class"):
            add(cls)

    def hop(node_id, data):
        for domain, relation in DOMAIN_RELATION.items():            # typed hops into the named domains
            if wanted(domain) and domain != data.get("domain"):
                for target in _out(graph, node_id, relation):
                    add_with_classes(target)

    subjects = [s for s in chosen if s[2].get("domain") == "trade" or wanted(s[2].get("domain"))][:3]
    for _score, node_id, data in subjects:
        add_with_classes(node_id)
        if data.get("domain") == "trade":
            # The trade's engine builder is where its curves are resolved from the market
            # (`market_->defaultCurve(...)`), so it answers "which curve config" too.
            for engine_entry in _out(graph, node_id, "maps_to_pricing_engine"):
                for cls in _out(graph, engine_entry, "maps_to_class"):
                    if _label(cls, graph.nodes[cls]).endswith(("EngineBuilder", "EngineBuilderBase")):
                        add(cls)
                        for base in builder_bases(graph, cls):
                            add(base)
    for _score, node_id, data in subjects:
        hop(node_id, data)
    # The rest of the matches, one domain after another: a question naming a trade and its
    # pricing engines must not fill the limit with fourteen engines before the trade.
    seen_rank: dict = {}
    rounds = []
    for entry in chosen:
        domain = entry[2].get("domain")
        rounds.append((seen_rank.setdefault(domain, 0), -entry[0], str(entry[1]), entry))
        seen_rank[domain] += 1
    for _r, _s, _i, (_score, node_id, data) in sorted(rounds, key=lambda r: r[:3]):
        if (_score, node_id, data) not in subjects:
            if wanted(data.get("domain")):
                add_with_classes(node_id)
            hop(node_id, data)
    return out


# --- pricing: trade -> build -> builder -> engine ----------------------------------
_FLOW = frozenset({"calls", "constructs", "registers", "uses"})


def flow_nodes(graph, trade, per: int = FLOW_PER_KIND, max_hops: int = 3) -> list:
    """Engine builders and engines reached from `trade::build`, cheapest first: what
    `query_flow` finds, as nodes. Empty unless *trade* is a portfolio class with a `build`."""
    if not graph.is_directed() or not str(graph.nodes[trade].get("source_file") or "").startswith("portfolio/"):
        return []
    builds = [m for m in _out(graph, trade, "defines") if _label(m, graph.nodes[m]) == "build"]
    if not builds:
        return []
    best = {builds[0]: 0.0}
    heap = [(0.0, 0, str(builds[0]), builds[0])]
    found: dict = {"builder": [], "engine": []}
    while heap:
        cost, hops, _order, node_id = heapq.heappop(heap)
        if cost > best.get(node_id, math.inf):
            continue
        label = _label(node_id, graph.nodes[node_id])
        if hops:
            if label.endswith(("EngineBuilder", "EngineBuilderBase")):
                found["builder"].append((cost, str(node_id), node_id))
            elif label.endswith("Engine") and "pricingengines" in str(graph.nodes[node_id].get("source_file") or ""):
                found["engine"].append((cost, str(node_id), node_id))
        if hops >= max_hops:
            continue
        for _u, m, e in graph.out_edges(node_id, data=True):
            if str(e.get("relation", "")).lower() not in _FLOW:
                continue
            cost2 = cost + _weight(node_id, m, graph.get_edge_data(node_id, m))
            if cost2 < best.get(m, math.inf):
                best[m] = cost2
                heapq.heappush(heap, (cost2, hops + 1, str(m), m))
    return [n for kind in ("builder", "engine") for _c, _s, n in sorted(found[kind])[:per]]


_BUILDER_LINKS = frozenset({"constructs", "uses", "includes", "defines", "method", "calls", "references"})


def builder_engines(graph, builder, per: int = FLOW_PER_KIND, max_hops: int = 2) -> list:
    """The pricing engines an engine builder builds: the ones its header includes or its
    `engineImpl` constructs (`BondEngineBuilder` includes `DiscountingRiskyBondEngine`).
    A registry builder is found from the trade without a code edge; this is the step from
    it to the engine, which is what "how is a bond priced" is asking for."""
    if not graph.is_directed():
        return []
    found, frontier, seen = [], [builder], {builder}
    for hop in range(1, max_hops + 1):
        following = []
        for node_id in frontier:
            for _u, m, e in graph.out_edges(node_id, data=True):
                if e.get("relation") not in _BUILDER_LINKS or m in seen:
                    continue
                seen.add(m)
                label = _label(m, graph.nodes[m])
                if label.endswith("Engine") and "pricingengines" in str(graph.nodes[m].get("source_file") or ""):
                    found.append((hop, label, str(m), m))
                elif hop < max_hops and "/builders/" in str(graph.nodes[m].get("source_file") or ""):
                    following.append(m)
        frontier = following
    found.sort()
    return [m for _h, _l, _s, m in found[:per]]


def pricing_subjects(graph, seeds: list) -> list:
    """The ORE trade classes a pricing question is about, in seed order. "How is a bond
    priced" seeds `Bond` the QuantLib instrument (one seed per label); the ORE `Bond` trade,
    which owns `build` and its engine builder, is the same word and stands in its place."""
    from .query import _norm_index, _norm_key
    index, out = _norm_index(graph), []
    for seed in seeds:
        data = graph.nodes[seed]
        if str(data.get("source_file") or "").startswith("portfolio/"):
            out.append(seed)
            continue
        key = _norm_key(data.get("norm_label") or _label(seed, data))
        out += [n for n in index.get(key, ())
                if str(graph.nodes[n].get("source_file") or "").startswith("portfolio/") and _is_class(graph, n)]
    return list(dict.fromkeys(out))


def builder_bases(graph, builder) -> list:
    """The builder classes *builder* extends that live beside it (`MidPointCdsEngineBuilder`
    -> `CreditDefaultSwapEngineBuilder`), not the framework's own (`CachingPricingEngineBuilder`):
    the registry names the leaf, the base is where the curves and parameters are read."""
    if not graph.is_directed():
        return []
    return [m for m in _out(graph, builder, "inherits")
            if "/builders/" in str(graph.nodes[m].get("source_file") or "")
            and _label(m, graph.nodes[m]).endswith(("EngineBuilder", "EngineBuilderBase"))]


def registry_builders(graph, trade, limit: int = REGISTRY_LIMIT) -> list:
    """Engine builders ORE_Forge's registry ties to *trade*. A builder is looked up by
    trade-type string when the trade builds, so the code has no edge to it; the fieldmap
    entries for the trade name both the class and the builder."""
    if not graph.is_directed():
        return []
    out, seen, frontier = [], {trade}, [trade]
    for _ in range(3):
        following = []
        for node_id in frontier:
            neighbours = _in(graph, node_id, "maps_to_class")
            if graph.nodes[node_id].get("repo") == "OREFieldmap":
                neighbours += _out(graph, node_id, "maps_to_class") + _out(graph, node_id, "maps_to_pricing_engine")
            for m in neighbours:
                if m in seen:
                    continue
                seen.add(m)
                if graph.nodes[m].get("repo") == "OREFieldmap":
                    following.append(m)
                elif _label(m, graph.nodes[m]).endswith(("EngineBuilder", "EngineBuilderBase")):
                    out.append(m)
        frontier = following
    # The plain builder before its decorated variants (`SwapEngineBuilder`, then
    # `CamAmcSwapEngineBuilder`, `AmcCgCurrencySwapEngineBuilder`): a trade type has one
    # canonical builder and several for particular models, and alphabetical order put the
    # AMC ones first.
    out.sort(key=lambda n: (len(_label(n, graph.nodes[n])), _label(n, graph.nodes[n]), str(n)))
    return list(dict.fromkeys(out + [b for n in out for b in builder_bases(graph, n)]))[:limit]


_USAGE = frozenset({"calls", "uses", "constructs", "registers"})   # how one node depends on another


# --- structure ------------------------------------------------------------------------
def _is_class(graph, node_id) -> bool:
    data = graph.nodes[node_id]
    return bool(data.get("_callable_class")) and bool(data.get("source_file"))


def _line(data: dict) -> int:
    match = re.search(r"\d+", str(data.get("source_location") or ""))
    return int(match.group()) if match else 0


def file_siblings(graph, seed, limit: int = SIBLING_LIMIT) -> list:
    """Other top-level classes declared in *seed*'s header, nearest first (`MakeSchedule`
    beside `Schedule`, the binomial tree variants beside `BinomialTree`)."""
    if not graph.is_directed() or not _is_class(graph, seed):
        return []
    source, here = graph.nodes[seed].get("source_file"), _line(graph.nodes[seed])
    found = {}
    own = _label(seed, graph.nodes[seed])
    for header in _in(graph, seed, "contains"):
        for m in _out(graph, header, "contains"):
            label = _label(m, graph.nodes[m])
            if (m != seed and _is_class(graph, m) and graph.nodes[m].get("source_file") == source
                    and label != own and not label.startswith(own + "::")):     # not `Swap::arguments`
                found[m] = abs(_line(graph.nodes[m]) - here)
    return sorted(found, key=lambda m: (found[m], str(m)))[:limit]


def derived_of(graph, seeds: list) -> frozenset:
    """Every class that extends one of *seeds*."""
    if not graph.is_directed():
        return frozenset()
    return frozenset(u for seed in seeds for u in _in(graph, seed, "inherits"))


def derived_classes(graph, seed, limit: int = DERIVED_LIMIT) -> list:
    """Classes that extend *seed*, the best known first: the concrete implementations of
    an abstraction (`LinearInterpolation` of `Interpolation`, `Thirty360` of `DayCounter`).
    "Best known" is how many others call or use one, then how connected it is: `Interpolation`
    has 24, and in adjacency order `LinearInterpolation` was the 7th by degree and the 40th
    in the answer. Only for an abstraction with a handful of implementations (DERIVED_MAX)."""
    if not graph.is_directed() or not _is_class(graph, seed):
        return []
    found = {u for u in _in(graph, seed, "inherits") if _is_class(graph, u)}
    if len(found) > DERIVED_MAX:
        # A framework base (`PricingEngine` has hundreds): ten of them would be arbitrary,
        # and a question that wanted one would have named it.
        return []

    def used(n):
        return sum(1 for _a, _b, e in graph.in_edges(n, data=True) if e.get("relation") in _USAGE)
    return sorted(found, key=lambda n: (-used(n), -graph.degree(n), str(n)))[:limit]


def _derived_count(graph, node_id) -> int:
    return len(_in(graph, node_id, "inherits"))


def ancestors(graph, seed, depth: int = ANCESTOR_DEPTH, limit: int = ANCESTOR_LIMIT) -> list:
    """Base classes of *seed*, nearest first (HullWhite -> ... -> ShortRateModel), leaving out
    the framework's own (`Observer`, `XMLSerializable`, `Results`: dozens of derived classes
    each, in every answer and about nothing in particular)."""
    if not graph.is_directed() or not _is_class(graph, seed):
        return []
    out, frontier, seen = [], [seed], {seed}
    for _ in range(depth):
        following = []
        for node_id in frontier:
            for m in _out(graph, node_id, "inherits"):
                if m not in seen and _is_class(graph, m):
                    seen.add(m)
                    following.append(m)
                    if _derived_count(graph, m) <= DERIVED_MAX:
                        out.append(m)
        frontier = following
    return out[:limit]


# --- ordering ------------------------------------------------------------------------------
def content_stems(question: str) -> set:
    """Stems of the question's content words: no stopwords, filler or intent words, and,
    for a question about the fieldmap, none of the words that name a domain ("config" says
    which mapping is asked about, not which class - it made `DefaultCurveConfig` look like
    an answer about FX)."""
    terms = channel_terms(question)
    drop = TEST_WORDS + DOC_WORDS + SCHEMA_WORDS + ("fieldmap",)
    marked: set = set()
    if detect_intents(terms).fieldmap:
        drop += FIELDMAP_DOMAIN_WORDS
        marked = {a for a, b in zip(terms, terms[1:]) if b.startswith("config")}   # "curve" in "curve config"
    return {stem(t) for t in topic_terms(terms, drop) if len(t) >= 3 and t not in marked}


def unaccounted_stems(graph, stems: set, seeds: list) -> set:
    """The question's stems that no seed's own label already says. Every neighbour of a `Swap`
    seed named `swapLength` or `buildSwap` shares the word "swap" only because of the seed; it
    tells nothing about which neighbour the question wants, and sorting on it put fifty of them
    ahead of `LegData`."""
    said = set()
    for seed in seeds:
        said |= {stem(t) for t in split_tokens(_label(seed, graph.nodes[seed]))}
    return stems - said


def label_overlap(label: str, stems: set) -> int:
    """How many distinct content stems of the question the label's words cover."""
    return len({stem(t) for t in split_tokens(label)} & stems)


# --- putting it together ----------------------------------------------------------------------
def plan(graph, question: str, seeds: list) -> tuple[list, list]:
    """(lead, tail): priority nodes that go before the lexical seeds (the kind a question
    asks for) and after them (what completes an answer about a seed)."""
    terms = channel_terms(question)
    intents = detect_intents(terms)
    lead, tail = [], []
    for kind in ("tests", "docs", "schema"):
        if getattr(intents, kind):
            found = kind_seeds(graph, kind, terms)
            lead += found
            if kind == "schema":
                # What a type is composed of is its definition: `creditDefaultSwapData`
                # is `legData` and a credit curve, `fxBarrierOptionData` is `barrierData`
                # and `optionData`.
                types = [n for n in found if _label(n, graph.nodes[n]).endswith("(complexType)")]
                for node_id in types[:COMPOSITION_TYPES]:
                    tail += _out(graph, node_id, "composed_of")[:COMPOSITION_LIMIT] if graph.is_directed() else []
    if intents.fieldmap:
        tail += fieldmap_priority(graph, terms, intents.fieldmap)
    trades = pricing_subjects(graph, seeds) if intents.pricing else []
    for trade in trades[:FLOW_TRADES]:
        builders = registry_builders(graph, trade)
        tail += flow_nodes(graph, trade) + builders
        for builder in builders[:REGISTRY_ENGINES]:
            tail += builder_engines(graph, builder)
    class_seeds = [n for n in seeds if _is_class(graph, n)]
    for seed in class_seeds[:STRUCTURE_SEEDS]:
        tail += file_siblings(graph, seed) + ancestors(graph, seed)
    # Only the question's main subject: a second seed is often matched by one word ("trade")
    # and its implementations are not what was asked about.
    for seed in class_seeds[:1]:
        tail += derived_classes(graph, seed)
    tail += lexical_global(graph, question)
    return lead, tail


def lexical_global(graph, question: str, limit: int = LEXICAL_LIMIT,
                   min_overlap: int = LEXICAL_MIN_OVERLAP) -> list:
    """Source-bearing nodes anywhere whose label says at least *min_overlap* distinct
    content words of the question: `parsePeriod` for "what is a Period and how is it
    parsed" sits two hops beyond 80 other neighbours of the `Period` seed, and no seed
    or channel names it."""
    stems = content_stems(question)
    if len(stems) < min_overlap:
        return []
    index = graph.graph.get("_channel_stems")
    if index is None:
        index = {}
        for node_id, data in graph.nodes(data=True):
            if not data.get("source_file") or data.get("repo") == "OREFieldmap":
                continue
            for word in {stem(t) for t in split_tokens(_label(node_id, data))}:
                index.setdefault(word, []).append(node_id)
        graph.graph["_channel_stems"] = index
    count: dict = {}
    for word in stems:
        for node_id in index.get(word, ()):
            count[node_id] = count.get(node_id, 0) + 1
    def mostly_question(n):
        # `parsePeriod` says two words and is made of two; `auctionFinalPrice()` inside
        # `CreditDefaultSwapOption::AuctionSettlementInformation` also says "swap" and "price".
        return count[n] >= LEXICAL_SHARE * len(set(split_tokens(_label(n, graph.nodes[n]))))
    found = [n for n, c in count.items() if c >= min_overlap and mostly_question(n)]
    found.sort(key=lambda n: (-count[n], -graph.degree(n), str(n)))
    return found[:limit]


def member_usage(graph, seeds: list) -> dict:
    """For each member of a seed class (target of its `defines` / `method` edges), how many
    other nodes call or use it. A class has dozens of members and only some are its API:
    `Calendar::isBusinessDay` is called from everywhere, `Calendar::impl_` from nowhere, and
    in adjacency order they are equally likely to make the cut. (Raw degree is not this:
    it promotes `Date` and `string`.)"""
    if not graph.is_directed():
        return {}
    use: dict = {}
    for seed in seeds:
        for _u, member, e in graph.out_edges(seed, data=True):
            if e.get("relation") in ("defines", "method"):
                use[member] = sum(1 for _a, _b, ed in graph.in_edges(member, data=True)
                                  if ed.get("relation") in _USAGE)
    return use
