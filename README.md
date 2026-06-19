# LSEG-MCP Server

[![CI Pipeline](https://github.com/GreenGrassBlueOcean/lseg_mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/GreenGrassBlueOcean/lseg_mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/GreenGrassBlueOcean/lseg_mcp/graph/badge.svg)](https://codecov.io/gh/GreenGrassBlueOcean/lseg_mcp)
[![Platform Validation](https://img.shields.io/badge/Platforms-Windows%20%7C%20macOS%20%7C%20Linux-success?logo=githubactions)](https://github.com/GreenGrassBlueOcean/lseg_mcp/actions/workflows/ci.yml)
[![Python Support](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.14-blue?logo=python)](https://github.com/GreenGrassBlueOcean/lseg_mcp/actions/workflows/ci.yml)
![PyPI Compliant](https://img.shields.io/badge/PyPI-Compliant_(Not_Published)-yellow?logo=pypi)

> **This MCP server does not return market data.** It helps AI agents write *correct, runnable* LSEG data-retrieval code in Python ([`lseg-data`](https://pypi.org/project/lseg-data/)) or R ([`RefinitivR`](https://github.com/GreenGrassBlueOcean/RefinitivR)). You run the generated code against your own LSEG session to get the data.

`lseg-mcp` is an asynchronous, introspective Model Context Protocol (MCP) server that bridges LLMs and the London Stock Exchange Group (LSEG) data APIs. It resolves field names to the correct modern FCC/`TR.*` formulas, verifies function signatures via static AST analysis, and drafts perfectly formatted retrieval pipelines in both Python (`lseg-data`) and R (`RefinitivR`).

## Contents

- [Quick Start](#quick-start) · [Examples](#agentic-interaction-examples) · [Tools & Resources](#tools--resources) · [Features](#features)
- [Prerequisites](#prerequisites) · [Extending the Data Dictionary](#extending-the-data-dictionary-pricing-estimates-esg-) · [Environment Variables](#environment-variables)
- [Running Locally](#running-the-server-locally) · [Monitoring](#monitoring--observability) · [Testing](#testing) · [Architecture](ARCHITECTURE.md)

## Quick Start

Add this to your MCP client config (Claude Desktop, Cursor, VS Code, Antigravity, …) — no clone required:

```json
{
  "mcpServers": {
    "lseg-mcp": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/GreenGrassBlueOcean/lseg_mcp.git", "lseg-mcp"]
    }
  }
}
```

Once on PyPI, this simplifies to `"args": ["lseg-mcp"]` (publication pending).

> **First launch takes ~1–3 minutes**: it clones `RefinitivR`, installs `lseg-data`, parses the mapping workbook, and builds the AST indexes. Tail [`startup.log`](#monitoring--observability) while you wait — subsequent starts are fast.

## Agentic Interaction Examples

Once connected to your MCP client (like Claude Desktop or Antigravity), you can simply use natural language to draft perfect, mapping-aware financial code.

### Example 1: R (`RefinitivR`)

**User Prompt:**
> "Hey, write an R script using RefinitivR to pull the last 10 years of Gross Profit, EBITDA, and Basic EPS for AAPL.O and MSFT.O. Make sure to map these to the modern FCC formulas."

**AI Agent Action:**
The agent will autonomously use the `lseg-mcp` tools to:
1. Call `search_financial_mapping` to identify the correct FCC mappings (e.g., resolving legacy COA codes for Gross Profit to their modern `TR.GrossProfit` equivalents, respecting industry routes).
2. Call `get_package_signature` to retrieve the live, exact AST-parsed signature for `rd_GetData` from the `RefinitivR` package.
3. Call `draft_api_call` to merge the mappings with the AST signature, instantly generating a syntactically flawless R script.

**What you get back:**
```r
library(Refinitiv)
RefinitivR::rd_GetData(
  rics   = c("AAPL.O", "MSFT.O"),
  fields = c("TR.GrossProfit", "TR.EBITDA", "TR.EPS"),
  parameters = list(SDate = "0", EDate = "-9", Frq = "FY")
)
# NOTE: 'Gross Profit' resolved to TR.GrossProfit via industrial FCC routing.
```
Without the MCP, an LLM commonly hallucinates fields like `TR.Revenue` or the deprecated `Eikonformulas` parameter; with the mapping engine it lands on the correct modern `TR.*` formula and the live `fields` argument.

### Example 2: Python (`lseg-data`)

**User Prompt:**
> "I need a Python script using lseg-data to get the daily Total Return for the S&P 500 constituents over the last 3 months."

**AI Agent Action:**
1. The agent searches the mapping index to confirm the exact parameter for 'Total Return' under the Python SDK mappings.
2. It calls `get_package_signature` for the `lseg.data.get_data` Python function to verify default arguments.
3. It calls `draft_api_call` to generate the runnable Python boilerplate, ensuring no deprecated variables are used.

### Example 3: Extended Data Dictionary (Pricing / Estimates / ESG)

**User Prompt:**
> "Write R code using RefinitivR to fetch last 2 years of Price Close, consensus EPS (annual), and overall ESG score for AAPL.O and MSFT.O."

**AI Agent Action:**
1. Calls `search_data_dictionary("price close")` → gets `TR.PriceClose` + params.
2. Calls `search_data_dictionary("eps mean")` + notes that `rd_GetEstimates(view="view-summary/annual", package="standard")` is often superior for full consensus.
3. Calls `search_data_dictionary("esg score", category="ESG")` → surfaces `rd_GetESG` recommendation.
4. `draft_api_call(language="r", ...)` produces clean code using the right surface (general `rd_GetData` for price + specialized for estimates/ESG where appropriate), with parameter examples pulled from the dictionary.

## Tools & Resources

The server exposes **7 tools** and **3 read-only resources** over the MCP protocol:

| Tool | Purpose |
|------|---------|
| `search_financial_mapping` | Fuzzy-search the Financials → Company Fundamentals matrix; resolves legacy COA codes to modern FCC/`TR.*` formulas (industry-aware, batchable). |
| `search_data_dictionary` | Fuzzy-search the extended dictionary (Pricing, Estimates, ESG, Reference, Valuation, …) for real `TR.*` fields and their parameters. |
| `validate_lseg_formula` | Validate drafted fields, distinguishing `NOT_FOUND` from `INDUSTRY_MISMATCH`, with a data-dictionary fallback. |
| `get_package_signature` | Fetch a live, AST-parsed function signature (e.g. `rd_GetData`, `ld.get_data`) from the local index. |
| `draft_api_call` | Merge field resolution + AST signatures into runnable Python/R boilerplate (unresolved fields kept with a `# WARNING`). |
| `get_mapping_rules` | Retrieve the overarching mapping definitions and categorical rules. |
| `rescan_packages` | Force a re-index of the Python (`lseg-data`) and R (`RefinitivR`) packages. |

| Resource | Purpose |
|----------|---------|
| `matrix://financials_to_fundamentals` | Markdown view of the global mapping rules and category definitions. |
| `pkg://lseg-data/exports` | Live hierarchical view of all Python functions in the current `lseg-data` package. |
| `pkg://RefinitivR/exports` | Live hierarchical view of all R functions exported by the current `RefinitivR` commit. |

## Features

- **Semantic Mapping Engine**: Translates legacy Refinitiv COA codes to industry-specific modern LSEG FCC formulas automatically. Handles additive arrays, ASR bracket notation, and industry routing. Includes a **fuzzy fallback** (via `difflib`) so misspellings like "Groos Proffit" still resolve to the correct field.
- **Extended Data Dictionary**: Fuzzy-searchable catalog of hundreds of real TR.* fields for Pricing, Estimates, ESG, Reference, Valuation, etc. (seeded from RefinitivR usage + curated). Complements the financials matrix. See `search_data_dictionary`.
- **User-Extensible via DIB / Screener**: Drop "Custom_Fields", "Data Dictionary", or "DIB Export" sheets (or point `LSEG_DATA_DICTIONARY_PATH` at a CSV/Excel) — the LLM instantly sees your private or curated fields alongside the seeds. Includes ready-made harvesters in both R (`R/harvest_lseg_fields.R`) and Python (`scripts/harvest_lseg_fields.py` using pandas + openpyxl) for Screener "Export All as Formulas" and DIB exports.
- **Short-Lived Caching**: Uses an in-memory asynchronous TTL (Time-To-Live) cache to completely eliminate duplicate queries, optimizing response times and reducing duplicate tool round-trips and Excel/AST reloads (e.g., `[CACHE HIT] search_financial_mapping (key: AAPL.O Gross Profit) — 4.2ms`).
- **Polyglot Code Generation**: Merges mapping-aware field resolution with live AST-verified function signatures to generate syntactically correct boilerplate in Python and R. Fields that cannot be resolved through the mapping matrix or data dictionary are **included with a `# WARNING` comment** instead of being silently dropped.
- **Industry-Aware Validation**: `validate_lseg_formula` distinguishes between genuinely unknown fields (`NOT_FOUND`) and fields that exist but aren't applicable for the requested industry (`INDUSTRY_MISMATCH`), with a message listing the industries where the field *is* available.
- **AST-Driven Introspection**: Performs static analysis to read function signatures directly from the Python and R source code without executing unsafe scripts.
- **Continuous Synchronization**: Automatically performs `git pull` and `pip install --upgrade` to ensure the MCP server is always synchronized with the underlying SDKs.

## Use Cases

`lseg-mcp` is designed for quantitative researchers, data engineers, and AI agents who need reliable, scalable generation of financial data-retrieval code:
- **Autonomous Pipeline Generation**: Ask an AI agent to "pull 10 years of normalized EPS for Apple and Microsoft in R" and receive a robust, mapping-verified `RefinitivR` pipeline in seconds without manually hunting for COA codes.
- **Cross-Language Transitions**: Seamlessly port legacy Python scripts using `lseg-data` into enterprise R pipelines using the identical semantic translation engine.
- **Automated Refactoring**: Identify deprecated `Eikonformulas` in existing codebases and automatically map them to their modern FCC equivalents.

## Enterprise Resilience

Following a comprehensive architectural audit, `lseg-mcp` has been hardened for mission-critical deployments:
- **Asynchronous OOM & Timeout Protection**: Heavy background operations (like automated `git clone` or `pip install` syncing) are securely offloaded to dedicated `asyncio` background tasks. This entirely eliminates JSON-RPC starvation and client-side timeouts.
- **Batched Semantic Resolution**: The `search_financial_mapping` engine natively supports batched vector queries, drastically reducing roundtrip latency during complex formula resolutions.
- **Cross-Platform Stdio Integrity**: Fortified multi-OS launch scripts utilizing non-blocking pipe management guarantee zero-downtime server operations across Windows, macOS, and Linux, preventing premature EOF closures.
- **Headless Observability**: Features a hardened `os.fsync()` log streaming pipeline ensuring reliable cross-platform telemetry capture for Airflow or Docker environments.

## Prerequisites

The MCP server itself never connects to LSEG — it only resolves fields and drafts code. A live LSEG session is only needed to *execute* the code it produces.

| To run the MCP server | To execute the generated code |
|-----------------------|-------------------------------|
| Python 3.11+, Git, and `uv` or `pip` | LSEG Workspace (or Eikon) running, plus `lseg-data` (Python) / `RefinitivR` (R) |

## Installation & Configuration

The server operates over standard input/output (stdio) using the JSON-RPC 2.0 protocol. The recommended `uvx` config is in [Quick Start](#quick-start) — the same `command`/`args` block works for Claude Desktop, Cursor, VS Code, and Antigravity.

### Extending the Data Dictionary (Pricing, Estimates, ESG, ...)

The MCP ships with a strong built-in seed (mined from RefinitivR examples + production patterns) for `TR.PriceClose`, `TR.EPSMean`, `TR.ESGScore`, market cap, etc.

**Fastest way to add your own / more fields (Path 1):**

1. In LSEG Workspace Excel, use **Data Item Browser (DIB)** or **Screener → Export All as Formulas**.
2. Create (or append to) a sheet in your `LSEG_Mapping.xlsx` named `Custom_Fields` (or `Data Dictionary`, `DIB Export`, `Extended`).
3. Columns (any order, case-insensitive): `Field`, `Description`, `Category` (Pricing/Estimates/ESG/...), `Parameters`, `Notes`.
4. Or point an env var at a standalone file:
   ```powershell
   $env:LSEG_DATA_DICTIONARY_PATH = "C:\path\to\my_dib_export.csv"
   ```
   (CSV or .xlsx supported; see `data/sample_extended_fields.csv` for the exact flat format.)

5. Restart the MCP client or call `rescan_packages`. The new fields are immediately searchable via `search_data_dictionary` and used in `draft_api_call`.

**R helper for harvesting (recommended when you live in R/RefinitivR):**

```r
source("R/harvest_lseg_fields.R")          # from the repo, or copy the file
export_starter_packs(".")
# Then enrich with your DIB/Screener exports and write_for_lseg_mcp(...)
```

See `R/harvest_lseg_fields.R` and the "Example 3" above.

**Python harvester (pandas + openpyxl) – great when you prefer Python or work in notebooks:**

```bash
# From a Screener "Export All as Formulas" file
python scripts/harvest_lseg_fields.py -i my_screener.xlsx -c Estimates -o my_new_fields.csv

# From a DIB sheet
python scripts/harvest_lseg_fields.py -i dib_export.xlsx -s "My Fields" -c "Pricing" -o pricing.csv
```

The script:
- Scans every cell (including formula text) for `TR.*` items
- Handles both classic DIB tables and the rich Screener formula format
- Splits out parameters (e.g. `TR.EPSMean(SDate=0CY)` → field=`TR.EPSMean`, parameters=`SDate=0CY`)
- Writes the exact 5-column CSV the MCP expects

You can also import it from notebooks:

```python
from scripts.harvest_lseg_fields import parse_excel_for_tr_fields, build_field_catalog, write_for_lseg_mcp

fields = parse_excel_for_tr_fields("screener_export.xlsx")
cat = build_field_catalog(fields, category="ESG")
write_for_lseg_mcp(cat, "esg_harvested.csv")
```

See `scripts/harvest_lseg_fields.py` for the full CLI and more examples.

### Development Installation

If you wish to contribute to the server, you can clone and install it in editable mode:

```bash
git clone https://github.com/GreenGrassBlueOcean/lseg_mcp.git
cd lseg_mcp
pip install -e ".[dev]"
```

### Environment Variables

The server automatically manages its own dependencies and mappings within your platform's local application data directory (e.g., `%LOCALAPPDATA%\lseg-mcp\` on Windows). You can override these defaults:

| Variable | Default | Purpose |
|----------|---------|---------|
| `LSEG_MAPPING_PATH` | bundled `LSEG_Mapping.xlsx` | Absolute path to a custom Excel mapping matrix. |
| `LSEG_DATA_DICTIONARY_PATH` | bundled seed | Absolute path to a CSV/Excel of extended `TR.*` fields (see [Extending the Data Dictionary](#extending-the-data-dictionary-pricing-estimates-esg-)). |
| `REFINITIVR_PATH` | `%LOCALAPPDATA%/lseg-mcp/...` | Absolute path to the RefinitivR repository (auto-cloned if missing). |
| `LSEG_FORCE_REINDEX` | `0` | Set to `1` to force a full AST re-index on startup. |
| `LSEG_ALLOW_ENV_MUTATION` | `0` | Set to `1` to permit `rescan_packages` to mutate process environment variables. |

## Running the Server Locally

If you need to debug the server independently of an MCP client, you can run the executable directly in your terminal:

```bash
# If installed via pip or uv
lseg-mcp
```

**For local developers:** If you cloned the repository and created a virtual environment, you can use the cross-platform launch scripts:

**Windows:**
```cmd
run_server.cmd
```

**macOS / Linux:**
```bash
./run_server.sh
```

## Monitoring & Observability

Because the server runs headlessly within the MCP client, all console outputs (like `git clone` or `pip install` progress) and JSON-RPC traffic are hidden.

You can monitor the server's real-time internal status by tailing its log file. Open a separate terminal and run:

**Windows (PowerShell):**
```powershell
Get-Content -Path "$env:LOCALAPPDATA\lseg-mcp\logs\startup.log" -Wait
```

**macOS / Linux:**
```bash
tail -f ~/.cache/lseg-mcp/logs/startup.log
```

### Enabling Cache Debug Logs
During development, you can inspect cache events by setting the log level to `DEBUG` inside `src/lseg_mcp/server.py`:
```python
logger.setLevel(logging.DEBUG)
```
These logs will stream directly into the `startup.log` file:
```text
2026-05-21 19:56:35 [lseg_mcp] [CACHE MISS] search_financial_mapping (key: (('AAPL.O',), None, None, 25))
2026-05-21 19:56:35 [lseg_mcp] [CACHE LOAD] search_financial_mapping resolved in 14.2ms
2026-05-21 19:56:40 [lseg_mcp] [CACHE HIT] search_financial_mapping (key: (('AAPL.O',), None, None, 25))
```

## Testing

The project maintains **99% absolute line coverage** across **200+ tests**. To run the test suite:

```bash
pytest --cov=src --cov-report=term-missing tests/
```

## Architecture

For a comprehensive dive into the internal semantic mapping engine, the AST parser bracket-balancing algorithms, and the polyglot generator templates, please see [ARCHITECTURE.md](ARCHITECTURE.md).

## Contributing

Issues and pull requests are welcome — see [Development Installation](#development-installation) to get set up, and run `pytest` before submitting.

## License

Released under the [MIT License](LICENSE).

> **Disclaimer:** This is an independent, community-built tool and is **not affiliated with, endorsed by, or supported by** LSEG, Refinitiv, or Eikon. Use at your own risk.
