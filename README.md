# LSEG-MCP Server

[![CI Pipeline](https://github.com/GreenGrassBlueOcean/lseg_mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/GreenGrassBlueOcean/lseg_mcp/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/GreenGrassBlueOcean/lseg_mcp/graph/badge.svg)](https://codecov.io/gh/GreenGrassBlueOcean/lseg_mcp)
[![Platform Validation](https://img.shields.io/badge/Platforms-Windows%20%7C%20macOS%20%7C%20Linux-success?logo=githubactions)](https://github.com/GreenGrassBlueOcean/lseg_mcp/actions/workflows/ci.yml)
[![Python Support](https://img.shields.io/badge/Python-3.11%20%7C%203.12%20%7C%203.14-blue?logo=python)](https://github.com/GreenGrassBlueOcean/lseg_mcp/actions/workflows/ci.yml)

`lseg-mcp` is an asynchronous, introspective Model Context Protocol (MCP) server that acts as a definitive bridge between LLMs and the London Stock Exchange Group (LSEG) data APIs.

It enables AI agents to confidently draft perfectly formatted financial data retrieval pipelines in both Python (`lseg-data`) and R (`RefinitivR`).

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

### Example 2: Python (`lseg-data`)

**User Prompt:**
> "I need a Python script using lseg-data to get the daily Total Return for the S&P 500 constituents over the last 3 months."

**AI Agent Action:**
1. The agent searches the mapping index to confirm the exact parameter for 'Total Return' under the Python SDK mappings.
2. It calls `get_package_signature` for the `lseg.data.get_data` Python function to verify default arguments.
3. It calls `draft_api_call` to generate the runnable Python boilerplate, ensuring no deprecated variables are used.

## Features

- **Semantic Mapping Engine**: Translates legacy Refinitiv COA codes to industry-specific modern LSEG FCC formulas automatically. Handles additive arrays, ASR bracket notation, and industry routing.
- **Polyglot Code Generation**: Merges mapping-aware field resolution with live AST-verified function signatures to generate syntactically correct boilerplate in Python and R.
- **AST-Driven Introspection**: Performs static analysis to read function signatures directly from the Python and R source code without executing unsafe scripts.
- **Continuous Synchronization**: Automatically performs `git pull` and `pip install --upgrade` to ensure the MCP server is always synchronized with the underlying SDKs.
## Use Cases

`lseg-mcp` is designed for quantitative researchers, data engineers, and AI agents who need reliable, scalable access to financial data:
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

- Python 3.11+
- Git
- Access to LSEG Workspace (running in the background for live data retrieval)

## Installation

Clone the repository and install it in editable mode:

```bash
git clone https://github.com/GreenGrassBlueOcean/lseg-mcp.git
cd lseg-mcp
pip install -e ".[dev]"
```

## Configuration

The server operates over standard input/output (stdio) using the JSON-RPC 2.0 protocol.

### MCP Client Configuration

Point your MCP client (like Claude Desktop or Antigravity) to the executable:

```json
{
  "mcpServers": {
    "lseg-mcp": {
      "command": "C:\\path\\to\\lseg_mcp\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "lseg_mcp.server"
      ]
    }
  }
}
```

### Environment Variables

All paths are relative to the project root by default, but you can override them:
- `LSEG_MAPPING_PATH`: Absolute path to the Excel mapping matrix.
- `REFINITIVR_PATH`: Absolute path to the RefinitivR repository (cloned automatically if missing).

## Running the Server Locally

If you need to debug the server independently of an MCP client, you can use the cross-platform launch scripts which automatically tail the internal logs:

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
Get-Content -Path .lseg_cache\startup.log -Wait
```

**macOS / Linux:**
```bash
tail -f .lseg_cache/startup.log
```

## Testing

The project maintains **98% absolute line coverage**. To run the test suite:

```bash
pytest --cov=src --cov-report=term-missing tests/
```

## Architecture

For a comprehensive dive into the internal semantic mapping engine, the AST parser bracket-balancing algorithms, and the polyglot generator templates, please see [ARCHITECTURE.md](ARCHITECTURE.md).
