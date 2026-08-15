# Running this in Copilot (VS Code)

> **Requires Copilot Pro or better.** The GitHub Copilot **Free** plan does not
> include agent mode, so it cannot run terminal commands or write files — and
> every phase below needs both. On the free plan use
> [CLAUDE-CODE.md](CLAUDE-CODE.md) instead.

Everything outstanding, in order, with the exact text to paste into Copilot Chat.

**Set Copilot Chat to Agent mode first.** The dropdown at the top of the chat
panel says *Ask* / *Edit* / *Agent*. Ask mode cannot run terminal commands or
write files, and most of this needs both. If you only see Ask and Edit, update
the GitHub Copilot Chat extension.

Total time: about 30 minutes of terminal work, 1–2 hours of review for phase 2,
and phase 3 is either 10 minutes or several hours depending on one decision.

---

## Phase 0 — Setup (5 min, terminal)

Clone this repo next to your ORE checkout, then in the VS Code terminal:

```bash
pip install -r requirements.txt
```

Set the Engine path — permanently, so every later command finds it:

```powershell
# PowerShell, persists across sessions
setx ORE_ENGINE "C:\Users\<you>\OneDrive\Documents\repos\Engine"
setx ORE_GRAPH_OUT "C:\GraphifyOut\ORE"
```

Reopen the terminal, then check:

```bash
python -m oregraph info
```

Every line should resolve, and `graphify lib` should say `importable`. If
`ORE_GRAPH_OUT` warns about OneDrive, point it somewhere local — builds write
hundreds of megabytes and OneDrive will try to sync all of it.

---

## Phase 1 — Rebuild with the fixed pipeline (15–30 min, mostly waiting)

This is the step that turns the fixes into an actual graph. Your existing build
at `C:\GraphifyOut\ORE` is from 5 July and has the four defects; this replaces it.

Paste into Copilot Chat (Agent mode):

> Run `python -m oregraph coverage` and show me the output. Then run
> `python -m oregraph build` — it takes 15–30 minutes, so don't interrupt it,
> and report any chunk that reports FAILED. When it finishes run
> `python -m oregraph verify` and tell me whether every check passed.

What to expect:

- `coverage` should report **0 unclaimed code files**. If it lists any, the ORE
  layout has moved since I wrote the chunk map — tell Copilot to add a chunk for
  them in `oregraph/chunks.py`, following the two rules at the top of that file.
- `build` prints a per-chunk summary. `ORESwig` may extract thin — graphify has
  no SWIG `.i` extractor, so you mostly get the Python tests. That's expected.
- `verify` must end with **All checks passed**. The check that matters most is
  `cross-module edges present`, which was 0 in the old build.

The one result worth reading yourself:

> Show me the cross_module_edges count and the node count from the merge, and
> compare them to the old build's 78,619 nodes and 0 cross-module edges.

---

## Phase 2 — Fix the community names (1–2 hours, the valuable part)

All 272 curated names are currently attached to the wrong communities. See
[RELABELLING.md](RELABELLING.md) for why. Do the chunks your team actually
queries; you do not have to do all eleven.

### 2a. See the damage

> Run `python -m oregraph relabel --only OREAnalytics` and show me the full
> output. Explain how many names would move and how many are ambiguous.

### 2b. Relabel one chunk properly

Do not just accept the proposal — it is token matching and it collapses names
that share vocabulary. This prompt has Copilot redo the mapping from the actual
community contents, which is what produces a correct result:

> Read `%ORE_GRAPH_OUT%\OREAnalytics\graphify-out\.graphify_analysis.json`. It
> maps community id to a list of member node ids.
>
> For each of the 40 largest communities, look at the member node ids and write
> a 2–5 word plain-language name describing what that group of code does. The
> existing names in `labels/OREAnalytics.json` are good descriptions of ORE but
> are attached to the wrong ids — reuse the wording where a name fits a
> community, and write a new one where nothing fits.
>
> Write the result to `labels/OREAnalytics.json` as `{"<community id>": "<name>"}`,
> sorted by community id. Then show me the ten largest communities with your
> chosen name and five sample member ids each, so I can check them.

Check that sample. Node ids contain the source path, so a name like "SIMM CRIF
record definitions" should sit on members with `simm` and `crif` in their ids.

### 2c. Pin it so it never rots again

```bash
python -m oregraph relabel --only OREAnalytics --write-anchors
```

This records the 15 highest-degree members of each named community. Future
builds re-attach names by content overlap rather than by id, so re-clustering no
longer breaks them. Measured recovery on a correct mapping: 15/15 names with an
unchanged corpus, 15/15 at 10% file churn, 14/15 at 25%.

Repeat 2b–2c per chunk. Suggested order — `OREAnalytics`, `OREData`, `QuantExt`,
`OREDocs`, `OREXsd`, then the QuantLib chunks.

### 2d. Commit

> Commit the labels directory with the message
> "relabel: fix community mapping and pin anchors".

---

## Phase 3 — Extract the Examples configs (10 min, or several hours)

~1,100 XML portfolios and CSV market-data files are scanned for code but not
semantically extracted. **Read this whole section before starting — the first
decision determines whether this takes ten minutes or an afternoon.**

### The decision

graphify's semantic extraction wants to fan out across parallel subagents.
Copilot has no such API — graphify ships a separate VS Code variant of its skill
that opens by saying so and falls back to driving extraction one chunk at a time
by hand. At roughly 55 chunks that is hours of sequential turns.

**Recommended — use Gemini and skip all of it:**

```bash
pip install "graphifyy[gemini]"
setx GEMINI_API_KEY "<your key>"
```

With that set, extraction is fully automated regardless of host. This is a
one-time cost for the whole team, since the output gets committed.

**Alternative — narrow the corpus.** Portfolio XML carries nearly all the signal;
CSV market data is mostly numbers. Have Copilot edit `CORPORA["examples"]
["patterns"]` in `oregraph/semantic_prep.py` to `("**/*.xml",)`, which cuts it by
roughly a third.

**Alternative — do it in batches.** The flow below is resumable: `--validate`
reports exactly which chunks are still missing, so you can stop and resume
across days without losing work.

### 3a. Prepare the chunks

```bash
python -m oregraph semantic --corpus examples
```

This writes `semantic-chunks/examples/_manifest.json` — which files go in which
chunk, and where each chunk's output belongs. Expected-output fixtures and files
over 400 KB are excluded automatically.

### 3b. Extract

With a Gemini key set, ask Copilot:

> Read `docs/extraction-spec.md`. Then for each entry in
> `semantic-chunks/examples/_manifest.json`, run graphify's semantic extraction
> over that entry's files using the Gemini backend
> (`graphify.llm.extract_corpus_parallel(files, backend="gemini")`) and write
> the result to that entry's `output` path. Run
> `python -m oregraph semantic --corpus examples --validate` when done.

Without a key, in batches:

> Read `docs/extraction-spec.md` — it defines the exact JSON schema.
>
> Run `python -m oregraph semantic --corpus examples --validate` to see which
> chunks are missing. Take the first 5 missing chunks from
> `semantic-chunks/examples/_manifest.json`. For each one, read that chunk's
> files, extract entities and relationships following the spec, and write the
> JSON to that chunk's `output` path.
>
> These are ORE example configurations: extract the trade types, the pricing and
> curve configuration blocks, the market-data conventions they reference, and
> how portfolios relate to the configs they need. Set `source_file` on every
> node and edge to the file path exactly as it appears in the manifest.
>
> When the 5 are written, re-run --validate and tell me how many remain.

Repeat that last prompt until validate reports READY. The five-at-a-time limit
matters — Copilot degrades on long file-reading runs, and this keeps each turn
inside a context it handles well.

### 3c. Build and commit

```bash
python -m oregraph semantic --corpus examples --validate   # must say READY
python -m oregraph build --only OREExamplesConfig
python -m oregraph merge
python -m oregraph verify
```

> Commit `semantic-chunks/examples/` with the message
> "semantic: extract Examples portfolios and configs".

That commit is what means no teammate ever pays this cost again.

---

## Phase 4 — Wire it up (2 min)

```bash
python -m oregraph mcp --host both
```

Writes `.mcp.json` (Claude Code) and `.vscode/mcp.json` (Copilot) into your
Engine repo. Restart VS Code, then confirm the `graphify-ore` server is listed
under MCP servers in the Copilot Chat tool picker.

Install the auto-rebuild hook so the graph tracks your checkout:

```bash
cp hooks/post-merge <Engine>/.git/hooks/post-merge
chmod +x <Engine>/.git/hooks/post-merge
```

Then try it, from inside the Engine repo:

> How does OREData's swap trade builder reach QuantExt's pricing engines?

That question could not be answered at all before phase 1 — there was no path
between the two modules.

---

## Handing it to the team

Once phases 1–4 are done and `labels/` and `semantic-chunks/` are committed, a
teammate needs only:

```bash
git clone <repo> && cd ORE-Axon
pip install -r requirements.txt
setx ORE_ENGINE "<their Engine path>"
python -m oregraph build
python -m oregraph mcp --host both
```

No API key, no relabelling, no extraction — they inherit all of it. The build
runs against their own checkout, so the graph describes the code they actually
have.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `could not locate the ORE Engine repo` | `ORE_ENGINE` unset in this shell | reopen the terminal after `setx`, or pass `--engine` |
| `graphify is not importable` | installed to a different interpreter | `python -m pip install graphifyy` with the same `python` |
| `verify` says 0 cross-module edges | chunks built but merge used stale graphs | `python -m oregraph merge` again |
| `verify` says labels `id-unverified` | phase 2 not done for that chunk | expected until you relabel it |
| a chunk reports FAILED | that path is absent in your checkout | usually fine; check with `python -m oregraph coverage` |
| build is very slow | first run has no cache | subsequent builds reuse it and take seconds |
| Copilot won't run commands | Chat is in Ask mode | switch to Agent |
