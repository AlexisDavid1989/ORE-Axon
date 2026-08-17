# Install

1. Clone and install:

   ```bash
   git clone https://github.com/AlexisDavid1989/ORE-Axon
   cd ORE-Axon
   pip install -r requirements.txt
   ```

2. Point it at your ORE checkout:

   ```powershell
   setx ORE_ENGINE "C:\path\to\your\Engine"
   ```

3. CLOSE the terminal and open a new one (`setx` only applies to new terminals).

4. Build the graph — takes 10-30 minutes, leave it running:

   ```bash
   cd ORE-Axon
   python -m oregraph build
   python -m oregraph verify
   ```

   `verify` must end with "All checks passed".

5. Wire it into your editor:

   ```bash
   python -m oregraph mcp --host both
   ```

6. Restart VS Code, open your Engine repo (not ORE-Axon), and ask:

   > How does OREData's swap trade builder reach QuantExt's pricing engines?

Requires Python 3.12 and about 1 GB of free disk. No API key needed.
Everything else has a sensible default.

## Caveats

- The graph reflects **your own checkout**. If your Engine is on a different
  commit than the one the curated labels in `labels/` were built against, a
  few community names may not re-attach — harmless, those communities just
  show up unnamed instead of missing.
- MCP configs (`.mcp.json`, `.vscode/mcp.json`) are written into your Engine
  repo and are **per-machine** — never commit them.
- Queries need a concrete symbol name as the entry point. `"portfolio/swap.hpp"`
  finds nothing; `"TradeFactory"` works.
