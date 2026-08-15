# Running this in Claude Code

Everything outstanding, in order, with the exact text to paste.

Claude Code is the right host for this work on a Claude Pro plan. It runs
commands and writes files without any mode switch, and for phase 3 it can
dispatch extraction subagents in parallel, which is what graphify's semantic
pipeline is built around.

> **If you were planning to use Copilot:** the GitHub Copilot **Free** plan does
> not include agent mode, so it cannot run terminal commands or write files.
> Phases 1–4 all need both. Copilot Pro would work; Free will not.

Start it from this folder — either the VS Code extension, or `claude` in the
integrated terminal.

---

## Managing Pro plan usage

Pro has a rolling five-hour window and a weekly cap. This job fits comfortably
if you avoid the two things that waste it:

- **Use Sonnet for the mechanical phases.** `/model sonnet` before phases 1 and
  4. Building and verifying is command-running, not reasoning. Phase 2 is worth
  Opus — naming communities is judgement.
- **`/clear` between phases.** Every request re-sends the whole conversation, so
  a session left open across all four phases pays for phase 1's context while
  doing phase 3.
- **Set `GEMINI_API_KEY` before phase 3.** This is the big one. Without it,
  extracting ~1,100 example files means Claude reads all of them, which is the
  single most expensive thing in this project. With it, the reading happens on
  Gemini and barely touches your plan.

Check with `/usage` at any point.

---

## Phase 0 — Setup (5 min)

```
Read README.md and docs/CLAUDE-CODE.md in this repo, then help me set up.

I'm on Windows. My ORE checkout is at
  C:\Users\Alexis\OneDrive\Documents\repos\Engine
I want graph output at a NEW directory:
  C:\GraphifyOut\ORE-v2
My old build is at C:\GraphifyOut\ORE — leave it completely alone, it's my
working fallback until the new one verifies.

Do this:
1. pip install -r requirements.txt
2. Set ORE_ENGINE and ORE_GRAPH_OUT with setx, then tell me to restart the
   terminal so they take effect
3. python -m oregraph info
4. python -m oregraph coverage

Show me the output of info and coverage. Do NOT start the build yet.
```

`info` should show every path resolved and `graphify lib: importable`.
`coverage` should report **0 unclaimed code files** — if it lists any, ORE's
layout has shifted since the chunk map was written and that needs fixing before
you build.

---

## Phase 1 — Rebuild with the fixed pipeline (15–30 min)

`/model sonnet` first.

```
Run `python -m oregraph build`. It takes 15-30 minutes — don't interrupt it or
try to speed it up. Report any chunk that says FAILED.

Then run `python -m oregraph verify` and tell me whether every check passed.
Specifically compare the cross_module_edges count against the old build, which
had 0, and the node count against the old build's 78,619.
```

`verify` must end with **All checks passed**. Labels will report
`id-unverified` — expected until phase 2.

`ORESwig` may extract thin; graphify has no SWIG `.i` extractor, so you mostly
get its Python tests. Not a problem.

---

## Phase 2 — Fix the community names (1–2 hours, the valuable part)

`/clear`, then `/model opus`. This is judgement work.

All 272 curated names are attached to the wrong communities — see
[RELABELLING.md](RELABELLING.md). Do the chunks your team queries most; you do
not have to do all eleven.

### 2a. See the damage

```
Run `python -m oregraph relabel --only OREAnalytics` and show me the output.
How many names would move, and how many are ambiguous?
```

### 2b. Relabel properly

The proposal is token matching and collapses names that share vocabulary — don't
just accept it. This redoes the mapping from actual community contents:

```
Read %ORE_GRAPH_OUT%\OREAnalytics\graphify-out\.graphify_analysis.json — it maps
community id to member node ids.

For the 40 largest communities, read the member node ids and write a 2-5 word
plain-language name for what that group of code does. The names currently in
labels/OREAnalytics.json are good descriptions of ORE but attached to the wrong
ids — reuse the wording where it fits a community, write new where nothing fits.

Use subagents to examine communities in parallel — this is a lot of reading.

Write the result to labels/OREAnalytics.json as {"<id>": "<name>"} sorted by id.
Then show me the 10 largest communities with your chosen name and 5 sample
member ids each so I can check them.
```

Check that sample. Node ids contain source paths, so "SIMM CRIF record
definitions" should sit on members with `simm` and `crif` in their ids.

### 2c. Pin it

```bash
python -m oregraph relabel --only OREAnalytics --write-anchors
```

Records the 15 highest-degree members per named community, so future builds
re-attach names by content rather than by id. Measured recovery: 15/15 on an
unchanged corpus, 15/15 at 10% file churn, 14/15 at 25%.

Repeat 2b–2c per chunk. Order: `OREAnalytics`, `OREData`, `QuantExt`,
`OREDocs`, `OREXsd`, then QuantLib.

Commit when done: `git commit -m "relabel: fix community mapping and pin anchors"`

---

## Phase 3 — Extract the Examples configs

`/clear` first.

**Set `GEMINI_API_KEY` before starting**, or this becomes the most expensive
part of the project by a wide margin:

```bash
pip install "graphifyy[gemini]"
setx GEMINI_API_KEY "<your key>"
```

### 3a. Prepare

```bash
python -m oregraph semantic --corpus examples
```

Writes `semantic-chunks/examples/_manifest.json` — which files go in which
chunk and where each chunk's output belongs. Expected-output fixtures and files
over 400 KB are excluded automatically.

### 3b. Extract

With a Gemini key:

```
Read docs/extraction-spec.md. For each entry in
semantic-chunks/examples/_manifest.json, run graphify's semantic extraction over
that entry's files using the Gemini backend
(graphify.llm.extract_corpus_parallel(files, backend="gemini")) and write the
result to that entry's "output" path.

Then run `python -m oregraph semantic --corpus examples --validate`.
```

Without a key — slower and uses real plan budget, so consider narrowing to
`("**/*.xml",)` in `oregraph/semantic_prep.py` first:

```
Read docs/extraction-spec.md — it defines the exact JSON schema.

Run `python -m oregraph semantic --corpus examples --validate` to see which
chunks are missing. Dispatch one subagent per missing chunk, in parallel,
batching about 8 at a time. Each subagent reads its chunk's files from the
manifest, extracts entities and relationships per the spec, and writes JSON to
that chunk's "output" path.

These are ORE example configurations: extract trade types, pricing and curve
configuration blocks, the market-data conventions they reference, and how
portfolios relate to the configs they need. Set source_file on every node and
edge to the path exactly as it appears in the manifest.

Re-run --validate after each batch and tell me how many remain.
```

The flow is resumable — `--validate` reports exactly what's still missing, so
you can stop and pick up later without losing work.

### 3c. Build and commit

```bash
python -m oregraph semantic --corpus examples --validate   # must say READY
python -m oregraph build --only OREExamplesConfig
python -m oregraph merge
python -m oregraph verify
```

Commit `semantic-chunks/examples/` — that commit is what means no teammate ever
pays this cost again.

---

## Phase 4 — Wire it up (2 min)

```bash
python -m oregraph mcp --host both
cp hooks/post-merge <Engine>/.git/hooks/post-merge
```

Writes `.mcp.json` and `.vscode/mcp.json` into the Engine repo, so the graph is
available whichever host a teammate uses. Restart, open the **Engine** repo (not
this one), and try:

> How does OREData's swap trade builder reach QuantExt's pricing engines?

That was unanswerable before phase 1 — there was no path between the modules.

Once it verifies, point your old MCP config at `ORE-v2` and retire
`C:\GraphifyOut\ORE`.

---

## Handing it to the team

```bash
git clone <repo> && cd ore-graphify
pip install -r requirements.txt
setx ORE_ENGINE "<their Engine path>"
python -m oregraph build && python -m oregraph mcp --host both
```

No API key, no relabelling, no extraction — they inherit all of it, built
against their own checkout.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `could not locate the ORE Engine repo` | env var not in this shell | restart the terminal after `setx`, or pass `--engine` |
| `graphify is not importable` | installed to a different interpreter | `python -m pip install graphifyy` with the same `python` |
| `verify`: 0 cross-module edges | merge used stale chunk graphs | `python -m oregraph merge` again |
| `verify`: labels `id-unverified` | phase 2 not done for that chunk | expected |
| a chunk reports FAILED | that path is absent in your checkout | check with `python -m oregraph coverage` |
| build very slow | first run, no cache | later builds reuse it and take seconds |
| hit a usage limit | long session or agent reading many files | `/clear`, switch to Sonnet, set `GEMINI_API_KEY` |
