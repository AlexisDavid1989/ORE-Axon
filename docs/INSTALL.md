# Install

## Prerequisites

- **Python 3.12** and `pip`.
- **git** on your PATH — the build, merge and `mcp` steps shell out to it.
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

6. Wire it into your editor:

   ```bash
   python -m oregraph mcp --host both
   ```

7. Restart VS Code, open your Engine repo (not ORE-Axon), and ask:

   > How does OREData's swap trade builder reach QuantExt's pricing engines?

## Caveats

- The graph reflects **your own checkout**. If your Engine is on a different
  commit than the one the curated labels in `labels/` were built against, a
  few community names may not re-attach — harmless, those communities just
  show up unnamed instead of missing.
- MCP configs (`.mcp.json`, `.vscode/mcp.json`) are written into your Engine
  repo and are **per-machine** — never commit them.
- Queries need a concrete symbol name as the entry point. `"portfolio/swap.hpp"`
  finds nothing; `"TradeFactory"` works.
