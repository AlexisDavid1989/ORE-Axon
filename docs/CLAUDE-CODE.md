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
  4. Building and verifying is command-running, not reasoning. Judgement work —
  naming communities, per [RELABELLING.md](RELABELLING.md) — is worth Opus.
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

See [docs/INSTALL.md](INSTALL.md) for install and setup (steps 1-3). Once
`ORE_ENGINE` is set and the terminal is restarted, ask Claude Code:

```
Run `python -m oregraph info` and `python -m oregraph coverage` and show me
the output. Do NOT start the build yet.
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

`verify` must end with **All checks passed** (a trailing `(N warning(s))` is
fine). The line `curated labels attached` must PASS. `all curated names
attached` is a **warning, not a failure**: when you build against a different
ORE commit than the anchors were pinned on, a few names legitimately don't
re-attach and it reports `WARN` with their names — harmless, and it no longer
fails the build. A wholesale collapse is still a hard failure, caught by
`curated-name retention rate`. The names come from `labels/` in this repo and
re-attach themselves; there is no manual step.

`ORESwig` may extract thin; graphify has no SWIG `.i` extractor, so you mostly
get its Python tests. Not a problem.

---

## Phase 2 — Community names — **done**

Nothing to do here. All 530 community names have been rewritten against the
current clustering, audited and pinned to content anchors; they now re-attach
themselves on every rebuild. Skip to phase 3.

For maintenance — adding a name, correcting one, or recovering after an ORE
upgrade re-clusters the corpus — see **[RELABELLING.md](RELABELLING.md)**.

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

See [docs/INSTALL.md](INSTALL.md). No API key, no relabelling, no
extraction — they inherit all of it, built against their own checkout.

---

## If something goes wrong

| Symptom | Cause | Fix |
|---|---|---|
| `could not locate the ORE Engine repo` | env var not in this shell | restart the terminal after `setx`, or pass `--engine` |
| `graphify is not importable` | installed to a different interpreter | `python -m pip install graphifyy` with the same `python` |
| `verify`: 0 cross-module edges | merge used stale chunk graphs | `python -m oregraph merge` again |
| `verify`: names did not attach | anchors no longer win a community after re-clustering | re-run the loop in [RELABELLING.md](RELABELLING.md) for that chunk |
| a chunk reports FAILED | that path is absent in your checkout | check with `python -m oregraph coverage` |
| build very slow | first run, no cache | later builds reuse it and take seconds |
| hit a usage limit | long session or agent reading many files | `/clear`, switch to Sonnet, set `GEMINI_API_KEY` |
