# Install

## Prerequisites

- **Python 3.12** and `pip`.
- **git** on your PATH — the build and merge steps shell out to it.
- **~1 GB of free disk** for the graph and its intermediates.
- **Access to the package index that serves `graphifyy==0.9.44`.** The pinned
  version lives on the internal mirror, not public PyPI (see step 1).

No API key is required. Everything else has a sensible default.

## Steps

1. Clone and install:

   ```bash
   git clone https://github.com/AlexisDavid1989/ORE-Axon
   cd ORE-Axon
   pip install -r requirements.txt
   ```

   If that fails with `No matching distribution found for graphifyy==0.9.44`,
   pip is not looking at the internal mirror. Point it there first, then
   re-run the install (PowerShell — note this is *not* bash `export`):

   ```powershell
   $env:PIP_INDEX_URL = "https://<username>:<token>@artifactory.lseg.com/artifactory/api/pypi/python-remotes/simple"
   pip install -r requirements.txt
   ```

2. Point it at your ORE checkout — the folder that **directly contains**
   `OREData`, `OREAnalytics`, `QuantExt` and `QuantLib` (not their parent, not
   one of them):

   ```powershell
   setx ORE_ENGINE "C:\path\to\your\Engine"
   ```

3. CLOSE the terminal and open a new one (`setx` only applies to new terminals).

4. Check it before the long build. This prints the resolved paths and confirms
   `graphifyy` is importable — fix anything here first:

   ```bash
   cd ORE-Axon
   python -m oregraph info
   ```

   `Engine repo` should be your checkout and `graphify lib` should say
   `importable`.

5. Build the graph — takes 10-30 minutes, leave it running:

   ```bash
   python -m oregraph build
   python -m oregraph verify
   ```

   `verify` must end with "All checks passed".

6. Make the ORE-Axon checkout discoverable by the custom agent:

   ```powershell
   setx ORE_AXON "C:\path\to\ORE-Axon"
   ```

   Close VS Code after running `setx`; newly opened windows will inherit it.
   In the new terminal, verify that the configured checkout provides the query
   command:

   ```powershell
   Set-Location $env:ORE_AXON
   python -c "import oregraph.cli; print(oregraph.cli.__file__)"
   python -m oregraph query-flow --help
   python -m oregraph query-path --help
   python -m oregraph query-symbol --help
   python -m oregraph query-batch --help
   python -m oregraph query-impact --help
   python -m oregraph query-example --help
   ```

   The printed module path must be inside your ORE-Axon checkout. If the help
   commands are invalid, update the checkout or correct `ORE_AXON`;
   do not continue with the agent installation.

7. Install the repository's Copilot agent in your Engine checkout:

   ```powershell
   New-Item -ItemType Directory -Force "$env:ORE_ENGINE\.github\agents" | Out-Null
   Copy-Item ".\agents\ore-axon.agent.md" "$env:ORE_ENGINE\.github\agents\ore-axon.agent.md"
   ```

   Do not add Graphify or ORE-Axon guidance to the Engine repository's
   `.github/copilot-instructions.md`. Those instructions are always loaded and
   can make ordinary control questions use the graph. The custom agent is
   intentionally opt-in.

8. Restart VS Code, open your Engine repo (not ORE-Axon), select **ore-axon**
   from the agent picker, and ask:

   > Look up exactly this symbol at depth 1 and summarize its direct graph
   > neighbors: `FdDefaultableEquityJumpDiffusionConvertibleBondEngine`.

   The agent should pass only the identifier, not the full sentence, to
   `oregraph query-symbol`. It should include
   `DefaultableEquityJumpDiffusionModel`, the discounting and credit inputs,
   `FxIndex`, `calculate`, `softCallBarrier`, and the conversion-ratio grid.
   It is a better installation check than a broad question about how swaps
   reach pricing engines, which can match hundreds of loosely related nodes.

   Ask the same question with the default agent when you need a no-graph
   control. Do not select **ore-axon** and do not invoke `/oreaxon` for that run.

## Caveats

- The graph reflects **your own checkout**. If your Engine is on a different
  commit than the one the curated labels in `labels/` were built against, a
  few community names may not re-attach — harmless, those communities just
  show up unnamed instead of missing.
- MCP is not required. The recommended Copilot integration calls
   `python -m oregraph query` through the workspace custom agent.
- Queries need a concrete symbol name as the entry point. `"portfolio/swap.hpp"`
  finds nothing; `"TradeFactory"` works.
- Use `query-symbol` for ranked exact neighborhoods, `query-flow` to discover
   pricing/build endpoints without guessing names, `query-path` for
   implementation flow between known symbols, and `query-batch` for several
   exact neighborhoods. Use `query-impact` for direct
   incoming and outgoing semantic dependencies, and `query-example` for a
   categorized existing implementation when planning code creation. These
   commands keep broad conceptual BFS available for discovery.
